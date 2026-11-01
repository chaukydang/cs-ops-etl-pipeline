from __future__ import annotations

import logging
import time
from pathlib import Path

from selenium import webdriver
from selenium.common.exceptions import (
    InvalidSessionIdException,
    NoSuchWindowException,
    SessionNotCreatedException,
    TimeoutException,
    WebDriverException,
)
from selenium.webdriver.chrome.service import Service

from modules.dashboard.browser.actions import BrowserActions
from modules.dashboard.browser.exceptions import (
    DriverNotReadyError,
)


class BrowserSession:
    """
    Quản lý Chrome driver:

    - Chrome profile.
    - Download folder.
    - Driver lifecycle.
    - Navigation.
    - Browser tabs.
    - Driver health.
    """

    def __init__(
        self,
        project_root: str | Path,
        chrome_driver_path: str | Path,
        profile_name: str = "aeolus",
        download_directory: str | Path | None = None,
        page_timeout: int = 90,
        element_timeout: int = 20,
        transition_timeout: int = 60,
        headless: bool = False,
    ) -> None:
        self.project_root = Path(
            project_root
        ).resolve()

        self.chrome_driver_path = Path(
            chrome_driver_path
        ).resolve()

        self.user_data_dir = (
            self.project_root
            / "data"
            / "browser_profile"
            / profile_name
        )

        if download_directory is None:
            self.download_directory = (
                self.project_root
                / "downloads"
            )
        else:
            self.download_directory = Path(
                download_directory
            ).resolve()

        self.page_timeout = page_timeout
        self.element_timeout = element_timeout
        self.transition_timeout = transition_timeout
        self.headless = headless

        self.driver: webdriver.Chrome | None = None
        self.actions: BrowserActions | None = None

        self.main_tab: str | None = None

        self.logger = logging.getLogger(
            self.__class__.__name__
        )

    # ========================================================
    # OPTIONS
    # ========================================================

    def build_options(
        self,
    ) -> webdriver.ChromeOptions:
        options = webdriver.ChromeOptions()

        options.add_argument(
            f"--user-data-dir={self.user_data_dir}"
        )

        options.add_argument(
            "--profile-directory=Default"
        )

        options.add_argument(
            "--start-maximized"
        )

        options.add_argument(
            "--disable-notifications"
        )

        options.add_argument(
            "--disable-popup-blocking"
        )

        options.add_argument(
            "--no-first-run"
        )

        options.add_argument(
            "--no-default-browser-check"
        )

        options.add_argument(
            "--disable-dev-shm-usage"
        )

        if self.headless:
            options.add_argument(
                "--headless=new"
            )

            options.add_argument(
                "--window-size=1920,1080"
            )

        options.add_experimental_option(
            "prefs",
            {
                "download.default_directory": str(
                    self.download_directory
                ),
                "download.prompt_for_download": False,
                "download.directory_upgrade": True,
                "safebrowsing.enabled": True,
                "profile.default_content_setting_values"
                ".geolocation": 2,
            },
        )

        options.set_capability(
            "goog:loggingPrefs",
            {
                "performance": "ALL",
                "browser": "ALL",
            },
        )

        return options

    # ========================================================
    # INITIALIZATION
    # ========================================================

    def initialize(
        self,
    ) -> None:
        self.user_data_dir.mkdir(
            parents=True,
            exist_ok=True,
        )

        self.download_directory.mkdir(
            parents=True,
            exist_ok=True,
        )

        options = self.build_options()

        self.driver = self._create_driver(
            options
        )

        self.driver.set_page_load_timeout(
            self.page_timeout
        )

        self.driver.execute_cdp_cmd(
            "Network.enable",
            {},
        )

        self.actions = BrowserActions(
            driver=self.driver,
            default_timeout=(
                self.element_timeout
            ),
            transition_timeout=(
                self.transition_timeout
            ),
            poll_interval=0.5,
        )

        self.main_tab = (
            self.driver.current_window_handle
        )

        print(
            "[BROWSER] Driver initialized "
            f"| profile={self.user_data_dir}"
        )

    def _create_driver(
        self,
        options: webdriver.ChromeOptions,
    ) -> webdriver.Chrome:
        if self.chrome_driver_path.exists():
            try:
                service = Service(
                    executable_path=str(
                        self.chrome_driver_path
                    )
                )

                return webdriver.Chrome(
                    service=service,
                    options=options,
                )

            except SessionNotCreatedException as error:
                self.logger.warning(
                    "ChromeDriver không khớp "
                    "Chrome version. "
                    "Using Selenium Manager. "
                    "Detail=%s",
                    str(error).splitlines()[0],
                )

        else:
            self.logger.warning(
                "Không tìm thấy chromedriver: %s. "
                "Using Selenium Manager.",
                self.chrome_driver_path,
            )

        return webdriver.Chrome(
            options=options
        )

    # ========================================================
    # READY CHECK
    # ========================================================

    def ensure_ready(
        self,
    ) -> None:
        if (
            self.driver is None
            or self.actions is None
        ):
            raise DriverNotReadyError(
                "BrowserSession chưa initialize"
            )

    # ========================================================
    # NAVIGATION
    # ========================================================

    def open(
        self,
        url: str,
        retries: int = 3,
    ) -> bool:
        self.ensure_ready()

        assert self.driver is not None
        assert self.actions is not None

        last_error: Exception | None = None

        for attempt in range(
            1,
            retries + 1,
        ):
            try:
                self.driver.get(url)

                self.actions.wait_document_ready(
                    timeout=self.page_timeout
                )

                return True

            except TimeoutException:
                self.logger.warning(
                    "Page load timed out but "
                    "browser may still be usable | "
                    "url=%s",
                    url,
                )

                return True

            except Exception as error:
                last_error = error

                self.logger.warning(
                    "Open URL failed | "
                    "attempt=%s/%s | error=%s",
                    attempt,
                    retries,
                    error,
                )

                if attempt < retries:
                    time.sleep(2)

        raise WebDriverException(
            "Không mở được URL sau "
            f"{retries} lần. "
            f"Last error={last_error}"
        )

    def refresh(
        self,
    ) -> None:
        self.ensure_ready()

        assert self.driver is not None
        assert self.actions is not None

        try:
            self.driver.refresh()

        except TimeoutException:
            self.logger.warning(
                "Page refresh timed out"
            )

        self.actions.wait_document_ready(
            timeout=self.page_timeout
        )

    # ========================================================
    # TABS
    # ========================================================

    def open_new_tab(
        self,
        url: str | None = None,
    ) -> str:
        self.ensure_ready()

        assert self.driver is not None

        self.driver.switch_to.new_window(
            "tab"
        )

        handle = (
            self.driver.current_window_handle
        )

        if url:
            try:
                self.driver.get(url)

            except TimeoutException:
                pass

        return handle

    def switch_to(
        self,
        handle: str,
    ) -> None:
        self.ensure_ready()

        assert self.driver is not None

        if handle not in self.driver.window_handles:
            raise NoSuchWindowException(
                f"Tab không tồn tại: {handle}"
            )

        self.driver.switch_to.window(handle)

    def close_tab(
        self,
        handle: str,
        fallback_handle: str | None = None,
    ) -> None:
        self.ensure_ready()

        assert self.driver is not None

        if handle not in self.driver.window_handles:
            return

        self.driver.switch_to.window(handle)
        self.driver.close()

        remaining_handles = (
            self.driver.window_handles
        )

        if not remaining_handles:
            return

        if (
            fallback_handle
            and fallback_handle
            in remaining_handles
        ):
            self.driver.switch_to.window(
                fallback_handle
            )

        else:
            self.driver.switch_to.window(
                remaining_handles[0]
            )

    # ========================================================
    # HEALTH CHECK
    # ========================================================

    def is_alive(
        self,
    ) -> tuple[bool, str]:
        if self.driver is None:
            return (
                False,
                "Driver object is None",
            )

        try:
            service = getattr(
                self.driver,
                "service",
                None,
            )

            process = getattr(
                service,
                "process",
                None,
            )

            if (
                process is not None
                and process.poll() is not None
            ):
                return (
                    False,
                    "ChromeDriver process stopped",
                )

        except Exception as error:
            self.logger.warning(
                "Driver process check failed: %s",
                error,
            )

        try:
            if not self.driver.window_handles:
                return (
                    False,
                    "Browser has no active window",
                )

            self.driver.execute_script(
                "return document.readyState"
            )

            return (
                True,
                "ChromeDriver session is active",
            )

        except InvalidSessionIdException as error:
            return (
                False,
                f"Invalid Selenium session: {error}",
            )

        except NoSuchWindowException as error:
            return (
                False,
                f"Browser window closed: {error}",
            )

        except WebDriverException as error:
            return (
                False,
                f"ChromeDriver not responding: {error}",
            )

        except Exception as error:
            return (
                False,
                f"Driver health check error: {error}",
            )

    # ========================================================
    # CLEANUP
    # ========================================================

    def close(
        self,
    ) -> None:
        driver = self.driver

        self.driver = None
        self.actions = None
        self.main_tab = None

        if driver is None:
            return

        try:
            service = getattr(
                driver,
                "service",
                None,
            )

            process = getattr(
                service,
                "process",
                None,
            )

            if (
                process is not None
                and process.poll() is not None
            ):
                print(
                    "[BROWSER] "
                    "ChromeDriver already stopped"
                )

                return

        except Exception:
            pass

        try:
            driver.quit()

        except (
            InvalidSessionIdException,
            NoSuchWindowException,
            WebDriverException,
            ConnectionError,
            OSError,
        ):
            pass

        except Exception as error:
            self.logger.warning(
                "Cannot close Chrome normally: %s",
                error,
            )

        print(
            "[BROWSER] Driver closed"
        )