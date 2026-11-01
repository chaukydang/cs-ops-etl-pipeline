from __future__ import annotations

from typing import Any

TOKEN_HEADER_NAMES = (
    "open-api-token",
    "x-open-api-token",
    "openapitoken",
)


def extract_open_api_token(headers: dict[str, Any]) -> str | None:
    """Compatibility helper. Main capture logic remains in DashboardAuthManager."""
    if not isinstance(headers, dict):
        return None
    for name, value in headers.items():
        normalized = str(name).strip().lower().replace("_", "-")
        if normalized in TOKEN_HEADER_NAMES:
            token = str(value or "").strip()
            if token:
                return token
    return None
