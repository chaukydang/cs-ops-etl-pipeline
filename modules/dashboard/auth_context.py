from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class AeolusAuthContext:
    open_api_token: str
    cookies: dict[str, str]
    app_id: str

    captured_at: datetime = field(
        default_factory=datetime.now
    )

    def is_valid(
        self,
    ) -> bool:
        return bool(
            self.open_api_token
            and self.open_api_token.strip()
        )