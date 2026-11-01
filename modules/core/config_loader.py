from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def load_metric_config(
    config_file: str | Path,
) -> dict[str, Any]:
    path = Path(config_file)

    if not path.exists():
        raise FileNotFoundError(
            "Không tìm thấy config file: "
            f"{path}"
        )

    try:
        config = json.loads(
            path.read_text(
                encoding="utf-8"
            )
        )

    except json.JSONDecodeError as error:
        raise ValueError(
            "Config JSON không hợp lệ: "
            f"{path} | {error}"
        ) from error

    validate_metric_config(config)

    return config


def validate_metric_config(
    config: dict[str, Any],
) -> None:
    required_keys = (
        "metric_name",
        "endpoint",
        "payload",
    )

    missing_keys = [
        key
        for key in required_keys
        if key not in config
    ]

    if missing_keys:
        raise ValueError(
            "Metric config thiếu key: "
            + ", ".join(missing_keys)
        )

    if not isinstance(
        config["payload"],
        dict,
    ):
        raise ValueError(
            "payload phải là object/dictionary"
        )