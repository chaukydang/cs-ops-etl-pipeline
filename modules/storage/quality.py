from __future__ import annotations

import csv
from pathlib import Path


class DataQualityError(Exception):
    pass


def read_header(csv_file: Path) -> list[str]:
    with csv_file.open("r", encoding="utf-8-sig", newline="") as file:
        header = next(csv.reader(file), None)
    if not header:
        raise DataQualityError(f"CSV has no header: {csv_file.name}")
    return header


def check_row_count(
    rows: int,
    previous_rows: int | None,
    min_rows: int = 1,
    max_drop_ratio: float = 0.5,
) -> None:
    """Fail on an empty file or a sudden large drop versus the previous run."""
    if rows < min_rows:
        raise DataQualityError(f"Too few rows: {rows} (minimum {min_rows})")

    if previous_rows and previous_rows > 0:
        drop = 1 - rows / previous_rows
        if drop > max_drop_ratio:
            raise DataQualityError(
                f"Row count dropped {drop:.0%}: {previous_rows} -> {rows}"
            )


def check_header_unchanged(
    header: list[str],
    expected: list[str] | None,
) -> None:
    if expected is not None and header != expected:
        missing = [h for h in expected if h not in header]
        extra = [h for h in header if h not in expected]
        raise DataQualityError(f"Header changed | missing={missing} | extra={extra}")
