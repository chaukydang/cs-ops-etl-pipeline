from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any

from selenium.common.exceptions import (
    InvalidSessionIdException,
    NoSuchWindowException,
    TimeoutException,
    WebDriverException,
)

from modules.dashboard.auth.lark_login_flow import (
    LarkLoginFlow,
    LarkLoginFlowError,
)
from modules.dashboard.auth.outlook_otp_reader import (
    OutlookLoginRequiredError,
    OutlookOtpReader,
    OutlookOtpTimeoutError,
)
from modules.dashboard.auth_context import AeolusAuthContext
from modules.dashboard.browser.exceptions import (
    BrowserAutomationError,
    DriverNotReadyError,
    StepTransitionError,
)
from modules.dashboard.browser.session import BrowserSession


class AeolusAuthError(Exception):
    """Lỗi authentication chung của Aeolus."""


class AeolusLoginRequiredError(AeolusAuthError):
    """Dashboard hoặc Outlook yêu cầu đăng nhập."""


class AeolusTokenNotFoundError(AeolusAuthError):
    """Không tìm thấy Open-Api-Token."""


class AeolusDashboardError(AeolusAuthError):
    """Dashboard không load đúng."""


class AeolusAuthManager:
    TOKEN_HEADER_NAMES = (
        "open-api-token",
        "x-open-api-token",
        "openapitoken",
    )

    TOKEN_REQUEST_PATHS = (
        "/aeolus/openapi/v3/queryengine/dimvaluealias",
        "/aeolus/openapi/",
        "/aeolus/vqs/openapi/",
    )

    AUTHENTICATED_URL_KEYWORDS = (
        "csp.byteintl.com/workspace/report_center/aeolus",
        "aeolus-va.bytelemon.com/aeolus-open",
        "aeolus-va.bytelemon.com/aeolus/",
    )

    LOGIN_URL_KEYWORDS = (
        "mpsso-sg.bytelemon.com",
        "accounts.larksuite.com",
        "passport",
        "signin",
        "sign-in",
        "/sso",
    )

    def __init__(
        self,
        dashboard_url: str,
        app_id: str | int,
        chrome_driver_path: str | Path,
        project_root: str | Path,
        lark_email: str,
        lark_password: str,
        outlook_mail_url: str,
        outlook_email: str,
        outlook_password: str,
        outlook_totp_secret: str = "",
        page_timeout: int = 90,
        element_timeout: int = 20,
        transition_timeout: int = 60,
        login_timeout: int = 300,
        outlook_login_timeout: int = 300,
        manual_mfa_timeout: int = 300,
        otp_timeout: int = 180,
        token_capture_timeout: int = 120,
        headless: bool = False,
    ) -> None:
        self.dashboard_url = dashboard_url.strip()
        self.app_id = str(app_id).strip()
        self.lark_email = lark_email.strip()
        self.lark_password = lark_password
        self.outlook_mail_url = (
            outlook_mail_url.strip()
            or "https://outlook.office.com/mail/"
        )
        self.outlook_email = outlook_email.strip()
        self.outlook_password = outlook_password
        self.outlook_totp_secret = outlook_totp_secret.strip()
        self.project_root = Path(project_root).resolve()
        self.chrome_driver_path = Path(chrome_driver_path).resolve()
        self.page_timeout = page_timeout
        self.element_timeout = element_timeout
        self.transition_timeout = transition_timeout
        self.login_timeout = login_timeout
        self.outlook_login_timeout = outlook_login_timeout
        self.manual_mfa_timeout = manual_mfa_timeout
        self.otp_timeout = otp_timeout
        self.token_capture_timeout = token_capture_timeout
        self.headless = headless

        self.browser = BrowserSession(
            project_root=self.project_root,
            chrome_driver_path=self.chrome_driver_path,
            profile_name="aeolus",
            page_timeout=self.page_timeout,
            element_timeout=self.element_timeout,
            transition_timeout=self.transition_timeout,
            headless=self.headless,
        )

        self.cached_auth_context: AeolusAuthContext | None = None
        self.logger = logging.getLogger(self.__class__.__name__)
        self.network_request_urls: dict[str, str] = {}
        self.network_request_headers: dict[str, dict[str, Any]] = {}
        self.network_extra_headers: dict[str, dict[str, Any]] = {}

    def ensure_authenticated(
        self,
        force_refresh: bool = False,
    ) -> AeolusAuthContext:
        if (
            not force_refresh
            and self.cached_auth_context is not None
            and self.cached_auth_context.is_valid()
        ):
            return self.cached_auth_context

        self._ensure_browser_initialized()
        self._enable_network_capture()
        self._open_dashboard()

        if not self.is_dashboard_authenticated():
            print("[DashboardAUTH] Login required")
            self._run_lark_login_flow()

        self._wait_for_dashboard(timeout=self.login_timeout)

        # Không clear performance logs ở đây. Request mang token thường
        # xuất hiện trong quá trình Authorize -> redirect -> dashboard load.
        token = self._capture_token_with_fallback()
        cookies = self.get_cookies()

        auth_context = AeolusAuthContext(
            open_api_token=token,
            cookies=cookies,
            app_id=self.app_id,
        )
        self.cached_auth_context = auth_context

        print(
            "[DashboardAUTH] Authentication ready "
            f"| Cookies={len(cookies)}"
        )
        return auth_context

    def refresh_auth(self) -> AeolusAuthContext:
        self.cached_auth_context = None
        alive, reason = self.browser.is_alive()

        if not alive:
            self.logger.warning("Browser unavailable: %s", reason)
            self.browser.close()
            self.browser.initialize()

        return self.ensure_authenticated(force_refresh=True)

    def _ensure_browser_initialized(self) -> None:
        if self.browser.driver is None or self.browser.actions is None:
            self.browser.initialize()
            return

        alive, reason = self.browser.is_alive()
        print(
            "[DashboardAUTH] "
            f"Browser alive={alive} | Reason={reason}"
        )

        if alive:
            return

        self.browser.close()
        time.sleep(2)
        self.browser.initialize()

    def _enable_network_capture(self) -> None:
        driver = self._get_driver()

        try:
            driver.execute_cdp_cmd("Network.enable", {})
        except Exception as error:
            self.logger.warning("Cannot enable CDP Network: %s", error)

    def _open_dashboard(self) -> None:
        driver = self._get_driver()
        main_tab = self.browser.main_tab

        if main_tab and main_tab in driver.window_handles:
            self.browser.switch_to(main_tab)

        print("[DashboardAUTH] Opening dashboard...")
        self.browser.open(self.dashboard_url, retries=3)
        print(
            "[DashboardAUTH] Current URL: "
            f"{self._safe_current_url()}"
        )
        time.sleep(3)

    def is_dashboard_authenticated(self) -> bool:
        driver = self.browser.driver

        if driver is None:
            return False

        try:
            current_url = str(driver.current_url or "").lower()

            if not current_url or current_url in ("about:blank", "data:"):
                return False

            return any(
                keyword in current_url
                for keyword in self.AUTHENTICATED_URL_KEYWORDS
            )

        except (
            InvalidSessionIdException,
            NoSuchWindowException,
            WebDriverException,
        ):
            return False

    def _wait_for_dashboard(self, timeout: int) -> None:
        actions = self._get_actions()
        actions.wait_until(
            condition=self.is_dashboard_authenticated,
            condition_name="Dashboard dashboard",
            timeout=timeout,
        )
        print("[DashboardAUTH] Dashboard authenticated")

    def _run_lark_login_flow(self) -> None:
        driver = self._get_driver()
        actions = self._get_actions()

        outlook_reader = OutlookOtpReader(
            driver=driver,
            actions=actions,
            mail_url=self.outlook_mail_url,
            otp_timeout=self.otp_timeout,
            poll_interval=5,
            outlook_email=self.outlook_email,
            outlook_password=self.outlook_password,
            outlook_totp_secret=self.outlook_totp_secret,
            outlook_login_timeout=self.outlook_login_timeout,
            manual_mfa_timeout=self.manual_mfa_timeout,
        )

        login_flow = LarkLoginFlow(
            actions=actions,
            email=self.lark_email,
            password=self.lark_password,
            outlook_reader=outlook_reader,
            dashboard_condition=self.is_dashboard_authenticated,
            login_timeout=self.login_timeout,
            step_delay=3.0,
        )

        try:
            login_flow.run()
        except OutlookLoginRequiredError as error:
            raise AeolusLoginRequiredError(
                f"Outlook login thất bại: {error}"
            ) from error
        except OutlookOtpTimeoutError as error:
            raise AeolusLoginRequiredError(
                "Không lấy được email OTP Lark "
                f"trong {self.otp_timeout} giây"
            ) from error
        except (
            LarkLoginFlowError,
            BrowserAutomationError,
            DriverNotReadyError,
            StepTransitionError,
        ) as error:
            raise AeolusAuthError(
                f"Lark auto-login thất bại: {error}"
            ) from error

    def _capture_token_with_fallback(self) -> str:
        print("[DashboardAUTH] Checking existing Network events for token...")
        token = self.capture_open_api_token(15, False)
        if token:
            return token

        iframe_url = self._find_aeolus_iframe_url()
        if iframe_url:
            print(f"[DashboardAUTH] Dashboard iframe detected: {iframe_url}")
            token = self._open_aeolus_url_and_capture(iframe_url)
            if token:
                return token

        driver = self._get_driver()
        actions = self._get_actions()
        print("[DashboardAUTH] Refreshing parent dashboard...")
        try:
            driver.execute_cdp_cmd("Network.setCacheDisabled", {"cacheDisabled": True})
            driver.refresh()
        except TimeoutException:
            self.logger.warning("Dashboard refresh timed out")

        actions.wait_document_ready(self.page_timeout)
        self._wait_for_dashboard(self.page_timeout)
        time.sleep(5)

        iframe_url = self._find_aeolus_iframe_url()
        if iframe_url:
            token = self._open_aeolus_url_and_capture(iframe_url)
            if token:
                return token

        token = self.capture_open_api_token(self.token_capture_timeout, True)
        if token is None:
            raise AeolusTokenNotFoundError("Không tìm thấy Open-Api-Token")
        return token

    def _find_aeolus_iframe_url(self) -> str | None:
        driver = self._get_driver()
        try:
            urls = driver.execute_script(
                "return Array.from(document.querySelectorAll('iframe')).map(f => f.src || '');"
            )
        except Exception as error:
            self.logger.warning("Cannot inspect iframes: %s", error)
            return None

        for url in urls or []:
            clean_url = str(url or "").strip()
            if "aeolus-va.bytelemon.com" in clean_url.lower():
                return clean_url
        return None

    def _open_aeolus_url_and_capture(self, iframe_url: str) -> str | None:
        driver = self._get_driver()
        actions = self._get_actions()
        source_tab = driver.current_window_handle
        aeolus_tab = None
        try:
            driver.switch_to.new_window("tab")
            aeolus_tab = driver.current_window_handle
            self._reset_network_cache()
            try:
                driver.get_log("performance")
            except Exception:
                pass
            try:
                driver.get(iframe_url)
            except TimeoutException:
                self.logger.warning("Dashboard iframe load timed out")
            actions.wait_document_ready(self.page_timeout)
            return self.capture_open_api_token(self.token_capture_timeout, False)
        finally:
            if aeolus_tab and aeolus_tab in driver.window_handles:
                try:
                    driver.switch_to.window(aeolus_tab)
                    driver.close()
                except Exception:
                    pass
            if source_tab in driver.window_handles:
                driver.switch_to.window(source_tab)

    def _reset_network_cache(self) -> None:
        self.network_request_urls.clear()
        self.network_request_headers.clear()
        self.network_extra_headers.clear()

    def capture_open_api_token(
        self,
        timeout: int | None = None,
        raise_on_timeout: bool = True,
    ) -> str | None:
        timeout = timeout or self.token_capture_timeout
        deadline = time.time() + timeout
        checked_events = 0
        aeolus_requests = 0
        matched_url = ""

        while time.time() < deadline:
            result = self._find_token_in_performance_logs()
            checked_events += int(result["event_count"])
            aeolus_requests += int(result["aeolus_request_count"])
            if result["matched_url"]:
                matched_url = str(result["matched_url"])
            if result["token"]:
                print("[DashboardAUTH] Open-Api-Token captured")
                print(f"[DashboardAUTH] Captured from: {matched_url or 'Dashboard request headers'}")
                return str(result["token"])
            time.sleep(0.25)

        if raise_on_timeout:
            raise AeolusTokenNotFoundError(
                "Không tìm thấy Open-Api-Token. "
                f"Events={checked_events}, Dashboard requests={aeolus_requests}, "
                f"Last URL={matched_url or 'none'}, Current page={self._safe_current_url()}"
            )
        return None

    def _find_token_in_performance_logs(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "token": None,
            "event_count": 0,
            "aeolus_request_count": 0,
            "matched_url": "",
        }
        driver = self.browser.driver
        if driver is None:
            return result

        try:
            entries = driver.get_log("performance")
        except Exception as error:
            self.logger.warning("Cannot read performance logs: %s", error)
            return result

        result["event_count"] = len(entries)

        for entry in entries:
            try:
                message = json.loads(entry["message"]).get("message", {})
                method = str(message.get("method", ""))
                params = message.get("params", {})
                request_id = str(params.get("requestId", ""))

                if method == "Network.requestWillBeSent":
                    request = params.get("request", {})
                    url = str(request.get("url", ""))
                    headers = request.get("headers", {})
                    if request_id:
                        self.network_request_urls[request_id] = url
                        if isinstance(headers, dict):
                            self.network_request_headers[request_id] = headers
                    if self._is_aeolus_host(url):
                        result["aeolus_request_count"] += 1
                        result["matched_url"] = url
                        token = self._extract_open_api_token(headers)
                        if token:
                            result["token"] = token
                            return result

                elif method == "Network.requestWillBeSentExtraInfo":
                    headers = params.get("headers", {})
                    headers_text = str(params.get("headersText", "") or "")
                    if request_id and isinstance(headers, dict):
                        self.network_extra_headers[request_id] = headers
                    url = self.network_request_urls.get(request_id, "")
                    token = self._extract_open_api_token(headers)
                    if not token:
                        token = self._extract_token_from_headers_text(headers_text)
                    if token and (not url or self._is_aeolus_host(url)):
                        result["token"] = token
                        result["matched_url"] = url
                        return result
            except Exception:
                continue

        for request_id, url in self.network_request_urls.items():
            if not self._is_aeolus_host(url):
                continue
            token = self._extract_open_api_token(
                self.network_extra_headers.get(request_id, {})
            ) or self._extract_open_api_token(
                self.network_request_headers.get(request_id, {})
            )
            if token:
                result["token"] = token
                result["matched_url"] = url
                return result
        return result

    @classmethod
    def _extract_open_api_token(cls, headers: dict[str, Any]) -> str | None:
        if not isinstance(headers, dict):
            return None
        for name, value in headers.items():
            normalized = str(name).strip().lower().replace("_", "-")
            if normalized in cls.TOKEN_HEADER_NAMES:
                token = str(value or "").strip()
                if token:
                    return token
        return None

    @classmethod
    def _extract_token_from_headers_text(cls, headers_text: str) -> str | None:
        for line in str(headers_text or "").splitlines():
            if ":" not in line:
                continue
            name, value = line.split(":", 1)
            normalized = name.strip().lower().replace("_", "-")
            if normalized in cls.TOKEN_HEADER_NAMES and value.strip():
                return value.strip()
        return None

    @staticmethod
    def _is_aeolus_host(request_url: str) -> bool:
        url = str(request_url or "").strip().lower()
        return url.startswith("https://aeolus-va.bytelemon.com/") or url.startswith(
            "http://aeolus-va.bytelemon.com/"
        )

    def get_cookies(self) -> dict[str, str]:
        driver = self._get_driver()
        return {
            cookie["name"]: cookie["value"]
            for cookie in driver.get_cookies()
            if cookie.get("name")
        }

    def _get_driver(self):
        driver = self.browser.driver
        if driver is None:
            raise AeolusAuthError(
                "Browser driver chưa được khởi tạo"
            )
        return driver

    def _get_actions(self):
        actions = self.browser.actions
        if actions is None:
            raise AeolusAuthError(
                "Browser actions chưa được khởi tạo"
            )
        return actions

    def _safe_current_url(self) -> str:
        driver = self.browser.driver
        if driver is None:
            return ""

        try:
            return str(driver.current_url or "")
        except Exception:
            return ""

    def close(self) -> None:
        self.cached_auth_context = None
        self.browser.close()
