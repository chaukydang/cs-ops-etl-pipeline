from __future__ import annotations

import logging
import re
import time

from selenium.common.exceptions import (
    StaleElementReferenceException,
    TimeoutException,
)
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.remote.webdriver import WebDriver
from selenium.webdriver.remote.webelement import WebElement

from modules.dashboard.auth.outlook_login_flow import (
    OutlookLoginFlow,
    OutlookLoginFlowError,
)
from modules.dashboard.browser.actions import BrowserActions

# ============================================================
# EXCEPTIONS
# ============================================================


class OutlookOtpError(Exception):
    """Lỗi chung khi lấy OTP từ Outlook."""


class OutlookLoginRequiredError(OutlookOtpError):
    """Không đăng nhập được Outlook."""


class OutlookOtpTimeoutError(OutlookOtpError):
    """Không tìm thấy OTP trong thời gian cho phép."""


# ============================================================
# OUTLOOK OTP READER
# ============================================================


class OutlookOtpReader:
    """
    Đọc OTP Lark từ Outlook.

    Flow chính:

    1. prepare_inbox_before_otp()
        - Mở Outlook
        - Login Outlook nếu cần
        - Tìm OTP Lark unread cũ
        - Mark các email đó thành read
        - Quay lại tab Lark

    2. LarkLoginFlow click Switch to Email Verification

    3. wait_for_new_unread_lark_otp()
        - Mở lại Outlook
        - Chỉ tìm OTP Lark đang unread
        - Đọc OTP
        - Mark OTP đó thành read
        - Quay lại tab Lark
    """

    # ========================================================
    # OUTLOOK URLS
    # ========================================================

    MAILBOX_URL_KEYWORDS = (
        "outlook.office.com",
        "outlook.office365.com",
        "outlook.cloud.microsoft",
        "outlook.live.com",
    )

    LOGIN_URL_KEYWORDS = (
        "login.microsoftonline.com",
        "login.microsoft.com",
        "login.live.com",
        "account.live.com",
        "/oauth2/",
        "adfs",
        "mysignins.microsoft.com",
    )

    # ========================================================
    # LOGIN ELEMENTS
    # ========================================================

    LOGIN_INPUT_XPATHS = (
        "//input[@name='loginfmt']",
        "//input[@name='passwd']",
        "//input[@type='email']",
        "//input[@type='password']",
    )

    # ========================================================
    # MAIL LIST ELEMENTS
    # ========================================================

    MAIL_ITEM_XPATHS = (
        "//div[@role='option']",
        "//*[@role='listbox']//*[@role='option']",
    )

    FOCUSED_TAB_XPATHS = (
        "//*[@role='tab'][normalize-space()='Focused']",
        "//button[@name='Focused']",
        "//*[@role='tab'][contains(@aria-label, 'Focused')]",
    )

    OTHER_TAB_XPATHS = (
        "//*[@role='tab'][normalize-space()='Other']",
        "//button[@name='Other']",
        "//*[@role='tab'][contains(@aria-label, 'Other')]",
    )

    # ========================================================
    # MESSAGE BODY
    # ========================================================

    MESSAGE_BODY_XPATHS = (
        "//div[@aria-label='Message body']",
        "//div[@role='document']",
        "//*[contains(@class, 'allowTextSelection')]",
        "//*[@data-app-section='MailReadCompose']"
        "//*[@role='document']",
    )

    # ========================================================
    # READ / UNREAD ACTIONS
    # ========================================================

    MARK_READ_XPATHS = (
        "//button[@aria-label='Mark as read']",
        "//button[@title='Mark as read']",
        "//*[@role='button' and @aria-label='Mark as read']",
        "//*[@role='button' and @title='Mark as read']",
    )

    MARK_UNREAD_XPATHS = (
        "//button[@aria-label='Mark as unread']",
        "//button[@title='Mark as unread']",
        "//*[@role='button' and @aria-label='Mark as unread']",
        "//*[@role='button' and @title='Mark as unread']",
    )

    # ========================================================
    # LARK EMAIL IDENTIFICATION
    # ========================================================

    LARK_MAIL_KEYWORDS = (
        "lark verification code",
        "is your lark verification code",
        "lark email verification",
        "verification code",
    )

    LARK_SENDER_KEYWORDS = (
        "lark",
        "lark_passport",
        "larksuite",
        "service.larksuite.com",
    )

    # ========================================================
    # OTP REGEX
    # ========================================================

    OTP_REGEXES = (
        re.compile(
            r"\b(\d{6})\s+is your "
            r"Lark verification code\b",
            re.IGNORECASE,
        ),
        re.compile(
            r"Here is your Lark verification "
            r"code.{0,500}?\b(\d{6})\b",
            re.IGNORECASE | re.DOTALL,
        ),
        re.compile(
            r"Lark verification code"
            r".{0,500}?\b(\d{6})\b",
            re.IGNORECASE | re.DOTALL,
        ),
        re.compile(
            r"\bverification code\b"
            r".{0,300}?\b(\d{6})\b",
            re.IGNORECASE | re.DOTALL,
        ),
    )

    # ========================================================
    # INITIALIZATION
    # ========================================================

    def __init__(
        self,
        driver: WebDriver,
        actions: BrowserActions,
        mail_url: str,
        otp_timeout: int = 180,
        poll_interval: int = 5,
        outlook_email: str = "",
        outlook_password: str = "",
        outlook_totp_secret: str = "",
        outlook_login_timeout: int = 300,
        manual_mfa_timeout: int = 300,
    ) -> None:
        self.driver = driver
        self.actions = actions

        self.mail_url = (
            mail_url.strip()
            or "https://outlook.office.com/mail/"
        )

        self.otp_timeout = otp_timeout
        self.poll_interval = poll_interval

        self.outlook_email = outlook_email.strip()
        self.outlook_password = outlook_password

        self.outlook_totp_secret = (
            outlook_totp_secret.strip()
        )

        self.outlook_login_timeout = (
            outlook_login_timeout
        )

        self.manual_mfa_timeout = (
            manual_mfa_timeout
        )

        self.source_tab: str | None = None
        self.outlook_tab: str | None = None

        self.last_used_otp: str | None = None

        self.logger = logging.getLogger(
            self.__class__.__name__
        )

    # ========================================================
    # PREPARE INBOX BEFORE LARK SENDS NEW OTP
    # ========================================================

    def prepare_inbox_before_otp(self) -> None:
        """
        Trước khi Lark gửi OTP mới:

        1. Mở Outlook.
        2. Login Outlook nếu cần.
        3. Kiểm tra Focused và Other.
        4. Tìm email OTP Lark đang unread.
        5. Đánh dấu các OTP cũ thành read.
        6. Quay lại tab Lark.
        """

        print(
            "[OUTLOOK OTP] "
            "Preparing inbox before requesting new OTP"
        )

        self.open_outlook_tab()

        try:
            self.ensure_outlook_logged_in()

            self.ensure_outlook_available(
                timeout=60
            )

            total_marked = 0

            for tab_name in (
                "Focused",
                "Other",
            ):
                self.click_mail_tab(
                    tab_name
                )

                time.sleep(2)

                marked_count = (
                    self.mark_existing_unread_lark_otps_read()
                )

                total_marked += marked_count

            print(
                "[OUTLOOK OTP] "
                "Old unread Lark OTP emails "
                f"marked read={total_marked}"
            )

        finally:
            self.switch_to_source()

    def mark_existing_unread_lark_otps_read(
        self,
        max_items: int = 20,
    ) -> int:
        """
        Mark toàn bộ email OTP Lark unread hiện tại thành read.

        Sau mỗi lần mark, Outlook có thể render lại DOM.
        Vì vậy cần tìm lại mail item ở mỗi vòng lặp.
        """

        marked_count = 0
        processed_signatures: set[str] = set()

        for _ in range(max_items):
            item = self.find_first_unread_lark_mail(
                excluded_signatures=processed_signatures
            )

            if item is None:
                break

            signature = (
                self.get_mail_item_signature(
                    item
                )
            )

            if signature:
                processed_signatures.add(
                    signature
                )

            try:
                self.scroll_to_element(item)

                item.click()

                time.sleep(2)

                marked_read = (
                    self.mark_current_mail_read()
                )

                if marked_read:
                    marked_count += 1

                else:
                    self.logger.warning(
                        "Không xác nhận được email OTP cũ "
                        "đã chuyển sang read"
                    )

                time.sleep(2)

            except Exception as error:
                self.logger.warning(
                    "Không xử lý được email OTP cũ | "
                    "Error=%s",
                    error,
                )

        return marked_count

    # ========================================================
    # WAIT FOR NEW UNREAD LARK OTP
    # ========================================================

    def wait_for_new_unread_lark_otp(
        self,
    ) -> str:
        """
        Chỉ lấy OTP từ email Lark đang unread.

        Sau khi đọc:
        - Mark email thành read.
        - Lưu OTP vào last_used_otp.
        - Quay lại tab Lark.
        """

        print(
            "[OUTLOOK OTP] "
            "Waiting for new unread Lark OTP"
        )

        self.open_outlook_tab()

        try:
            self.ensure_outlook_logged_in()

            self.ensure_outlook_available(
                timeout=60
            )

            deadline = (
                time.time()
                + self.otp_timeout
            )

            while time.time() < deadline:
                for tab_name in (
                    "Focused",
                    "Other",
                ):
                    self.click_mail_tab(
                        tab_name
                    )

                    time.sleep(2)

                    item = (
                        self.find_first_unread_lark_mail()
                    )

                    if item is None:
                        continue

                    item_text = (
                        self.get_element_text(
                            item
                        )
                    )

                    otp = self.extract_otp(
                        item_text
                    )

                    try:
                        self.scroll_to_element(
                            item
                        )

                        item.click()

                        time.sleep(2)

                    except Exception as error:
                        self.logger.warning(
                            "Không mở được email OTP mới | "
                            "Error=%s",
                            error,
                        )

                        continue

                    if not otp:
                        otp = self.read_open_mail_otp(
                            timeout=15
                        )

                    if not otp:
                        self.logger.warning(
                            "Tìm thấy email OTP unread "
                            "nhưng không extract được OTP"
                        )

                        continue

                    if otp == self.last_used_otp:
                        print(
                            "[OUTLOOK OTP] "
                            "OTP đã được sử dụng trước đó. "
                            "Mark read và tiếp tục chờ."
                        )

                        self.mark_current_mail_read()

                        continue

                    marked_read = (
                        self.mark_current_mail_read()
                    )

                    if not marked_read:
                        self.logger.warning(
                            "Đã đọc OTP nhưng chưa xác nhận "
                            "được email chuyển sang read"
                        )

                    self.last_used_otp = otp

                    print(
                        "[OUTLOOK OTP] "
                        "New unread Lark OTP found "
                        "and marked as read"
                    )

                    return otp

                self.refresh_mailbox()

                time.sleep(
                    self.poll_interval
                )

            raise OutlookOtpTimeoutError(
                "Không tìm thấy email OTP Lark "
                "đang unread trong "
                f"{self.otp_timeout} giây"
            )

        finally:
            self.switch_to_source()

    def wait_for_lark_otp(self) -> str:
        """
        Wrapper tương thích với code cũ.
        """

        return (
            self.wait_for_new_unread_lark_otp()
        )

    # ========================================================
    # OUTLOOK LOGIN
    # ========================================================

    def ensure_outlook_logged_in(
        self,
    ) -> None:
        if self.is_mailbox_page():
            print(
                "[OUTLOOK OTP] "
                "Outlook session is already active"
            )

            return

        login_flow = OutlookLoginFlow(
            actions=self.actions,
            email=self.outlook_email,
            password=self.outlook_password,
            totp_secret=(
                self.outlook_totp_secret
            ),
            login_timeout=(
                self.outlook_login_timeout
            ),
            manual_mfa_timeout=(
                self.manual_mfa_timeout
            ),
            stay_signed_in=True,
        )

        try:
            login_flow.run()

        except OutlookLoginFlowError as error:
            raise OutlookLoginRequiredError(
                f"Outlook login thất bại: {error}"
            ) from error

    # ========================================================
    # TAB MANAGEMENT
    # ========================================================

    def open_outlook_tab(self) -> None:
        """
        Lưu tab nguồn và mở/tái sử dụng tab Outlook.
        """

        self.source_tab = (
            self.driver.current_window_handle
        )

        if (
            self.outlook_tab
            and self.outlook_tab
            in self.driver.window_handles
        ):
            self.driver.switch_to.window(
                self.outlook_tab
            )

        else:
            self.driver.switch_to.new_window(
                "tab"
            )

            self.outlook_tab = (
                self.driver.current_window_handle
            )

        try:
            current_url = str(
                self.driver.current_url or ""
            ).lower()

        except Exception:
            current_url = ""

        already_in_outlook = any(
            keyword in current_url
            for keyword in (
                self.MAILBOX_URL_KEYWORDS
                + self.LOGIN_URL_KEYWORDS
            )
        )

        if not already_in_outlook:
            try:
                self.driver.get(
                    self.mail_url
                )

            except TimeoutException:
                self.logger.warning(
                    "Outlook page load timed out"
                )

        self.actions.wait_document_ready(
            timeout=60
        )

        time.sleep(3)

    def switch_to_source(self) -> bool:
        """
        Quay lại tab Lark/Aeolus.
        """

        if (
            self.source_tab
            and self.source_tab
            in self.driver.window_handles
        ):
            self.driver.switch_to.window(
                self.source_tab
            )

            return True

        self.logger.warning(
            "Source tab no longer exists"
        )

        return False

    def switch_to_outlook(self) -> bool:
        """
        Chuyển sang tab Outlook hiện tại.
        """

        if (
            self.outlook_tab
            and self.outlook_tab
            in self.driver.window_handles
        ):
            self.driver.switch_to.window(
                self.outlook_tab
            )

            return True

        return False

    # ========================================================
    # OUTLOOK PAGE STATE
    # ========================================================

    def is_login_page(self) -> bool:
        try:
            current_url = str(
                self.driver.current_url or ""
            ).lower()

        except Exception:
            current_url = ""

        if any(
            keyword in current_url
            for keyword in self.LOGIN_URL_KEYWORDS
        ):
            return True

        return (
            self.find_visible(
                self.LOGIN_INPUT_XPATHS
            )
            is not None
        )

    def is_mailbox_page(self) -> bool:
        try:
            current_url = str(
                self.driver.current_url or ""
            ).lower()

        except Exception:
            return False

        if self.is_login_page():
            return False

        return any(
            keyword in current_url
            for keyword in self.MAILBOX_URL_KEYWORDS
        )

    def ensure_outlook_available(
        self,
        timeout: int = 60,
    ) -> None:
        deadline = time.time() + timeout

        while time.time() < deadline:
            if self.is_mailbox_page():
                print(
                    "[OUTLOOK OTP] Mailbox ready"
                )

                return

            if self.is_login_page():
                raise OutlookLoginRequiredError(
                    "Outlook vẫn đang ở login page"
                )

            time.sleep(1)

        raise OutlookLoginRequiredError(
            "Không xác nhận được Outlook mailbox "
            f"trong {timeout} giây"
        )

    # ========================================================
    # MAILBOX ACTIONS
    # ========================================================

    def refresh_mailbox(self) -> None:
        try:
            self.driver.refresh()

        except TimeoutException:
            self.logger.warning(
                "Outlook refresh timed out"
            )

        self.actions.wait_document_ready(
            timeout=30
        )

        time.sleep(2)

    def click_mail_tab(
        self,
        tab_name: str,
    ) -> bool:
        if tab_name.lower() == "focused":
            xpaths = self.FOCUSED_TAB_XPATHS
        else:
            xpaths = self.OTHER_TAB_XPATHS

        tab = self.find_visible(xpaths)

        if tab is None:
            return False

        try:
            tab.click()

            time.sleep(1)

            return True

        except Exception as error:
            self.logger.debug(
                "Cannot click Outlook tab %s: %s",
                tab_name,
                error,
            )

            return False

    # ========================================================
    # UNREAD LARK OTP EMAIL
    # ========================================================

    def find_first_unread_lark_mail(
        self,
        excluded_signatures: set[str] | None = None,
    ) -> WebElement | None:
        """
        Chỉ trả về mail item:

        - Là email OTP Lark.
        - Đang unread.
        - Chưa nằm trong excluded_signatures.
        """

        if excluded_signatures is None:
            excluded_signatures = set()

        items = self.find_all_visible(
            self.MAIL_ITEM_XPATHS
        )

        for item in items:
            signature = (
                self.get_mail_item_signature(
                    item
                )
            )

            if (
                signature
                and signature
                in excluded_signatures
            ):
                continue

            text = self.get_element_text(
                item
            ).lower()

            if not self.is_lark_otp_text(
                text
            ):
                continue

            if self.is_mail_item_unread(
                item
            ):
                return item

        return None

    def find_latest_lark_mail(
        self,
    ) -> WebElement | None:
        """
        Fallback tìm email Lark OTP mà không yêu cầu unread.
        """

        items = self.find_all_visible(
            self.MAIL_ITEM_XPATHS
        )

        for item in items:
            text = self.get_element_text(
                item
            ).lower()

            if self.is_lark_otp_text(text):
                return item

        return None

    def is_lark_otp_text(
        self,
        text: str,
    ) -> bool:
        normalized_text = str(
            text or ""
        ).lower()

        has_otp_keyword = any(
            keyword in normalized_text
            for keyword in self.LARK_MAIL_KEYWORDS
        )

        has_lark_sender = any(
            keyword in normalized_text
            for keyword in self.LARK_SENDER_KEYWORDS
        )

        return (
            has_otp_keyword
            and (
                has_lark_sender
                or "lark" in normalized_text
            )
        )

    @staticmethod
    def is_mail_item_unread(
        item: WebElement,
    ) -> bool:
        """
        Detect unread từ nhiều tín hiệu DOM của Outlook.
        """

        try:
            data_is_unread = str(
                item.get_attribute(
                    "data-is-unread"
                )
                or ""
            ).lower()

            if data_is_unread == "true":
                return True

        except Exception:
            pass

        try:
            aria_label = str(
                item.get_attribute(
                    "aria-label"
                )
                or ""
            ).lower()

            if "unread" in aria_label:
                return True

        except Exception:
            pass

        try:
            class_name = str(
                item.get_attribute(
                    "class"
                )
                or ""
            ).lower()

            unread_classes = (
                "unread",
                "is-unread",
                "isunread",
                "unreadmail",
            )

            if any(
                value in class_name
                for value in unread_classes
            ):
                return True

        except Exception:
            pass

        try:
            font_weight = str(
                item.value_of_css_property(
                    "font-weight"
                )
                or ""
            ).lower()

            if font_weight in (
                "600",
                "700",
                "bold",
            ):
                return True

        except Exception:
            pass

        try:
            mark_read_buttons = (
                item.find_elements(
                    By.XPATH,
                    ".//*[@aria-label='Mark as read']"
                    " | "
                    ".//*[@title='Mark as read']",
                )
            )

            if mark_read_buttons:
                return True

        except Exception:
            pass

        return False

    # ========================================================
    # READ OPEN MAIL OTP
    # ========================================================

    def read_open_mail_otp(
        self,
        timeout: int = 15,
    ) -> str | None:
        deadline = time.time() + timeout

        while time.time() < deadline:
            text_candidates: list[str] = []

            for xpath in (
                self.MESSAGE_BODY_XPATHS
            ):
                try:
                    elements = (
                        self.driver.find_elements(
                            By.XPATH,
                            xpath,
                        )
                    )

                    for element in elements:
                        try:
                            if element.is_displayed():
                                text_candidates.append(
                                    element.text or ""
                                )

                        except Exception:
                            continue

                except Exception:
                    continue

            try:
                body_text = (
                    self.driver.find_element(
                        By.TAG_NAME,
                        "body",
                    ).text
                )

                text_candidates.append(
                    body_text or ""
                )

            except Exception:
                pass

            for text in text_candidates:
                otp = self.extract_otp(
                    text
                )

                if otp:
                    return otp

            time.sleep(1)

        return None

    # ========================================================
    # MARK MAIL AS READ
    # ========================================================

    def mark_current_mail_read(
        self,
    ) -> bool:
        """
        Mark email đang mở thành read.

        Returns:
            True nếu xác nhận được trạng thái read.
        """

        button = self.find_visible(
            self.MARK_READ_XPATHS
        )

        if button is not None:
            try:
                button.click()

                time.sleep(2)

                if self.current_mail_is_read():
                    print(
                        "[OUTLOOK OTP] "
                        "Email marked as read"
                    )

                    return True

            except Exception as error:
                self.logger.warning(
                    "Mark as read button failed: %s",
                    error,
                )

        try:
            body = self.driver.find_element(
                By.TAG_NAME,
                "body",
            )

            body.send_keys(
                Keys.CONTROL,
                "q",
            )

            time.sleep(2)

            if self.current_mail_is_read():
                print(
                    "[OUTLOOK OTP] "
                    "Email marked as read by Ctrl+Q"
                )

                return True

        except Exception as error:
            self.logger.warning(
                "Ctrl+Q mark read failed: %s",
                error,
            )

        return False

    def current_mail_is_read(
        self,
    ) -> bool:
        """
        Email được xem là read nếu:

        - Nút Mark as unread xuất hiện; hoặc
        - Nút Mark as read không còn visible.
        """

        if self.find_visible(
            self.MARK_UNREAD_XPATHS
        ) is not None:
            return True

        if self.find_visible(
            self.MARK_READ_XPATHS
        ) is None:
            return True

        return False

    # ========================================================
    # OTP EXTRACTION
    # ========================================================

    def extract_otp(
        self,
        text: str,
    ) -> str | None:
        for regex in self.OTP_REGEXES:
            match = regex.search(text)

            if match:
                return match.group(1)

        return None

    # ========================================================
    # MAIL ITEM HELPERS
    # ========================================================

    @staticmethod
    def get_mail_item_signature(
        item: WebElement,
    ) -> str:
        """
        Tạo signature tạm để tránh xử lý cùng mail item
        nhiều lần trong một vòng prepare.
        """

        parts: list[str] = []

        try:
            element_id = str(
                item.id or ""
            )

            if element_id:
                parts.append(element_id)

        except Exception:
            pass

        for attribute in (
            "aria-label",
            "title",
            "data-convid",
            "data-item-id",
        ):
            try:
                value = str(
                    item.get_attribute(
                        attribute
                    )
                    or ""
                )

                if value:
                    parts.append(value)

            except Exception:
                continue

        try:
            text = str(
                item.text or ""
            )

            if text:
                parts.append(text)

        except Exception:
            pass

        return "|".join(parts)

    @staticmethod
    def get_element_text(
        element: WebElement,
    ) -> str:
        parts: list[str] = []

        try:
            visible_text = str(
                element.text or ""
            )

            if visible_text:
                parts.append(visible_text)

        except Exception:
            pass

        for attribute in (
            "aria-label",
            "title",
            "data-is-unread",
        ):
            try:
                value = element.get_attribute(
                    attribute
                )

                if value:
                    parts.append(
                        str(value)
                    )

            except Exception:
                continue

        return "\n".join(parts).strip()

    # ========================================================
    # GENERIC ELEMENT HELPERS
    # ========================================================

    def find_visible(
        self,
        xpaths: tuple[str, ...],
    ) -> WebElement | None:
        for xpath in xpaths:
            try:
                elements = (
                    self.driver.find_elements(
                        By.XPATH,
                        xpath,
                    )
                )

                for element in elements:
                    try:
                        if element.is_displayed():
                            return element

                    except StaleElementReferenceException:
                        continue

                    except Exception:
                        continue

            except Exception:
                continue

        return None

    def find_all_visible(
        self,
        xpaths: tuple[str, ...],
    ) -> list[WebElement]:
        """
        Tìm tất cả element visible từ danh sách XPath.

        Element trùng được loại bỏ bằng Selenium element ID.
        """

        result: list[WebElement] = []
        seen_ids: set[str] = set()

        for xpath in xpaths:
            try:
                elements = self.driver.find_elements(
                    By.XPATH,
                    xpath,
                )

                for element in elements:
                    try:
                        if not element.is_displayed():
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

            except Exception:
                continue

        return result

    def scroll_to_element(
        self,
        element: WebElement,
    ) -> None:
        try:
            self.driver.execute_script(
                """
                arguments[0].scrollIntoView({
                    block: "center",
                    inline: "center"
                });
                """,
                element,
            )

        except Exception:
            pass