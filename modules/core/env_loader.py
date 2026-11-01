from __future__ import annotations

import os
from pathlib import Path


def load_env_file(
    env_file: str | Path,
) -> None:
    """
    Đọc file .env mà không cần python-dotenv.
    """

    path = Path(env_file)

    if not path.exists():
        raise FileNotFoundError(
            f"Không tìm thấy .env: {path}"
        )

    for raw_line in path.read_text(
        encoding="utf-8"
    ).splitlines():
        line = raw_line.strip()

        if not line:
            continue

        if line.startswith("#"):
            continue

        if "=" not in line:
            continue

        key, value = line.split(
            "=",
            1,
        )

        key = key.strip()

        value = value.strip()

        if (
            len(value) >= 2
            and value[0] == value[-1]
            and value[0] in (
                '"',
                "'",
            )
        ):
            value = value[1:-1]

        if key:
            os.environ[key] = value


def get_required_env(
    key: str,
) -> str:
    value = os.getenv(
        key,
        "",
    ).strip()

    if not value:
        raise RuntimeError(
            "Thiếu environment variable: "
            f"{key}"
        )

    return value


def get_optional_env(
    key: str,
    default: str | None = None,
) -> str | None:
    value = os.getenv(key)

    if value is None:
        return default

    value = value.strip()

    if not value:
        return default

    return value