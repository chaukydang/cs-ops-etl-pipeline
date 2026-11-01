from __future__ import annotations

import logging
import time
from collections.abc import Callable

from selenium.common.exceptions import TimeoutException
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.remote.webelement import WebElement
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

from modules.dashboard.auth.outlook_otp_reader import (
    OutlookLoginRequiredError,
    OutlookOtpReader,
    OutlookOtpTimeoutError,
)
from modules.dashboard.browser.actions import BrowserActions

Condition = Callable[[], bool]


class LarkLoginFlowError(Exception):
    """Lỗi chung trong quá trình đăng nhập Lark."""


class LarkEmailStepError(LarkLoginFlowError):
    """Không hoàn tất được bước email."""


class LarkPasswordStepError(LarkLoginFlowError):
    """Không hoàn tất được bước password."""


class LarkVerificationStepError(LarkLoginFlowError):
    """Không hoàn tất được bước verification."""


class LarkOtpStepError(LarkLoginFlowError):
    """Không hoàn tất được bước OTP."""


class LarkLoginFlow:
    """
    Strict login flow:

    BPO -> Email -> Terms -> Email Next -> Password -> Enter
    -> prepare Outlook -> Switch to Email Verification
    -> get unread OTP -> fill OTP -> OTP Next -> Authorize -> Dashboard
    """

    BPO_XPATH = (
        "//div[contains(@class,'semi-card')]"
        "[.//span[normalize-space()='Business Partner / BPO User']]"
    )

    EMAIL_INPUT_XPATH = "//input[@data-test='login-mail-input']"
    TERMS_INPUT_XPATH = "//input[@type='checkbox' and @role='checkbox']"
    EMAIL_NEXT_XPATH = "//button[@data-test='login-phone-next-btn']"

    PASSWORD_INPUT_XPATH = "//input[@data-test='login-pwd-input']"

    SWITCH_EMAIL_XPATH = (
        "//div[contains(@class,'base-tab-pane') "
        "and not(contains(@class,'base-tab-pane-inactive'))]"
        "//div[contains(@class,'switch-button-base')]"
        "//button[normalize-space()='Switch to Email Verification']"
    )

    OTP_INPUT_XPATH = (
        "//div[contains(@class,'base-tab-pane') "
        "and not(contains(@class,'base-tab-pane-inactive'))]"
        "//div[contains(@class,'base-code-box')]"
        "//input[@name='code_box_input_item' and not(@disabled)][1]"
    )

    ALL_ACTIVE_OTP_INPUTS_XPATH = (
        "//div[contains(@class,'base-tab-pane') "
        "and not(contains(@class,'base-tab-pane-inactive'))]"
        "//div[contains(@class,'base-code-box')]"
        "//input[@name='code_box_input_item']"
    )

    OTP_NEXT_XPATH = (
        "//div[contains(@class,'base-tab-pane') "
        "and not(contains(@class,'base-tab-pane-inactive'))]"
        "//button[@data-test='login-pwd-next-btn' and not(@disabled)]"
    )

    AUTHORIZE_XPATH = (
        "//button[@data-authz-action='confirm' "
        "and normalize-space()='Authorize']"
    )

    NOTICE_AGREE_XPATH = "//button[normalize-space()='Agree']"

    def __init__(
        self,
        actions: BrowserActions,
        email: str,
        password: str,
        outlook_reader: OutlookOtpReader,
        dashboard_condition: Condition,
        login_timeout: int = 300,
        step_delay: float = 3.0,
    ) -> None:
        self.actions = actions
        self.driver = actions.driver
        self.email = email.strip()
        self.password = password
        self.outlook_reader = outlook_reader
        self.dashboard_condition = dashboard_condition
        self.login_timeout = login_timeout
        self.step_delay = max(2.0, min(float(step_delay), 4.0))
        self.logger = logging.getLogger(self.__class__.__name__)

    def run(self) -> None:
        self._validate_credentials()
        print("[LARK LOGIN] Starting strict tested login flow")

        if self.dashboard_condition():
            print("[LARK LOGIN] Dashboard already authenticated")
            return

        # Existing session can occasionally land directly on Authorize.
        authorize = self._find_visible(By.XPATH, self.AUTHORIZE_XPATH)
        if authorize is not None:
            self._authorize(authorize)
            return

        self._select_bpo_if_present()

        landing_state = self._wait_after_bpo(timeout=60)

        if landing_state == "dashboard":
            print("[LARK LOGIN] Dashboard detected after BPO")
            return

        if landing_state == "authorize":
            print(
                "[LARK LOGIN] Existing Lark session detected; "
                "skipping Email, Password and OTP"
            )
            self._authorize_and_wait_dashboard()
            print("[LARK LOGIN] Login flow completed")
            return

        if landing_state != "email":
            raise LarkLoginFlowError(
                "Không xác định được màn hình sau BPO: "
                f"{landing_state}"
            )

        self._input_email_and_next()
        self._input_password_and_submit()
        self._prepare_outlook_and_switch_email()
        self._read_and_submit_otp()
        self._authorize_and_wait_dashboard()

        print("[LARK LOGIN] Login flow completed")

    def _select_bpo_if_present(self) -> None:
        try:
            card = WebDriverWait(self.driver, 30).until(
                EC.element_to_be_clickable((By.XPATH, self.BPO_XPATH))
            )
        except TimeoutException:
            # BPO may already have been selected in the current session.
            if self._find_visible(By.XPATH, self.EMAIL_INPUT_XPATH) is not None:
                return
            if self._find_visible(By.XPATH, self.AUTHORIZE_XPATH) is not None:
                return
            raise LarkLoginFlowError(
                "Không tìm thấy Business Partner / BPO User"
            )

        card.click()
        print("[LARK LOGIN] BPO provider clicked")
        self._pause("BPO provider")

    def _wait_after_bpo(self, timeout: int = 60) -> str:
        """Wait for Email, Authorize, or Dashboard after BPO selection."""
        deadline = time.time() + timeout
        last_url = ""

        while time.time() < deadline:
            if self.dashboard_condition():
                return "dashboard"

            authorize = self._find_visible(By.XPATH, self.AUTHORIZE_XPATH)
            if authorize is not None:
                return "authorize"

            email_input = self._find_visible(By.XPATH, self.EMAIL_INPUT_XPATH)
            if email_input is not None:
                return "email"

            current_url = self._safe_current_url()
            if current_url and current_url != last_url:
                print(f"[LARK LOGIN] Waiting after BPO | URL={current_url}")
                last_url = current_url

            time.sleep(0.5)

        raise LarkLoginFlowError(
            "Timeout sau khi chọn BPO. Không tìm thấy Email, "
            "Authorize hoặc Dashboard. "
            f"URL={self._safe_current_url()}"
        )

    def _input_email_and_next(self) -> None:
        try:
            email_input = WebDriverWait(self.driver, 60).until(
                EC.element_to_be_clickable((By.XPATH, self.EMAIL_INPUT_XPATH))
            )
            email_input.click()
            email_input.send_keys(Keys.CONTROL, "a")
            email_input.send_keys(Keys.BACKSPACE)
            email_input.send_keys(self.email)
            print("[LARK LOGIN] Email filled")
            self._pause("fill email", 2.0)

            self._accept_terms_if_needed()
            self._pause("Terms", 2.0)

            next_button = WebDriverWait(self.driver, 30).until(
                EC.element_to_be_clickable((By.XPATH, self.EMAIL_NEXT_XPATH))
            )
            self.driver.execute_script("arguments[0].click();", next_button)
            print("[LARK LOGIN] Email Next clicked")
            self._pause("Email Next")

            self._agree_notice_if_present()

        except TimeoutException as error:
            raise LarkEmailStepError(
                "Timeout tại bước Email hoặc Email Next"
            ) from error

    def _accept_terms_if_needed(self) -> None:
        try:
            checkbox = WebDriverWait(self.driver, 15).until(
                EC.presence_of_element_located((By.XPATH, self.TERMS_INPUT_XPATH))
            )
        except TimeoutException:
            self.logger.warning("Terms checkbox not found; continuing")
            return

        checked = False
        try:
            checked = checkbox.is_selected() or (
                str(checkbox.get_attribute("aria-checked") or "").lower()
                == "true"
            )
        except Exception:
            pass

        if not checked:
            self.driver.execute_script("arguments[0].click();", checkbox)
            print("[LARK LOGIN] Terms checkbox clicked")

    def _agree_notice_if_present(self) -> None:
        try:
            agree = WebDriverWait(self.driver, 3).until(
                EC.element_to_be_clickable((By.XPATH, self.NOTICE_AGREE_XPATH))
            )
        except TimeoutException:
            return

        self.driver.execute_script("arguments[0].click();", agree)
        print("[LARK LOGIN] Terms Notice agreed")
        self._pause("Terms Agree")

    def _input_password_and_submit(self) -> None:
        try:
            password_input = WebDriverWait(self.driver, 60).until(
                EC.element_to_be_clickable(
                    (By.XPATH, self.PASSWORD_INPUT_XPATH)
                )
            )
            password_input.click()
            password_input.send_keys(Keys.CONTROL, "a")
            password_input.send_keys(Keys.BACKSPACE)
            password_input.send_keys(self.password)
            print("[LARK LOGIN] Password filled")
            self._pause("fill password")

            # This matches the verified notebook flow.
            password_input.send_keys(Keys.ENTER)
            print("[LARK LOGIN] Password submitted with Enter")
            self._pause("Password submit")

        except TimeoutException as error:
            raise LarkPasswordStepError(
                "Không tìm thấy password input active"
            ) from error

    def _prepare_outlook_and_switch_email(self) -> None:
        print("[LARK LOGIN] Preparing Outlook before requesting OTP")
        self.outlook_reader.prepare_inbox_before_otp()
        self._pause("prepare Outlook inbox")

        try:
            button = WebDriverWait(self.driver, 60).until(
                EC.presence_of_element_located((By.XPATH, self.SWITCH_EMAIL_XPATH))
            )
        except TimeoutException as error:
            raise LarkVerificationStepError(
                "Không tìm thấy Switch to Email Verification trong active pane"
            ) from error

        self.driver.execute_script(
            "arguments[0].scrollIntoView({block: 'center'});",
            button,
        )
        self.driver.execute_script("arguments[0].click();", button)
        print("[LARK LOGIN] Switch to Email Verification clicked")

        try:
            WebDriverWait(self.driver, 60).until(
                EC.element_to_be_clickable((By.XPATH, self.OTP_INPUT_XPATH))
            )
        except TimeoutException as error:
            raise LarkVerificationStepError(
                "Đã click Switch Email nhưng OTP input không xuất hiện"
            ) from error

        self._pause("Switch to Email Verification")

    def _read_and_submit_otp(self) -> None:
        print("[LARK LOGIN] Waiting for new unread Lark OTP")

        try:
            otp = self.outlook_reader.wait_for_new_unread_lark_otp()
        except (OutlookLoginRequiredError, OutlookOtpTimeoutError):
            raise

        self._pause("return from Outlook")
        self._input_otp(otp)
        self._pause("fill OTP")

        print("[LARK LOGIN] Waiting for automatic OTP submission")

        if self._wait_after_otp_submit(timeout=30):
            print("[LARK LOGIN] OTP submitted automatically")
            return

        next_button = self._find_optional_otp_next()
        if next_button is None:
            raise LarkOtpStepError(
                "Đã nhập đủ OTP nhưng trang không tự chuyển "
                "và cũng không tìm thấy OTP Next. "
                f"URL={self._safe_current_url()}"
            )

        self.driver.execute_script(
            "arguments[0].focus(); arguments[0].click();",
            next_button,
        )
        print("[LARK LOGIN] OTP Next clicked")

        if not self._wait_after_otp_submit(timeout=120):
            raise LarkOtpStepError(
                "Đã click OTP Next nhưng không xuất hiện "
                "Authorize hoặc dashboard"
            )

        self._pause("OTP Next")

    def _wait_after_otp_submit(self, timeout: int = 30) -> bool:
        deadline = time.time() + timeout

        while time.time() < deadline:
            if self.dashboard_condition():
                return True

            if self._find_visible(By.XPATH, self.AUTHORIZE_XPATH) is not None:
                return True

            if self._find_visible(By.XPATH, self.PASSWORD_INPUT_XPATH) is not None:
                return True

            time.sleep(0.5)

        return False

    def _find_optional_otp_next(self) -> WebElement | None:
        xpaths = (
            self.OTP_NEXT_XPATH,
            (
                "//div[contains(@class,'base-tab-pane') "
                "and not(contains(@class,'base-tab-pane-inactive'))]"
                "//button[normalize-space()='Next' and not(@disabled)]"
            ),
            (
                "//button[@data-test='login-pwd-next-btn' "
                "and not(@disabled)]"
            ),
        )

        for xpath in xpaths:
            element = self._find_visible(By.XPATH, xpath)
            if element is not None:
                return element

        return None

    def _input_otp(self, otp: str) -> None:
        clean_otp = "".join(char for char in str(otp).strip() if char.isdigit())
        if len(clean_otp) != 6:
            raise LarkOtpStepError("OTP phải gồm đúng 6 chữ số")

        try:
            otp_input = WebDriverWait(self.driver, 30).until(
                EC.element_to_be_clickable((By.XPATH, self.OTP_INPUT_XPATH))
            )
        except TimeoutException as error:
            raise LarkOtpStepError("Không tìm thấy OTP input active") from error

        otp_input.click()
        otp_input.send_keys(Keys.CONTROL, "a")
        otp_input.send_keys(Keys.BACKSPACE)
        otp_input.send_keys(clean_otp)

        if not WebDriverWait(self.driver, 15).until(self._otp_complete):
            raise LarkOtpStepError("OTP chưa được nhập đủ 6 chữ số")

        print("[LARK LOGIN] OTP filled")

    def _otp_complete(self, driver) -> bool:
        try:
            inputs = driver.find_elements(By.XPATH, self.ALL_ACTIVE_OTP_INPUTS_XPATH)
            value = "".join(
                str(item.get_attribute("value") or "") for item in inputs
            )
            return len(value) == 6 and value.isdigit()
        except Exception:
            return False

    def _authorize_and_wait_dashboard(self) -> None:
        if self.dashboard_condition():
            print("[LARK LOGIN] Dashboard detected, Authorize skipped")
            return

        try:
            button = WebDriverWait(self.driver, 120).until(
                EC.presence_of_element_located(
                    (By.XPATH, self.AUTHORIZE_XPATH)
                )
            )
        except TimeoutException as error:
            if self.dashboard_condition():
                return
            raise LarkVerificationStepError(
                "OTP đã được nhập nhưng không tìm thấy "
                "Authorize sau 120 giây"
            ) from error

        self.driver.execute_script(
            "arguments[0].focus(); arguments[0].click();",
            button,
        )
        print("[LARK LOGIN] Authorize clicked")

        self.actions.wait_until(
            condition=self.dashboard_condition,
            condition_name="Dashboard dashboard",
            timeout=120,
        )
        self._pause("Authorize")

    def _authorize(self, button: WebElement) -> None:
        self.driver.execute_script("arguments[0].click();", button)
        print("[LARK LOGIN] Authorize clicked")
        self.actions.wait_until(
            condition=self.dashboard_condition,
            condition_name="Dashboard dashboard",
            timeout=120,
        )

    def _find_visible(self, by: str, selector: str) -> WebElement | None:
        try:
            for element in self.driver.find_elements(by, selector):
                if element.is_displayed() and element.is_enabled():
                    return element
        except Exception:
            pass
        return None

    def _safe_current_url(self) -> str:
        try:
            return str(self.driver.current_url or "")
        except Exception:
            return ""

    def _pause(self, step_name: str, seconds: float | None = None) -> None:
        wait_seconds = (
            self.step_delay
            if seconds is None
            else max(2.0, min(float(seconds), 4.0))
        )
        print(
            f"[LARK LOGIN] Waiting {wait_seconds:.1f}s after {step_name}"
        )
        time.sleep(wait_seconds)

    def _validate_credentials(self) -> None:
        if not self.email:
            raise LarkLoginFlowError("LARK_LOGIN_EMAIL đang trống")
        if not self.password:
            raise LarkLoginFlowError("LARK_LOGIN_PASSWORD đang trống")
