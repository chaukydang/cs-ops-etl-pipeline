from __future__ import annotations

import logging
import socket
from datetime import datetime
from typing import Any

import requests


class LarkNotifier:
    def __init__(
        self,
        webhook_url: str | None,
        timeout: int = 15,
    ) -> None:
        self.webhook_url = (
            webhook_url.strip()
            if webhook_url
            else ""
        )

        self.timeout = timeout

        self.hostname = (
            socket.gethostname()
        )

        self.logger = logging.getLogger(
            self.__class__.__name__
        )

    def send_info(
        self,
        title: str,
        message: str,
        details: dict[str, Any] | None = None,
    ) -> bool:
        return self.send_event(
            level="INFO",
            title=title,
            message=message,
            details=details,
        )

    def send_warning(
        self,
        title: str,
        message: str,
        details: dict[str, Any] | None = None,
    ) -> bool:
        return self.send_event(
            level="WARNING",
            title=title,
            message=message,
            details=details,
        )

    def send_error(
        self,
        title: str,
        message: str,
        details: dict[str, Any] | None = None,
    ) -> bool:
        return self.send_event(
            level="ERROR",
            title=title,
            message=message,
            details=details,
        )

    def send_event(
        self,
        level: str,
        title: str,
        message: str,
        details: dict[str, Any] | None = None,
    ) -> bool:
        if not self.webhook_url:
            self.logger.warning(
                "Lark webhook chưa được cấu hình"
            )

            return False

        event_time = datetime.now().strftime(
            "%Y-%m-%d %H:%M:%S"
        )

        lines = [
            f"ETL PIPELINE | {level}",
            "",
            f"Event: {title}",
            f"Time: {event_time}",
            f"Machine: {self.hostname}",
            f"Message: {message}",
        ]

        if details:
            lines.append("")
            lines.append("Details:")

            for key, value in details.items():
                safe_value = (
                    self._sanitize_value(
                        key=key,
                        value=value,
                    )
                )

                lines.append(
                    f"- {key}: {safe_value}"
                )

        payload = {
            "msg_type": "text",
            "content": {
                "text": "\n".join(lines),
            },
        }

        try:
            response = requests.post(
                self.webhook_url,
                json=payload,
                timeout=self.timeout,
            )

            response.raise_for_status()

            response_data: dict[str, Any] = {}

            try:
                response_data = (
                    response.json()
                )

            except ValueError:
                pass

            response_code = (
                response_data.get(
                    "code",
                    response_data.get(
                        "StatusCode",
                        0,
                    ),
                )
            )

            if response_code not in (
                0,
                "0",
                None,
            ):
                raise RuntimeError(
                    "Lark webhook trả lỗi: "
                    f"{response_data}"
                )

            return True

        except Exception as error:
            self.logger.error(
                "Không gửi được Lark webhook: %s",
                error,
            )

            return False

    @staticmethod
    def _sanitize_value(
        key: str,
        value: Any,
    ) -> str:
        sensitive_keywords = (
            "token",
            "cookie",
            "password",
            "secret",
            "authorization",
            "session",
        )

        normalized_key = key.lower()

        if any(
            keyword in normalized_key
            for keyword
            in sensitive_keywords
        ):
            return "[REDACTED]"

        text = str(value)

        if len(text) > 1500:
            return (
                text[:1500]
                + "...[truncated]"
            )

        return text