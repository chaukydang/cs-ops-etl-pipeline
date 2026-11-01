from __future__ import annotations

import logging
import time
from collections.abc import Callable
from typing import TypeAlias

from selenium.common.exceptions import (
    ElementClickInterceptedException,
    ElementNotInteractableException,
    StaleElementReferenceException,
    TimeoutException,
    WebDriverException,
)
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.remote.webdriver import WebDriver
from selenium.webdriver.remote.webelement import WebElement
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

from modules.dashboard.browser.exceptions import (
    DriverNotReadyError,
    ElementActionError,
    ElementNotFoundError,
    StepTransitionError,
)

# ============================================================
# TYPE ALIASES
# ============================================================

Locator: TypeAlias = tuple[str, str]
Condition: TypeAlias = Callable[[], bool]


# ============================================================
# BROWSER ACTIONS
# ============================================================


class BrowserActions:
    """
    Selenium helper dùng chung.

    Chức năng:

    - Kiểm tra driver.
    - Chờ document load.
    - Tìm element present, visible hoặc clickable.
    - Nhập dữ liệu và xác nhận input giữ đúng value.
    - Click bằng native, ActionChains và JavaScript.
    - Chỉ xác nhận click thành công khi màn hình tiếp theo xuất hiện.
    """

    def __init__(
        self,
        driver: WebDriver,
        default_timeout: int = 20,
        transition_timeout: int = 60,
        poll_interval: float = 0.5,
    ) -> None:
        self.driver = driver
        self.default_timeout = default_timeout
        self.transition_timeout = transition_timeout
        self.poll_interval = poll_interval

        self.logger = logging.getLogger(
            self.__class__.__name__
        )

    # ========================================================
    # DRIVER
    # ========================================================

    def ensure_driver_ready(self) -> None:
        if self.driver is None:
            raise DriverNotReadyError(
                "Driver chưa được khởi tạo"
            )

        try:
            handles = self.driver.window_handles

            if not handles:
                raise DriverNotReadyError(
                    "Browser không có window đang hoạt động"
                )

            self.driver.execute_script(
                "return document.readyState"
            )

        except DriverNotReadyError:
            raise

        except WebDriverException as error:
            raise DriverNotReadyError(
                f"Driver không phản hồi: {error}"
            ) from error

    def wait_document_ready(
        self,
        timeout: int | None = None,
    ) -> bool:
        self.ensure_driver_ready()

        timeout = timeout or self.default_timeout

        try:
            WebDriverWait(
                self.driver,
                timeout,
                poll_frequency=self.poll_interval,
            ).until(
                lambda driver: (
                    driver.execute_script(
                        "return document.readyState"
                    )
                    == "complete"
                )
            )

            return True

        except TimeoutException:
            return False

    # ========================================================
    # ELEMENT FINDERS
    # ========================================================

    def find_present(
        self,
        locator: Locator,
        element_name: str = "element",
        timeout: int | None = None,
    ) -> WebElement:
        self.ensure_driver_ready()

        timeout = timeout or self.default_timeout

        try:
            return WebDriverWait(
                self.driver,
                timeout,
                poll_frequency=self.poll_interval,
                ignored_exceptions=(
                    StaleElementReferenceException,
                ),
            ).until(
                EC.presence_of_element_located(
                    locator
                )
            )

        except TimeoutException as error:
            raise ElementNotFoundError(
                f"Không tìm thấy {element_name} "
                f"trong {timeout} giây"
            ) from error

    def find_visible(
        self,
        locator: Locator,
        element_name: str = "element",
        timeout: int | None = None,
    ) -> WebElement:
        self.ensure_driver_ready()

        timeout = timeout or self.default_timeout

        try:
            return WebDriverWait(
                self.driver,
                timeout,
                poll_frequency=self.poll_interval,
                ignored_exceptions=(
                    StaleElementReferenceException,
                ),
            ).until(
                EC.visibility_of_element_located(
                    locator
                )
            )

        except TimeoutException as error:
            raise ElementNotFoundError(
                f"{element_name} không visible "
                f"trong {timeout} giây"
            ) from error

    def find_clickable(
        self,
        locator: Locator,
        element_name: str = "element",
        timeout: int | None = None,
    ) -> WebElement:
        self.ensure_driver_ready()

        timeout = timeout or self.default_timeout

        try:
            return WebDriverWait(
                self.driver,
                timeout,
                poll_frequency=self.poll_interval,
                ignored_exceptions=(
                    StaleElementReferenceException,
                ),
            ).until(
                EC.element_to_be_clickable(
                    locator
                )
            )

        except TimeoutException as error:
            raise ElementNotFoundError(
                f"{element_name} không clickable "
                f"trong {timeout} giây"
            ) from error

    def find_first_visible(
        self,
        locators: tuple[Locator, ...],
        element_name: str = "element",
        timeout: int | None = None,
    ) -> tuple[WebElement, Locator]:
        self.ensure_driver_ready()

        timeout = timeout or self.default_timeout
        deadline = time.time() + timeout

        while time.time() < deadline:
            for locator in locators:
                try:
                    elements = self.driver.find_elements(
                        *locator
                    )

                    for element in elements:
                        try:
                            if element.is_displayed():
                                return element, locator

                        except StaleElementReferenceException:
                            continue

                        except Exception:
                            continue

                except WebDriverException:
                    continue

            time.sleep(self.poll_interval)

        raise ElementNotFoundError(
            f"Không tìm thấy {element_name} "
            f"trong {timeout} giây"
        )

    def find_first_clickable(
        self,
        locators: tuple[Locator, ...],
        element_name: str = "element",
        timeout: int | None = None,
    ) -> tuple[WebElement, Locator]:
        """
        Tìm element đầu tiên đáp ứng đầy đủ:

        - Visible.
        - Selenium báo enabled.
        - Không có attribute disabled.
        - aria-disabled không phải true.
        - Class không chứa disabled.
        """

        self.ensure_driver_ready()

        timeout = timeout or self.default_timeout
        deadline = time.time() + timeout

        while time.time() < deadline:
            for locator in locators:
                try:
                    elements = self.driver.find_elements(
                        *locator
                    )

                    for element in elements:
                        try:
                            if not element.is_displayed():
                                continue

                            if not element.is_enabled():
                                continue

                            disabled_attribute = (
                                element.get_attribute(
                                    "disabled"
                                )
                            )

                            aria_disabled = str(
                                element.get_attribute(
                                    "aria-disabled"
                                )
                                or ""
                            ).lower()

                            class_name = str(
                                element.get_attribute(
                                    "class"
                                )
                                or ""
                            ).lower()

                            if disabled_attribute is not None:
                                continue

                            if aria_disabled == "true":
                                continue

                            if "disabled" in class_name:
                                continue

                            return element, locator

                        except StaleElementReferenceException:
                            continue

                        except Exception:
                            continue

                except WebDriverException:
                    continue

            time.sleep(self.poll_interval)

        raise ElementNotFoundError(
            f"Không tìm thấy {element_name} clickable "
            f"trong {timeout} giây"
        )

    def find_all_visible(
        self,
        locators: tuple[Locator, ...],
        require_enabled: bool = False,
    ) -> list[WebElement]:
        self.ensure_driver_ready()

        result: list[WebElement] = []
        seen_ids: set[str] = set()

        for locator in locators:
            try:
                elements = self.driver.find_elements(
                    *locator
                )

                for element in elements:
                    try:
                        if not element.is_displayed():
                            continue

                        if (
                            require_enabled
                            and not element.is_enabled()
                        ):
                            continue

                        element_id = str(element.id)

                        if element_id in seen_ids:
                            continue

                        result.append(element)
                        seen_ids.add(element_id)

                    except StaleElementReferenceException:
                        continue

                    except Exception:
                        continue

            except WebDriverException:
                return result

    def is_visible(
        self,
        locator: Locator,
    ) -> bool:
        try:
            elements = self.driver.find_elements(
                *locator
            )

            for element in elements:
                try:
                    if element.is_displayed():
                        return True

                except Exception:
                    continue

            return False

        except Exception:
            return False

    def is_any_visible(
        self,
        locators: tuple[Locator, ...],
    ) -> bool:
        return any(
            self.is_visible(locator)
            for locator in locators
        )

    def is_clickable(
        self,
        locator: Locator,
    ) -> bool:
        try:
            elements = self.driver.find_elements(
                *locator
            )

            for element in elements:
                try:
                    if not element.is_displayed():
                        continue

                    if not element.is_enabled():
                        continue

                    disabled_attribute = (
                        element.get_attribute(
                            "disabled"
                        )
                    )

                    aria_disabled = str(
                        element.get_attribute(
                            "aria-disabled"
                        )
                        or ""
                    ).lower()

                    class_name = str(
                        element.get_attribute(
                            "class"
                        )
                        or ""
                    ).lower()

                    if disabled_attribute is not None:
                        continue

                    if aria_disabled == "true":
                        continue

                    if "disabled" in class_name:
                        continue

                    return True

                except Exception:
                    continue

            return False

        except Exception:
            return False

    def is_any_clickable(
        self,
        locators: tuple[Locator, ...],
    ) -> bool:
        return any(
            self.is_clickable(locator)
            for locator in locators
        )

    # ========================================================
    # WAIT CONDITIONS
    # ========================================================

    def wait_until(
        self,
        condition: Condition,
        condition_name: str = "condition",
        timeout: int | None = None,
        raise_on_timeout: bool = True,
    ) -> bool:
        timeout = timeout or self.transition_timeout
        deadline = time.time() + timeout

        while time.time() < deadline:
            try:
                if condition():
                    return True

            except (
                StaleElementReferenceException,
                WebDriverException,
            ):
                pass

            except Exception:
                pass

            time.sleep(self.poll_interval)

        if raise_on_timeout:
            raise StepTransitionError(
                f"Timeout chờ {condition_name} "
                f"sau {timeout} giây"
            )

        return False

    def wait_any_visible(
        self,
        locators: tuple[Locator, ...],
        element_name: str,
        timeout: int | None = None,
    ) -> tuple[WebElement, Locator]:
        return self.find_first_visible(
            locators=locators,
            element_name=element_name,
            timeout=timeout,
        )

    def wait_any_clickable(
        self,
        locators: tuple[Locator, ...],
        element_name: str,
        timeout: int | None = None,
    ) -> tuple[WebElement, Locator]:
        return self.find_first_clickable(
            locators=locators,
            element_name=element_name,
            timeout=timeout,
        )

    def wait_invisible(
        self,
        locator: Locator,
        element_name: str,
        timeout: int | None = None,
    ) -> bool:
        timeout = timeout or self.default_timeout

        try:
            WebDriverWait(
                self.driver,
                timeout,
                poll_frequency=self.poll_interval,
            ).until(
                EC.invisibility_of_element_located(
                    locator
                )
            )

            return True

        except TimeoutException as error:
            raise StepTransitionError(
                f"{element_name} vẫn visible "
                f"sau {timeout} giây"
            ) from error

    # ========================================================
    # INPUT
    # ========================================================

    def type_text(
        self,
        locator: Locator,
        value: str,
        element_name: str,
        timeout: int | None = None,
        clear_first: bool = True,
        press_tab: bool = False,
        press_enter: bool = False,
        verify_value: bool = True,
    ) -> WebElement:
        element = self.find_visible(
            locator=locator,
            element_name=element_name,
            timeout=timeout,
        )

        self._fill_element(
            element=element,
            value=value,
            clear_first=clear_first,
            press_tab=press_tab,
            press_enter=press_enter,
        )

        if verify_value:
            self._verify_element_value(
                element=element,
                expected_value=value,
                element_name=element_name,
            )

        print(
            f"[BROWSER] Filled {element_name}"
        )

        return element

    def type_text_first_visible(
        self,
        locators: tuple[Locator, ...],
        value: str,
        element_name: str,
        timeout: int | None = None,
        clear_first: bool = True,
        press_tab: bool = False,
        press_enter: bool = False,
        verify_value: bool = True,
    ) -> WebElement:
        element, _ = self.find_first_visible(
            locators=locators,
            element_name=element_name,
            timeout=timeout,
        )

        self._fill_element(
            element=element,
            value=value,
            clear_first=clear_first,
            press_tab=press_tab,
            press_enter=press_enter,
        )

        if verify_value:
            self._verify_element_value(
                element=element,
                expected_value=value,
                element_name=element_name,
            )

        print(
            f"[BROWSER] Filled {element_name}"
        )

        return element

    def _fill_element(
        self,
        element: WebElement,
        value: str,
        clear_first: bool,
        press_tab: bool,
        press_enter: bool,
    ) -> None:
        self._scroll_to_element(element)

        element.click()

        if clear_first:
            element.send_keys(
                Keys.CONTROL,
                "a",
            )

            element.send_keys(
                Keys.DELETE
            )

        element.send_keys(value)

        if press_tab:
            element.send_keys(
                Keys.TAB
            )

        if press_enter:
            element.send_keys(
                Keys.ENTER
            )

    def _verify_element_value(
        self,
        element: WebElement,
        expected_value: str,
        element_name: str,
        timeout: int = 5,
    ) -> None:
        deadline = time.time() + timeout

        while time.time() < deadline:
            try:
                current_value = str(
                    element.get_attribute(
                        "value"
                    )
                    or ""
                )

                if current_value == expected_value:
                    return

            except StaleElementReferenceException:
                pass

            time.sleep(0.2)

        raise ElementActionError(
            f"{element_name} không giữ đúng value "
            "sau khi nhập"
        )

    # ========================================================
    # CLICK
    # ========================================================

    def click(
        self,
        locator: Locator,
        element_name: str,
        timeout: int | None = None,
        success_condition: Condition | None = None,
        success_name: str | None = None,
        transition_timeout: int | None = None,
    ) -> WebElement:
        return self.click_first_visible(
            locators=(locator,),
            element_name=element_name,
            timeout=timeout,
            success_condition=success_condition,
            success_name=success_name,
            transition_timeout=transition_timeout,
        )

    def click_first_visible(
        self,
        locators: tuple[Locator, ...],
        element_name: str,
        timeout: int | None = None,
        success_condition: Condition | None = None,
        success_name: str | None = None,
        transition_timeout: int | None = None,
    ) -> WebElement:
        """
        Thử click lần lượt bằng:

        1. Selenium native click.
        2. ActionChains.
        3. JavaScript MouseEvent.

        Nếu success_condition được truyền vào, click chỉ được
        xác nhận thành công khi condition trả về True.
        """

        timeout = timeout or self.default_timeout

        strategies = (
            "native",
            "action_chains",
            "javascript",
        )

        last_error: Exception | None = None

        for strategy in strategies:
            try:
                element, locator = (
                    self.find_first_clickable(
                        locators=locators,
                        element_name=element_name,
                        timeout=timeout,
                    )
                )

                self._scroll_to_element(element)

                time.sleep(0.3)

                self.logger.info(
                    "Clicking | element=%s | "
                    "strategy=%s | locator=%s",
                    element_name,
                    strategy,
                    locator,
                )

                if strategy == "native":
                    element.click()

                elif strategy == "action_chains":
                    (
                        ActionChains(self.driver)
                        .move_to_element(element)
                        .pause(0.3)
                        .click()
                        .perform()
                    )

                elif strategy == "javascript":
                    self.driver.execute_script(
                        """
                        const element = arguments[0];

                        element.dispatchEvent(
                            new MouseEvent(
                                "mousedown",
                                {
                                    bubbles: true,
                                    cancelable: true,
                                    view: window
                                }
                            )
                        );

                        element.dispatchEvent(
                            new MouseEvent(
                                "mouseup",
                                {
                                    bubbles: true,
                                    cancelable: true,
                                    view: window
                                }
                            )
                        );

                        element.dispatchEvent(
                            new MouseEvent(
                                "click",
                                {
                                    bubbles: true,
                                    cancelable: true,
                                    view: window
                                }
                            )
                        );
                        """,
                        element,
                    )

                if success_condition is None:
                    print(
                        "[BROWSER] "
                        f"Clicked {element_name}"
                    )

                    return element

                transition_ok = self.wait_until(
                    condition=success_condition,
                    condition_name=(
                        success_name
                        or (
                            "next step after "
                            f"{element_name}"
                        )
                    ),
                    timeout=transition_timeout,
                    raise_on_timeout=False,
                )

                if transition_ok:
                    print(
                        "[BROWSER] "
                        f"Click confirmed: "
                        f"{element_name}"
                    )

                    return element

                last_error = StepTransitionError(
                    f"{element_name} click bằng "
                    f"{strategy} nhưng màn hình "
                    "kế tiếp chưa xuất hiện"
                )

                self.logger.warning(
                    "Click did not transition | "
                    "element=%s | strategy=%s",
                    element_name,
                    strategy,
                )

            except (
                ElementClickInterceptedException,
                ElementNotInteractableException,
                StaleElementReferenceException,
                ElementNotFoundError,
                StepTransitionError,
                WebDriverException,
            ) as error:
                last_error = error

                self.logger.warning(
                    "Click failed | element=%s | "
                    "strategy=%s | error=%s",
                    element_name,
                    strategy,
                    error,
                )

        raise ElementActionError(
            f"Không click được {element_name}. "
            f"Last error={last_error}"
        )

    # ========================================================
    # SCROLL
    # ========================================================

    def _scroll_to_element(
        self,
        element: WebElement,
    ) -> None:
        self.driver.execute_script(
            """
            arguments[0].scrollIntoView({
                block: "center",
                inline: "center",
                behavior: "instant"
            });
            """,
            element,
        )