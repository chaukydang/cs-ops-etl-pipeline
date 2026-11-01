from __future__ import annotations

import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

# ============================================================
# PATHS
# ============================================================

PROJECT_ROOT = Path(
    __file__
).resolve().parents[2]

RAW_DIRECTORY = (
    PROJECT_ROOT
    / "downloads"
    / "lark"
    / "sheets"
    / "raw"
)

TRANSFORMED_DIRECTORY = (
    PROJECT_ROOT
    / "downloads"
    / "lark"
    / "sheets"
    / "transformed"
)

PRODUCTIVITY_RAW_FILE = (
    RAW_DIRECTORY
    / "ProductivityDataReportRaw.csv"
)

BACKLOG_RAW_FILE = (
    RAW_DIRECTORY
    / "BacklogActionAbleCapacityRaw.csv"
)

PRODUCTIVITY_OUTPUT_FILE = (
    TRANSFORMED_DIRECTORY
    / "ProductivityDataReport.csv"
)

BACKLOG_OUTPUT_FILE = (
    TRANSFORMED_DIRECTORY
    / "BacklogActionAbleCapacity.csv"
)

LOG_DIRECTORY = (
    PROJECT_ROOT
    / "logs"
)

LOG_FILE = (
    LOG_DIRECTORY
    / "lark_transform.log"
)


# ============================================================
# SETTINGS
# ============================================================

PRODUCTIVITY_COLUMN_COUNT = 30
BACKLOG_COLUMN_COUNT = 13

PRODUCTIVITY_FILTER_INDEX = 26
PRODUCTIVITY_DATE_INDEX = 28

BACKLOG_REQUIRED_INDEX = 0
BACKLOG_FILTER_INDEX = 5

PRODUCTIVITY_DAYS_BACK = 40

EXCLUDED_VALUES = {
    "SWAT SS",
    "SWAT CR",
}

BACKLOG_TRAILING_BLANK_COLUMNS = 5


LOGGER = logging.getLogger(
    "LarkRawTransformer"
)


# ============================================================
# LOGGING
# ============================================================


def setup_logging() -> None:
    LOG_DIRECTORY.mkdir(
        parents=True,
        exist_ok=True,
    )

    logging.basicConfig(
        level=logging.INFO,
        format=(
            "%(asctime)s | "
            "%(levelname)s | "
            "%(name)s | "
            "%(message)s"
        ),
        handlers=[
            logging.FileHandler(
                LOG_FILE,
                encoding="utf-8",
            ),
            logging.StreamHandler(),
        ],
        force=True,
    )


# ============================================================
# RAW CSV
# ============================================================


def read_raw_csv(
    file_path: Path,
    expected_columns: int,
) -> pd.DataFrame:
    if not file_path.exists():
        raise FileNotFoundError(
            f"Không tìm thấy raw file: "
            f"{file_path}"
        )

    dataframe = pd.read_csv(
        file_path,
        header=None,
        dtype=object,
        encoding="utf-8-sig",
        keep_default_na=False,
        na_filter=False,
        engine="python",
        on_bad_lines="warn",
    )

    actual_columns = len(
        dataframe.columns
    )

    if actual_columns < expected_columns:
        raise ValueError(
            f"{file_path.name} thiếu cột | "
            f"actual={actual_columns} | "
            f"expected={expected_columns}"
        )

    if actual_columns > expected_columns:
        LOGGER.warning(
            "%s có %s cột; "
            "chỉ giữ %s cột đầu",
            file_path.name,
            actual_columns,
            expected_columns,
        )

        dataframe = dataframe.iloc[
            :,
            :expected_columns,
        ].copy()

    dataframe.columns = [
        column_number_to_name(
            index
        )
        for index in range(
            1,
            expected_columns + 1,
        )
    ]

    dataframe = remove_fully_empty_rows(
        dataframe
    )

    LOGGER.info(
        "Raw loaded | "
        "file=%s | rows=%s | columns=%s",
        file_path.name,
        len(dataframe),
        len(dataframe.columns),
    )

    return dataframe


# ============================================================
# PRODUCTIVITY
# ============================================================


def transform_productivity(
    dataframe: pd.DataFrame,
    today: datetime | None = None,
) -> pd.DataFrame:
    if (
        len(dataframe.columns)
        != PRODUCTIVITY_COLUMN_COUNT
    ):
        raise ValueError(
            "Productivity raw phải có "
            "đúng 30 cột A:AD"
        )

    source = dataframe.copy()

    # Productivity raw có header ở dòng đầu.
    header = make_unique_headers(
        [
            (
                str(value).strip()
                or column_number_to_name(
                    index
                )
            )
            for index, value in enumerate(
                source.iloc[0].tolist(),
                start=1,
            )
        ]
    )

    data = (
        source.iloc[1:]
        .copy()
        .reset_index(drop=True)
    )

    # LOWER(A:A)
    data.iloc[:, 0] = (
        data.iloc[:, 0]
        .map(lower_value)
    )

    # DATEVALUE(AC:AC)
    source_dates = parse_date_series(
        data.iloc[
            :,
            PRODUCTIVITY_DATE_INDEX,
        ]
    )

    current_date = pd.Timestamp(
        today or datetime.now()
    ).normalize()

    minimum_date = (
        current_date
        - pd.Timedelta(
            days=PRODUCTIVITY_DAYS_BACK
        )
    )

    filter_values = normalize_text_series(
        data.iloc[
            :,
            PRODUCTIVITY_FILTER_INDEX,
        ]
    ).str.upper()

    mask = (
        source_dates.gt(
            minimum_date
        )
        & ~filter_values.isin(
            EXCLUDED_VALUES
        )
    )

    result = (
        data.loc[mask]
        .copy()
        .reset_index(drop=True)
    )

    if result.empty:
        raise ValueError(
            "Productivity transform "
            "trả về 0 dòng | "
            f"date_parse_errors="
            f"{int(source_dates.isna().sum())} | "
            f"cutoff>{minimum_date:%Y-%m-%d}"
        )

    result = apply_numbervalue(
        result
    )

    result = (
        result.drop_duplicates(
            keep="first"
        )
        .reset_index(drop=True)
    )

    result.columns = header

    LOGGER.info(
        "Productivity transformed | "
        "output_rows=%s | "
        "columns=%s | "
        "cutoff>%s",
        len(result),
        len(result.columns),
        minimum_date.strftime(
            "%Y-%m-%d"
        ),
    )

    return result


# ============================================================
# BACKLOG
# ============================================================


def transform_backlog(
    dataframe: pd.DataFrame,
) -> pd.DataFrame:
    if (
        len(dataframe.columns)
        != BACKLOG_COLUMN_COUNT
    ):
        raise ValueError(
            "Backlog raw phải có đúng "
            "13 cột A:M"
        )

    # Backlog raw không có header.
    # Dòng đầu tiên là data thật.
    result = dataframe.copy()

    column_a = normalize_text_series(
        result.iloc[
            :,
            BACKLOG_REQUIRED_INDEX,
        ]
    )

    column_f = normalize_text_series(
        result.iloc[
            :,
            BACKLOG_FILTER_INDEX,
        ]
    ).str.upper()

    mask = (
        column_a.ne("")
        & ~column_f.isin(
            EXCLUDED_VALUES
        )
    )

    result = (
        result.loc[mask]
        .copy()
        .reset_index(drop=True)
    )

    if result.empty:
        raise ValueError(
            "Backlog transform "
            "trả về 0 dòng"
        )

    # IFERROR(
    #     NUMBERVALUE(Raw!A:M),
    #     Raw!A:M
    # )
    result = apply_numbervalue(
        result
    )

    # UNIQUE
    result = (
        result.drop_duplicates(
            keep="first"
        )
        .reset_index(drop=True)
    )

    # Raw I là Date.
    result.iloc[:, 8] = (
        result.iloc[:, 8]
        .map(
            format_backlog_display_date
        )
    )

    # Header cố định của ImportBase.
    result.columns = [
        "Primary Skill Group",
        "Today Handled",
        "Online",
        "Agent",
        "Function",
        "Task",
        "UnActionable",
        "Actionable",
        "Date",
        "Hour",
        "Volume",
        "DateImport",
        "HourImport",
    ]

    # Index sinh sau FILTER + UNIQUE.
    result.insert(
        0,
        "Index",
        range(
            1,
            len(result) + 1,
        ),
    )

    # Giữ 5 cột rỗng giống file
    # ImportBase tải từ system.
    for blank_index in range(
        1,
        BACKLOG_TRAILING_BLANK_COLUMNS
        + 1,
    ):
        result[
            f"__blank_{blank_index}"
        ] = ""

    LOGGER.info(
        "Backlog transformed | "
        "data_rows=%s | "
        "file_lines=%s | "
        "columns=%s",
        len(result),
        len(result) + 1,
        len(result.columns),
    )

    return result


# ============================================================
# OUTPUT
# ============================================================


def write_output_csv(
    dataframe: pd.DataFrame,
    output_file: Path,
) -> Path:
    output_file.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    temporary_file = (
        output_file.with_suffix(
            output_file.suffix
            + ".part"
        )
    )

    try:
        output = dataframe.copy()

        output.columns = [
            (
                ""
                if str(column).startswith(
                    "__blank_"
                )
                else column
            )
            for column in output.columns
        ]

        output.to_csv(
            temporary_file,
            index=False,
            header=True,
            encoding="utf-8-sig",
            lineterminator="\n",
        )

        if (
            not temporary_file.exists()
            or temporary_file.stat().st_size
            == 0
        ):
            raise RuntimeError(
                f"Output tạm bị rỗng: "
                f"{temporary_file}"
            )

        temporary_file.replace(
            output_file
        )

    finally:
        temporary_file.unlink(
            missing_ok=True
        )

    LOGGER.info(
        "Output saved | "
        "file=%s | "
        "data_rows=%s | "
        "file_lines=%s | "
        "columns=%s | "
        "bytes=%s",
        output_file,
        len(dataframe),
        len(dataframe) + 1,
        len(dataframe.columns),
        output_file.stat().st_size,
    )

    return output_file


# ============================================================
# NUMBERVALUE
# ============================================================


def apply_numbervalue(
    dataframe: pd.DataFrame,
) -> pd.DataFrame:
    result = dataframe.copy()

    for column in result.columns:
        result[column] = (
            result[column]
            .map(numbervalue)
        )

    return result


def numbervalue(
    value: Any,
) -> Any:
    if value is None:
        return ""

    if isinstance(
        value,
        bool,
    ):
        return value

    if isinstance(
        value,
        (
            int,
            float,
        ),
    ):
        if pd.isna(value):
            return ""

        return value

    if isinstance(
        value,
        (
            datetime,
            pd.Timestamp,
        ),
    ):
        return value

    text = str(
        value
    ).strip()

    if not text:
        return ""

    if looks_like_date_or_datetime(
        text
    ):
        return text

    numeric_text = (
        text.replace(
            ",",
            "",
        )
        .replace(
            " ",
            "",
        )
    )

    is_percentage = (
        numeric_text.endswith("%")
    )

    if is_percentage:
        numeric_text = (
            numeric_text[:-1]
        )

    if not re.fullmatch(
        (
            r"[+-]?"
            r"(?:\d+(?:\.\d*)?|\.\d+)"
        ),
        numeric_text,
    ):
        return text

    try:
        number = float(
            numeric_text
        )

    except ValueError:
        return text

    if is_percentage:
        number /= 100

    if number.is_integer():
        return int(
            number
        )

    return number


def lower_value(
    value: Any,
) -> Any:
    if value is None:
        return ""

    if isinstance(
        value,
        str,
    ):
        return value.lower()

    return value


# ============================================================
# DATE HELPERS
# ============================================================


def format_backlog_display_date(
    value: Any,
) -> Any:
    text = str(
        value or ""
    ).strip()

    if not text:
        return ""

    parsed = pd.to_datetime(
        text,
        errors="coerce",
        format="mixed",
        dayfirst=False,
    )

    if pd.isna(
        parsed
    ):
        return value

    return parsed.strftime(
        "%m/%d/%Y"
    )


def parse_date_series(
    series: pd.Series,
) -> pd.Series:
    text_values = (
        normalize_text_series(
            series
        )
    )

    parsed = pd.to_datetime(
        text_values,
        errors="coerce",
        format="mixed",
        dayfirst=False,
    )

    missing_mask = parsed.isna()

    if missing_mask.any():
        dayfirst_values = pd.to_datetime(
            text_values.loc[
                missing_mask
            ],
            errors="coerce",
            format="mixed",
            dayfirst=True,
        )

        parsed.loc[
            missing_mask
        ] = dayfirst_values

    missing_mask = parsed.isna()

    if missing_mask.any():
        numeric_values = pd.to_numeric(
            text_values.loc[
                missing_mask
            ],
            errors="coerce",
        )

        serial_mask = (
            numeric_values.between(
                20000,
                80000,
                inclusive="both",
            )
        )

        if serial_mask.any():
            serial_dates = (
                pd.to_datetime(
                    numeric_values.loc[
                        serial_mask
                    ],
                    unit="D",
                    origin="1899-12-30",
                    errors="coerce",
                )
            )

            parsed.loc[
                serial_dates.index
            ] = serial_dates

    return parsed


def looks_like_date_or_datetime(
    value: str,
) -> bool:
    patterns = (
        (
            r"\d{4}-\d{1,2}-\d{1,2}"
            r"(?:\s+.*)?"
        ),
        (
            r"\d{1,2}/\d{1,2}/\d{4}"
            r"(?:\s+.*)?"
        ),
        (
            r"\d{1,2}-\d{1,2}-\d{4}"
            r"(?:\s+.*)?"
        ),
        (
            r"\d{4}/\d{1,2}/\d{1,2}"
            r"(?:\s+.*)?"
        ),
    )

    return any(
        re.fullmatch(
            pattern,
            value,
        )
        is not None
        for pattern in patterns
    )


# ============================================================
# DATAFRAME HELPERS
# ============================================================


def normalize_text_series(
    series: pd.Series,
) -> pd.Series:
    return (
        series.fillna("")
        .astype(str)
        .str.strip()
    )


def remove_fully_empty_rows(
    dataframe: pd.DataFrame,
) -> pd.DataFrame:
    normalized = (
        dataframe.fillna("")
    )

    mask = normalized.apply(
        lambda row: any(
            str(value).strip()
            for value in row
        ),
        axis=1,
    )

    return (
        dataframe.loc[mask]
        .copy()
        .reset_index(drop=True)
    )


def make_unique_headers(
    headers: list[str],
) -> list[str]:
    
    result: list[str] = []
    counts: dict[
        str,
        int,
    ] = {}

    for index, raw_header in enumerate(
        headers,
        start=1,
    ):
        base_header = (
            str(raw_header).strip()
            or column_number_to_name(
                index
            )
        )

        counts[base_header] = (
            counts.get(
                base_header,
                0,
            )
            + 1
        )

        count = counts[
            base_header
        ]

        if count == 1:
            result.append(
                base_header
            )

        else:
            result.append(
                f"{base_header}_{count}"
            )

    return result


def column_number_to_name(
    number: int,
) -> str:
    if number < 1:
        raise ValueError(
            "Column number phải >= 1"
        )

    result = ""
    current = number

    while current > 0:
        current -= 1

        result = (
            chr(
                current % 26
                + ord("A")
            )
            + result
        )

        current //= 26

    return result


# ============================================================
# MAIN
# ============================================================


def main() -> None:
    setup_logging()

    print(
        "[TRANSFORM] "
        "Loading Productivity raw..."
    )

    productivity_raw = read_raw_csv(
        PRODUCTIVITY_RAW_FILE,
        PRODUCTIVITY_COLUMN_COUNT,
    )

    productivity_result = (
        transform_productivity(
            productivity_raw
        )
    )

    write_output_csv(
        productivity_result,
        PRODUCTIVITY_OUTPUT_FILE,
    )

    print(
        "[TRANSFORM] "
        "Loading Backlog raw..."
    )

    backlog_raw = read_raw_csv(
        BACKLOG_RAW_FILE,
        BACKLOG_COLUMN_COUNT,
    )

    backlog_result = (
        transform_backlog(
            backlog_raw
        )
    )

    write_output_csv(
        backlog_result,
        BACKLOG_OUTPUT_FILE,
    )

    print(
        "\n"
        "========================================"
    )

    print(
        "TRANSFORM COMPLETED"
    )

    print(
        "========================================"
    )

    print(
        "Productivity: "
        f"data_rows="
        f"{len(productivity_result)} | "
        f"file_lines="
        f"{len(productivity_result) + 1} | "
        f"columns="
        f"{len(productivity_result.columns)} | "
        f"file={PRODUCTIVITY_OUTPUT_FILE}"
    )

    print(
        "Backlog: "
        f"data_rows="
        f"{len(backlog_result)} | "
        f"file_lines="
        f"{len(backlog_result) + 1} | "
        f"columns="
        f"{len(backlog_result.columns)} | "
        f"file={BACKLOG_OUTPUT_FILE}"
    )

    print(
        "========================================"
    )


if __name__ == "__main__":
    main()