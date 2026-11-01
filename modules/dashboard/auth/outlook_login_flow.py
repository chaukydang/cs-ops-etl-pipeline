from __future__ import annotations

import logging
import time

from selenium.webdriver.common.by import By

from modules.dashboard.browser.actions import BrowserActions, Locator

try:
    import pyotp
except ImportError:
    pyotp = None


class OutlookLoginFlowError(Exception):
    """Lỗi chung trong flow đăng nhập Outlook."""


class OutlookCredentialsMissingError(
    OutlookLoginFlowError
):
    """Thiếu Outlook email hoặc password."""


class OutlookMfaRequiredError(
    OutlookLoginFlowError
):
    """Không hoàn tất Microsoft MFA."""


class OutlookLoginTimeoutError(
    OutlookLoginFlowError
):
    """Hết thời gian chờ login Outlook."""


class OutlookLoginRejectedError(
    OutlookLoginFlowError
):
    """Microsoft từ chối email, password hoặc OTP."""


class OutlookLoginFlow:
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
        "aka.ms/mfasetup",
    )

    EMAIL_INPUT_LOCATORS: tuple[Locator, ...] = (
        (
            By.XPATH,
            "//input[@name='loginfmt']",
        ),
        (
            By.XPATH,
            "//input[@type='email']",
        ),
        (
            By.XPATH,
            "//input[@autocomplete='username']",
        ),
    )

    PASSWORD_INPUT_LOCATORS: tuple[Locator, ...] = (
        (
            By.XPATH,
            "//input[@name='passwd']",
        ),
        (
            By.XPATH,
            "//input[@type='password']",
        ),
        (
            By.XPATH,
            "//input[@autocomplete='current-password']",
        ),
    )

    PRIMARY_BUTTON_LOCATORS: tuple[Locator, ...] = (
        (
            By.XPATH,
            "//input[@id='idSIButton9']",
        ),
        (
            By.XPATH,
            "//button[@id='idSIButton9']",
        ),
        (
            By.XPATH,
            "//button[@data-testid='primaryButton']",
        ),
        (
            By.XPATH,
            "//input[@type='submit']",
        ),
        (
            By.XPATH,
            "//button[@type='submit']",
        ),
        (
            By.XPATH,
            "//button[normalize-space()='Next']",
        ),
        (
            By.XPATH,
            "//button[normalize-space()='Sign in']",
        ),
    )

    OTP_INPUT_LOCATORS: tuple[Locator, ...] = (
        (
            By.XPATH,
            "//input[@name='otc']",
        ),
        (
            By.XPATH,
            "//input[@id='idTxtBx_SAOTCC_OTC']",
        ),
        (
            By.XPATH,
            "//input[@autocomplete='one-time-code']",
        ),
        (
            By.XPATH,
            "//input[@inputmode='numeric']",
        ),
    )

    OTP_SUBMIT_LOCATORS: tuple[Locator, ...] = (
        (
            By.XPATH,
            "//input[@id='idSubmit_SAOTCC_Continue']",
        ),
        (
            By.XPATH,
            "//button[@id='idSubmit_SAOTCC_Continue']",
        ),
        *PRIMARY_BUTTON_LOCATORS,
    )

    OTP_METHOD_LOCATORS: tuple[Locator, ...] = (
        (
            By.XPATH,
            "//div[@data-value='PhoneAppOTP']",
        ),
        (
            By.XPATH,
            "//*[contains("
            "normalize-space(), "
            "'Use a verification code'"
            ")]",
        ),
        (
            By.XPATH,
            "//*[contains("
            "normalize-space(), "
            "'Enter a code'"
            ")]",
        ),
    )

    PUSH_NUMBER_LOCATORS: tuple[Locator, ...] = (
        (
            By.XPATH,
            "//*[@id='idRichContext_DisplaySign']",
        ),
        (
            By.XPATH,
            "//*[contains("
            "normalize-space(), "
            "'Approve sign in request'"
            ")]",
        ),
        (
            By.XPATH,
            "//*[contains("
            "normalize-space(), "
            "'Open your Authenticator app'"
            ")]",
        ),
    )

    KMSI_PAGE_LOCATORS: tuple[Locator, ...] = (
        (
            By.XPATH,
            "//*[@id='KmsiDescription']",
        ),
        (
            By.XPATH,
            "//*[normalize-space()='Stay signed in?']",
        ),
    )

    KMSI_CHECKBOX_LOCATORS: tuple[Locator, ...] = (
        (
            By.XPATH,
            "//input[@id='KmsiCheckboxField']",
        ),
    )

    KMSI_YES_LOCATORS: tuple[Locator, ...] = (
        (
            By.XPATH,
            "//input[@id='idSIButton9']",
        ),
        (
            By.XPATH,
            "//button[@id='idSIButton9']",
        ),
        (
            By.XPATH,
            "//button[normalize-space()='Yes']",
        ),
    )

    KMSI_NO_LOCATORS: tuple[Locator, ...] = (
        (
            By.XPATH,
            "//input[@id='idBtn_Back']",
        ),
        (
            By.XPATH,
            "//button[@id='idBtn_Back']",
        ),
        (
            By.XPATH,
            "//button[normalize-space()='No']",
        ),
    )

    USE_ANOTHER_ACCOUNT_LOCATORS: tuple[
        Locator,
        ...
    ] = (
        (
            By.XPATH,
            "//*[contains("
            "normalize-space(), "
            "'Use another account'"
            ")]",
        ),
        (
            By.XPATH,
            "//*[contains("
            "normalize-space(), "
            "'Sign in with another account'"
            ")]",
        ),
    )

    SKIP_SETUP_LOCATORS: tuple[Locator, ...] = (
        (
            By.XPATH,
            "//*[@id='btnAskLater']",
        ),
        (
            By.XPATH,
            "//a[contains("
            "normalize-space(), "
            "'Skip setup'"
            ")]",
        ),
        (
            By.XPATH,
            "//button[contains("
            "normalize-space(), "
            "'Skip setup'"
            ")]",
        ),
        (
            By.XPATH,
            "//a[contains("
            "normalize-space(), "
            "'Ask later'"
            ")]",
        ),
        (
            By.XPATH,
            "//button[contains("
            "normalize-space(), "
            "'Ask later'"
            ")]",
        ),
    )

    MORE_INFORMATION_NEXT_LOCATORS: tuple[
        Locator,
        ...
    ] = (
        (
            By.XPATH,
            "//input[@id='idSubmit_ProofUp_Redirect']",
        ),
        (
            By.XPATH,
            "//button[@id='idSubmit_ProofUp_Redirect']",
        ),
    )

    LOGIN_ERROR_LOCATORS: tuple[Locator, ...] = (
        (
            By.XPATH,
            "//*[@id='usernameError']",
        ),
        (
            By.XPATH,
            "//*[@id='passwordError']",
        ),
        (
            By.XPATH,
            "//*[@id='idSpan_SAOTCC_Error_OTC']",
        ),
        (
            By.XPATH,
            "//*[@role='alert']"
            "[string-length(normalize-space()) > 0]",
        ),
    )

    def __init__(
        self,
        actions: BrowserActions,
        email: str,
        password: str,
        totp_secret: str | None = None,
        login_timeout: int = 300,
        manual_mfa_timeout: int = 300,
        stay_signed_in: bool = True,
    ) -> None:
        self.actions = actions
        self.driver = actions.driver

        self.email = email.strip()
        self.password = password

        self.totp_secret = (
            totp_secret.strip()
            if totp_secret
            else ""
        )

        self.login_timeout = login_timeout
        self.manual_mfa_timeout = manual_mfa_timeout
        self.stay_signed_in = stay_signed_in

        self.logger = logging.getLogger(
            self.__class__.__name__
        )

    def run(self) -> bool:
        self.validate_credentials()

        if self.is_mailbox_page():
            print(
                "[OUTLOOK LOGIN] "
                "Session is already active"
            )

            return True

        print(
            "[OUTLOOK LOGIN] Starting login flow"
        )

        deadline = time.time() + self.login_timeout

        while time.time() < deadline:
            if self.is_mailbox_page():
                print(
                    "[OUTLOOK LOGIN] Login successful"
                )

                return True

            self.raise_if_login_error()

            if self.handle_security_setup():
                continue

            if self.handle_account_tile():
                continue

            if self.handle_use_another_account():
                continue

            if self.handle_otp_input():
                continue

            if self.handle_otp_method():
                continue

            if self.handle_manual_mfa():
                continue

            if self.handle_password():
                continue

            if self.handle_email():
                continue

            if self.handle_stay_signed_in():
                continue

            time.sleep(1)

        raise OutlookLoginTimeoutError(
            "Hết thời gian Outlook login "
            f"sau {self.login_timeout} giây. "
            f"URL={self.safe_current_url()}"
        )

    def handle_email(self) -> bool:
        if not self.actions.is_any_visible(
            self.EMAIL_INPUT_LOCATORS
        ):
            return False

        self.actions.type_text_first_visible(
            locators=self.EMAIL_INPUT_LOCATORS,
            value=self.email,
            element_name="Outlook email",
            timeout=20,
            press_tab=False,
            verify_value=True,
        )

        self.actions.click_first_visible(
            locators=self.PRIMARY_BUTTON_LOCATORS,
            element_name="Email Next",
            timeout=20,
            success_condition=(
                self.email_step_completed
            ),
            success_name=(
                "password or Microsoft verification"
            ),
            transition_timeout=60,
        )

        return True

    def email_step_completed(self) -> bool:
        return (
            self.actions.is_any_visible(
                self.PASSWORD_INPUT_LOCATORS
            )
            or self.actions.is_any_visible(
                self.OTP_INPUT_LOCATORS
            )
            or self.actions.is_any_visible(
                self.PUSH_NUMBER_LOCATORS
            )
            or self.actions.is_any_visible(
                self.KMSI_PAGE_LOCATORS
            )
            or self.is_mailbox_page()
        )

    def handle_password(self) -> bool:
        if not self.actions.is_any_visible(
            self.PASSWORD_INPUT_LOCATORS
        ):
            return False

        self.actions.type_text_first_visible(
            locators=self.PASSWORD_INPUT_LOCATORS,
            value=self.password,
            element_name="Outlook password",
            timeout=20,
            press_tab=True,
            verify_value=True,
        )

        self.actions.click_first_visible(
            locators=self.PRIMARY_BUTTON_LOCATORS,
            element_name="Password Sign in",
            timeout=20,
            success_condition=(
                self.password_step_completed
            ),
            success_name=(
                "MFA, Stay signed in, or mailbox"
            ),
            transition_timeout=90,
        )

        return True

    def password_step_completed(self) -> bool:
        return (
            self.actions.is_any_visible(
                self.OTP_INPUT_LOCATORS
            )
            or self.actions.is_any_visible(
                self.OTP_METHOD_LOCATORS
            )
            or self.actions.is_any_visible(
                self.PUSH_NUMBER_LOCATORS
            )
            or self.actions.is_any_visible(
                self.KMSI_PAGE_LOCATORS
            )
            or self.actions.is_any_visible(
                self.SKIP_SETUP_LOCATORS
            )
            or self.actions.is_any_visible(
                self.MORE_INFORMATION_NEXT_LOCATORS
            )
            or self.is_mailbox_page()
        )

    def handle_use_another_account(self) -> bool:
        if not self.actions.is_any_visible(
            self.USE_ANOTHER_ACCOUNT_LOCATORS
        ):
            return False

        self.actions.click_first_visible(
            locators=self.USE_ANOTHER_ACCOUNT_LOCATORS,
            element_name="Use another account",
            timeout=10,
            success_condition=lambda: (
                self.actions.is_any_visible(
                    self.EMAIL_INPUT_LOCATORS
                )
            ),
            success_name="email input",
            transition_timeout=30,
        )

        return True

    def handle_account_tile(self) -> bool:
        account_literal = self.xpath_literal(
            self.email
        )

        account_locators: tuple[Locator, ...] = (
            (
                By.XPATH,
                "//div[@data-test-id="
                f"{account_literal}]",
            ),
            (
                By.XPATH,
                "//*[@role='listitem' "
                "or @role='button']"
                "[.//*[normalize-space()="
                f"{account_literal}]]",
            ),
            (
                By.XPATH,
                "//small[normalize-space()="
                f"{account_literal}]",
            ),
        )

        if not self.actions.is_any_visible(
            account_locators
        ):
            return False

        self.actions.click_first_visible(
            locators=account_locators,
            element_name="Outlook account tile",
            timeout=10,
            success_condition=lambda: (
                self.actions.is_any_visible(
                    self.PASSWORD_INPUT_LOCATORS
                )
                or self.actions.is_any_visible(
                    self.EMAIL_INPUT_LOCATORS
                )
                or self.is_mailbox_page()
            ),
            success_name=(
                "password, email, or mailbox"
            ),
            transition_timeout=30,
        )

        return True

    def handle_otp_method(self) -> bool:
        if not self.totp_secret:
            return False

        if not self.actions.is_any_visible(
            self.OTP_METHOD_LOCATORS
        ):
            return False

        if pyotp is None:
            raise OutlookLoginFlowError(
                "Chưa cài pyotp"
            )

        self.actions.click_first_visible(
            locators=self.OTP_METHOD_LOCATORS,
            element_name="Use verification code",
            timeout=15,
            success_condition=lambda: (
                self.actions.is_any_visible(
                    self.OTP_INPUT_LOCATORS
                )
            ),
            success_name="OTP input",
            transition_timeout=30,
        )

        return True

    def handle_otp_input(self) -> bool:
        if not self.actions.is_any_visible(
            self.OTP_INPUT_LOCATORS
        ):
            return False

        if not self.totp_secret:
            self.wait_for_manual_mfa(
                reason=(
                    "Hãy nhập Microsoft verification "
                    "code trực tiếp trên browser"
                )
            )

            return True

        if pyotp is None:
            raise OutlookLoginFlowError(
                "Chưa cài pyotp"
            )

        code = pyotp.TOTP(
            self.totp_secret.replace(
                " ",
                "",
            )
        ).now()

        self.actions.type_text_first_visible(
            locators=self.OTP_INPUT_LOCATORS,
            value=code,
            element_name=(
                "Outlook verification code"
            ),
            timeout=20,
            press_tab=True,
            verify_value=True,
        )

        self.actions.click_first_visible(
            locators=self.OTP_SUBMIT_LOCATORS,
            element_name="OTP Continue",
            timeout=20,
            success_condition=lambda: (
                self.actions.is_any_visible(
                    self.KMSI_PAGE_LOCATORS
                )
                or self.actions.is_any_visible(
                    self.SKIP_SETUP_LOCATORS
                )
                or self.is_mailbox_page()
            ),
            success_name=(
                "Stay signed in or mailbox"
            ),
            transition_timeout=60,
        )

        return True

    def handle_manual_mfa(self) -> bool:
        if not self.actions.is_any_visible(
            self.PUSH_NUMBER_LOCATORS
        ):
            return False

        element, _ = (
            self.actions.find_first_visible(
                locators=self.PUSH_NUMBER_LOCATORS,
                element_name=(
                    "Authenticator approval"
                ),
                timeout=10,
            )
        )

        number = (
            element.text or ""
        ).strip()

        print(
            "[OUTLOOK LOGIN] "
            "Microsoft Authenticator required"
        )

        if number:
            print(
                "[OUTLOOK LOGIN] "
                f"Authenticator number: {number}"
            )

        self.wait_for_manual_mfa(
            reason=(
                "Đang chờ Microsoft Authenticator"
            )
        )

        return True

    def wait_for_manual_mfa(
        self,
        reason: str,
    ) -> None:
        print(
            "[OUTLOOK LOGIN] "
            f"{reason} "
            f"| Timeout={self.manual_mfa_timeout}s"
        )

        success = self.actions.wait_until(
            condition=lambda: (
                self.actions.is_any_visible(
                    self.KMSI_PAGE_LOCATORS
                )
                or self.actions.is_any_visible(
                    self.SKIP_SETUP_LOCATORS
                )
                or self.actions.is_any_visible(
                    self.MORE_INFORMATION_NEXT_LOCATORS
                )
                or self.is_mailbox_page()
            ),
            condition_name=(
                "manual Microsoft MFA completion"
            ),
            timeout=self.manual_mfa_timeout,
            raise_on_timeout=False,
        )

        if not success:
            raise OutlookMfaRequiredError(
                "MFA chưa hoàn tất sau "
                f"{self.manual_mfa_timeout} giây"
            )

    def handle_stay_signed_in(self) -> bool:
        if not self.actions.is_any_visible(
            self.KMSI_PAGE_LOCATORS
        ):
            return False

        locators = (
            self.KMSI_YES_LOCATORS
            if self.stay_signed_in
            else self.KMSI_NO_LOCATORS
        )

        name = (
            "Stay signed in Yes"
            if self.stay_signed_in
            else "Stay signed in No"
        )

        self.actions.click_first_visible(
            locators=locators,
            element_name=name,
            timeout=20,
            success_condition=lambda: (
                self.is_mailbox_page()
                or self.actions.is_any_visible(
                    self.SKIP_SETUP_LOCATORS
                )
                or self.actions.is_any_visible(
                    self.MORE_INFORMATION_NEXT_LOCATORS
                )
            ),
            success_name=(
                "mailbox or security setup"
            ),
            transition_timeout=90,
        )

        return True

    def handle_security_setup(self) -> bool:
        if self.actions.is_any_visible(
            self.SKIP_SETUP_LOCATORS
        ):
            self.actions.click_first_visible(
                locators=self.SKIP_SETUP_LOCATORS,
                element_name="Skip security setup",
                timeout=15,
                success_condition=lambda: (
                    self.is_mailbox_page()
                    or not self.actions.is_any_visible(
                        self.SKIP_SETUP_LOCATORS
                    )
                ),
                success_name=(
                    "security setup dismissed"
                ),
                transition_timeout=60,
            )

            return True

        if self.actions.is_any_visible(
            self.MORE_INFORMATION_NEXT_LOCATORS
        ):
            self.actions.click_first_visible(
                locators=(
                    self.MORE_INFORMATION_NEXT_LOCATORS
                ),
                element_name=(
                    "More information required Next"
                ),
                timeout=15,
                success_condition=lambda: (
                    self.actions.is_any_visible(
                        self.SKIP_SETUP_LOCATORS
                    )
                    or self.is_mailbox_page()
                ),
                success_name=(
                    "security setup skip option"
                ),
                transition_timeout=60,
            )

            return True

        return False

    def raise_if_login_error(self) -> None:
        for locator in self.LOGIN_ERROR_LOCATORS:
            try:
                elements = self.driver.find_elements(
                    *locator
                )

                for element in elements:
                    if not element.is_displayed():
                        continue

                    message = (
                        element.text or ""
                    ).strip()

                    if message:
                        raise OutlookLoginRejectedError(
                            "Microsoft login error: "
                            f"{message}"
                        )

            except OutlookLoginRejectedError:
                raise

            except Exception:
                continue

    def is_mailbox_page(self) -> bool:
        try:
            current_url = str(
                self.driver.current_url or ""
            ).lower()

            if not any(
                keyword in current_url
                for keyword in self.MAILBOX_URL_KEYWORDS
            ):
                return False

            return not any(
                keyword in current_url
                for keyword in self.LOGIN_URL_KEYWORDS
            )

        except Exception:
            return False

    def validate_credentials(self) -> None:
        if not self.email:
            raise OutlookCredentialsMissingError(
                "Thiếu OUTLOOK_EMAIL"
            )

        if not self.password:
            raise OutlookCredentialsMissingError(
                "Thiếu OUTLOOK_PASSWORD"
            )

    def safe_current_url(self) -> str:
        try:
            return str(
                self.driver.current_url or ""
            )

        except Exception:
            return ""

    @staticmethod
    def xpath_literal(
        value: str,
    ) -> str:
        if "'" not in value:
            return f"'{value}'"

        if '"' not in value:
            return f'"{value}"'

        parts = value.split("'")

        xpath_parts: list[str] = []

        for index, part in enumerate(parts):
            if part:
                xpath_parts.append(
                    f"'{part}'"
                )

            if index < len(parts) - 1:
                xpath_parts.append(
                    '"\'"'
                )

        return (
            "concat("
            + ", ".join(xpath_parts)
            + ")"
        )