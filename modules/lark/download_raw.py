from __future__ import annotations

import csv
import json
import logging
from pathlib import Path
from typing import Any

from modules.core.env_loader import (
    get_required_env,
    load_env_file,
)
from modules.lark.data_client import (
    LarkApiClient,
    LarkSheetClient,
)

# ============================================================
# PATHS
# ============================================================

BASE_DIR = Path(__file__).resolve().parents[2]
ENV_FILE = BASE_DIR / ".env"

CONFIG_FILE = (
    BASE_DIR
    / "configs"
    / "lark"
    / "settings.json"
)

LOG_DIRECTORY = BASE_DIR / "logs"

LOG_FILE = (
    LOG_DIRECTORY
    / "lark_raw_download.log"
)


# ============================================================
# SETTINGS
# ============================================================

CHUNK_SIZE = 5000

# Sau khi đã bắt đầu có dữ liệu, nếu gặp số chunk trống
# liên tiếp này thì dừng.
EMPTY_CHUNK_STOP = 3


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


LOGGER = logging.getLogger(
    "LarkRawDownloader"
)


# ============================================================
# CONFIG HELPERS
# ============================================================


def load_json(
    file_path: Path,
) -> dict[str, Any]:
    if not file_path.exists():
        raise FileNotFoundError(
            f"Không tìm thấy config: {file_path}"
        )

    try:
        with file_path.open(
            "r",
            encoding="utf-8-sig",
        ) as file:
            data = json.load(file)

    except json.JSONDecodeError as error:
        raise ValueError(
            "JSON không hợp lệ | "
            f"file={file_path} | "
            f"line={error.lineno} | "
            f"column={error.colno} | "
            f"error={error.msg}"
        ) from error

    if not isinstance(
        data,
        dict,
    ):
        raise ValueError(
            f"Config phải là JSON object: "
            f"{file_path}"
        )

    return data


def resolve_path(
    configured_path: str,
) -> Path:
    path = Path(
        configured_path
    )

    if path.is_absolute():
        return path.resolve()

    return (
        BASE_DIR
        / path
    ).resolve()


def required(
    source: dict[str, Any],
    key: str,
) -> str:
    value = str(
        source.get(
            key,
            "",
        )
    ).strip()

    if not value:
        source_name = str(
            source.get(
                "name",
                "unknown",
            )
        )

        raise ValueError(
            f"Source '{source_name}' "
            f"thiếu field bắt buộc: {key}"
        )

    return value


def parse_column_range(
    value: str,
) -> tuple[str, str]:
    parts = (
        str(value)
        .strip()
        .upper()
        .split(
            ":",
            maxsplit=1,
        )
    )

    if len(parts) != 2:
        raise ValueError(
            "columns phải có format "
            "A:M hoặc A:AD"
        )

    start_column = parts[0].strip()
    end_column = parts[1].strip()

    if (
        not start_column.isalpha()
        or not end_column.isalpha()
    ):
        raise ValueError(
            "columns chỉ được chứa tên cột"
        )

    return (
        start_column,
        end_column,
    )


# ============================================================
# DATA HELPERS
# ============================================================


def row_is_empty(
    row: list[Any],
) -> bool:
    """
    Chỉ xem row là trống khi tất cả cell đều trống.

    Giá trị 0 và False vẫn được xem là dữ liệu.
    """

    if not row:
        return True

    for value in row:
        if value is None:
            continue

        if isinstance(
            value,
            str,
        ):
            if value.strip():
                return False

            continue

        if isinstance(
            value,
            (
                list,
                dict,
            ),
        ):
            if value:
                return False

            continue

        return False

    return True


def normalize_cell(
    value: Any,
) -> Any:
    """
    Chuẩn hóa value từ Lark Sheets API.

    Quy tắc:
    - None thành chuỗi rỗng.
    - String, number, boolean giữ nguyên.
    - Hyperlink object lấy text trước.
    - Email link bỏ prefix mailto:.
    - User object lấy name.
    - List hyperlink/user nối bằng " | ".
    - Object phức tạp còn lại lưu JSON.
    """

    if value is None:
        return ""

    if isinstance(
        value,
        (
            str,
            int,
            float,
            bool,
        ),
    ):
        return value

    if isinstance(
        value,
        dict,
    ):
        return normalize_object(
            value
        )

    if isinstance(
        value,
        list,
    ):
        normalized_items: list[str] = []

        for item in value:
            normalized_item = (
                normalize_cell(item)
            )

            if normalized_item is None:
                continue

            normalized_text = str(
                normalized_item
            ).strip()

            if normalized_text:
                normalized_items.append(
                    normalized_text
                )

        return " | ".join(
            normalized_items
        )

    return str(value)


def normalize_object(
    value: dict[str, Any],
) -> str:
    """
    Chuẩn hóa object trả về từ Lark.

    Ví dụ hyperlink:

    {
        "link": "mailto:user@company.com",
        "text": "user@company.com",
        "type": "url"
    }

    Kết quả:

    user@company.com
    """

    text_value = str(
        value.get(
            "text",
            "",
        )
        or ""
    ).strip()

    if text_value:
        return text_value

    name_value = str(
        value.get(
            "name",
            "",
        )
        or ""
    ).strip()

    if name_value:
        return name_value

    email_value = str(
        value.get(
            "email",
            "",
        )
        or ""
    ).strip()

    if email_value:
        return email_value

    link_value = str(
        value.get(
            "link",
            "",
        )
        or ""
    ).strip()

    if link_value:
        return remove_mailto_prefix(
            link_value
        )

    url_value = str(
        value.get(
            "url",
            "",
        )
        or ""
    ).strip()

    if url_value:
        return remove_mailto_prefix(
            url_value
        )

    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(
            ",",
            ":",
        ),
    )


def remove_mailto_prefix(
    value: str,
) -> str:
    clean_value = str(
        value
    ).strip()

    if clean_value.lower().startswith(
        "mailto:"
    ):
        return clean_value[7:]

    return clean_value


# ============================================================
# SHEET LOOKUP
# ============================================================


def find_sheet(
    client: LarkSheetClient,
    spreadsheet_token: str,
    sheet_name: str,
) -> dict[str, Any]:
    sheets = client.get_sheets(
        spreadsheet_token
    )

    target_sheet = next(
        (
            sheet
            for sheet in sheets
            if str(
                sheet.get(
                    "title",
                    "",
                )
            ).strip()
            == sheet_name.strip()
        ),
        None,
    )

    if target_sheet is None:
        available_sheets = [
            str(
                sheet.get(
                    "title",
                    "",
                )
            )
            for sheet in sheets
        ]

        raise ValueError(
            f"Không tìm thấy sheet "
            f"'{sheet_name}'. "
            f"Available={available_sheets}"
        )

    return target_sheet


# ============================================================
# DOWNLOAD ONE SOURCE
# ============================================================


def download_raw_source(
    client: LarkSheetClient,
    source: dict[str, Any],
) -> dict[str, Any]:
    name = required(
        source,
        "name",
    )

    spreadsheet_token = required(
        source,
        "spreadsheet_token",
    )

    sheet_name = required(
        source,
        "sheet_name",
    )

    columns = required(
        source,
        "columns",
    )

    output_file = resolve_path(
        required(
            source,
            "output",
        )
    )

    start_column, end_column = (
        parse_column_range(
            columns
        )
    )

    sheet = find_sheet(
        client=client,
        spreadsheet_token=(
            spreadsheet_token
        ),
        sheet_name=sheet_name,
    )

    sheet_id = str(
        sheet.get(
            "sheet_id",
            "",
        )
    ).strip()

    if not sheet_id:
        raise ValueError(
            f"Sheet '{sheet_name}' "
            "không có sheet_id"
        )

    grid_properties = (
        sheet.get(
            "grid_properties",
            {},
        )
        or {}
    )

    row_count = max(
        int(
            grid_properties.get(
                "row_count",
                1,
            )
            or 1
        ),
        1,
    )

    print(
        "[LARK RAW] "
        f"Source={name} | "
        f"Sheet={sheet_name} | "
        f"Sheet ID={sheet_id} | "
        f"Grid rows={row_count} | "
        f"Columns={columns}"
    )

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

    total_written = 0
    empty_chunk_count = 0
    data_started = False

    try:
        with temporary_file.open(
            "w",
            encoding="utf-8-sig",
            newline="",
        ) as file:
            writer = csv.writer(
                file
            )

            for start_row in range(
                1,
                row_count + 1,
                CHUNK_SIZE,
            ):
                end_row = min(
                    start_row
                    + CHUNK_SIZE
                    - 1,
                    row_count,
                )

                range_a1 = (
                    f"{sheet_id}!"
                    f"{start_column}{start_row}:"
                    f"{end_column}{end_row}"
                )

                print(
                    "[LARK RAW] "
                    f"Reading | "
                    f"Source={name} | "
                    f"Range={range_a1}"
                )

                rows = client.get_values(
                    spreadsheet_token=(
                        spreadsheet_token
                    ),
                    range_a1=range_a1,
                    value_render_option=(
                        "FormattedValue"
                    ),
                    date_time_render_option=(
                        "FormattedString"
                    ),
                )

                non_empty_rows = [
                    row
                    for row in rows
                    if not row_is_empty(
                        row
                    )
                ]

                if not non_empty_rows:
                    if data_started:
                        empty_chunk_count += 1

                    if (
                        data_started
                        and empty_chunk_count
                        >= EMPTY_CHUNK_STOP
                    ):
                        print(
                            "[LARK RAW] "
                            f"Stopping {name} after "
                            f"{EMPTY_CHUNK_STOP} "
                            "consecutive empty chunks"
                        )

                        break

                    continue

                data_started = True
                empty_chunk_count = 0

                for row in non_empty_rows:
                    normalized_row = [
                        normalize_cell(
                            value
                        )
                        for value in row
                    ]

                    writer.writerow(
                        normalized_row
                    )

                    total_written += 1

        if total_written == 0:
            raise RuntimeError(
                f"Source '{name}' "
                "không trả dữ liệu"
            )

        temporary_file.replace(
            output_file
        )

    finally:
        if temporary_file.exists():
            try:
                temporary_file.unlink()

            except OSError:
                pass

    file_size = (
        output_file.stat().st_size
    )

    print(
        "[LARK RAW] "
        f"Completed | "
        f"Source={name} | "
        f"Rows={total_written} | "
        f"Bytes={file_size} | "
        f"File={output_file}"
    )

    return {
        "name": name,
        "sheet_name": sheet_name,
        "sheet_id": sheet_id,
        "rows": total_written,
        "bytes": file_size,
        "output": str(
            output_file
        ),
    }


# ============================================================
# MAIN
# ============================================================


def main() -> None:
    setup_logging()

    if not ENV_FILE.exists():
        raise FileNotFoundError(
            f"Không tìm thấy .env: "
            f"{ENV_FILE}"
        )

    if not CONFIG_FILE.exists():
        raise FileNotFoundError(
            f"Không tìm thấy config: "
            f"{CONFIG_FILE}"
        )

    load_env_file(
        ENV_FILE
    )

    config = load_json(
        CONFIG_FILE
    )

    sources = config.get(
        "sources",
        [],
    )

    if not isinstance(
        sources,
        list,
    ):
        raise ValueError(
            "sources phải là list"
        )

    enabled_sources = [
        source
        for source in sources
        if (
            isinstance(
                source,
                dict,
            )
            and source.get(
                "enabled",
                True,
            )
        )
    ]

    if not enabled_sources:
        raise RuntimeError(
            "Không có raw source nào enabled"
        )

    api = LarkApiClient(
        app_id=get_required_env(
            "LARK_SHEET_APP_ID"
        ),
        app_secret=get_required_env(
            "LARK_SHEET_APP_SECRET"
        ),
        timeout=120,
    )

    client = LarkSheetClient(
        api
    )

    completed: list[
        dict[str, Any]
    ] = []

    failed: list[
        dict[str, Any]
    ] = []

    print(
        "[LARK RAW] "
        f"Enabled sources="
        f"{len(enabled_sources)}"
    )

    for index, source in enumerate(
        enabled_sources,
        start=1,
    ):
        name = str(
            source.get(
                "name",
                f"source_{index}",
            )
        ).strip()

        print(
            "\n"
            "[LARK RAW] "
            f"Running {index}/"
            f"{len(enabled_sources)} "
            f"| {name}"
        )

        try:
            result = download_raw_source(
                client=client,
                source=source,
            )

            completed.append(
                result
            )

        except Exception as error:
            LOGGER.exception(
                "Raw source failed | "
                "name=%s",
                name,
            )

            failed.append(
                {
                    "name": name,
                    "error_type": (
                        type(error).__name__
                    ),
                    "error": str(error),
                }
            )

            print(
                "[LARK RAW FAILED] "
                f"{name} | "
                f"{type(error).__name__}: "
                f"{error}"
            )

    print(
        "\n"
        "========================================"
    )

    print(
        "LARK RAW DOWNLOAD SUMMARY"
    )

    print(
        "========================================"
    )

    print(
        f"Completed: {len(completed)}"
    )

    print(
        f"Failed: {len(failed)}"
    )

    if completed:
        print(
            "\nCompleted sources:"
        )

        for result in completed:
            print(
                "  [OK] "
                f"{result['name']} | "
                f"Rows={result['rows']} | "
                f"Bytes={result['bytes']} | "
                f"File={result['output']}"
            )

    if failed:
        print(
            "\nFailed sources:"
        )

        for result in failed:
            print(
                "  [FAILED] "
                f"{result['name']} | "
                f"{result['error_type']} | "
                f"{result['error']}"
            )

    print(
        "========================================"
    )

    if failed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()