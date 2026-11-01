from __future__ import annotations

from pathlib import Path
from typing import Any

from modules.core.env_loader import get_required_env
from modules.lark.data_client import (
    LarkApiClient,
    LarkBaseClient,
    LarkSheetClient,
)


class LarkDataManager:
    """
    Quản lý hai Lark apps độc lập:

    1. App dành cho Lark Sheets.
    2. App dành cho Lark Base.
    """

    def __init__(
        self,
        sheet_app_id: str,
        sheet_app_secret: str,
        base_app_id: str,
        base_app_secret: str,
        api_base_url: str = (
            "https://open.larksuite.com/open-apis"
        ),
        timeout: int = 120,
    ) -> None:
        self.sheet_api = LarkApiClient(
            app_id=sheet_app_id,
            app_secret=sheet_app_secret,
            base_url=api_base_url,
            timeout=timeout,
        )

        self.base_api = LarkApiClient(
            app_id=base_app_id,
            app_secret=base_app_secret,
            base_url=api_base_url,
            timeout=timeout,
        )

        self.sheet = LarkSheetClient(
            self.sheet_api
        )

        self.base = LarkBaseClient(
            self.base_api
        )

    @classmethod
    def from_environment(
        cls,
        timeout: int = 120,
    ) -> "LarkDataManager":
        return cls(
            sheet_app_id=get_required_env(
                "LARK_SHEET_APP_ID"
            ),
            sheet_app_secret=get_required_env(
                "LARK_SHEET_APP_SECRET"
            ),
            base_app_id=get_required_env(
                "LARK_BASE_APP_ID"
            ),
            base_app_secret=get_required_env(
                "LARK_BASE_APP_SECRET"
            ),
            timeout=timeout,
        )

    def download_sheet_range(
        self,
        spreadsheet_token: str,
        range_a1: str,
        output_file: str | Path,
    ) -> Path:
        return self.sheet.export_range_csv(
            spreadsheet_token=(
                spreadsheet_token
            ),
            range_a1=range_a1,
            output_file=output_file,
        )

    def download_full_sheet_tab(
        self,
        spreadsheet_token: str,
        sheet_name: str,
        output_file: str | Path,
    ) -> Path:
        sheets = self.sheet.get_sheets(
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
                f"Available sheets="
                f"{available_sheets}"
            )

        sheet_id = str(
            target_sheet.get(
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
            target_sheet.get(
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

        column_count = max(
            int(
                grid_properties.get(
                    "column_count",
                    1,
                )
                or 1
            ),
            1,
        )

        print(
            "[LARK SHEET] "
            f"Sheet={sheet_name} | "
            f"Sheet ID={sheet_id} | "
            f"Grid Rows={row_count} | "
            f"Grid Columns={column_count}"
        )

        return (
            self.sheet
            .export_full_tab_csv(
                spreadsheet_token=(
                    spreadsheet_token
                ),
                sheet_id=sheet_id,
                row_count=row_count,
                column_count=(
                    column_count
                ),
                output_file=output_file,
                chunk_size=5000,
            )
        )

    def download_all_sheet_tabs(
        self,
        spreadsheet_token: str,
        output_directory: str | Path,
        max_columns: str = "ZZ",
    ) -> list[Path]:
        return (
            self.sheet
            .export_all_sheets_csv(
                spreadsheet_token=(
                    spreadsheet_token
                ),
                output_directory=(
                    output_directory
                ),
                max_columns=max_columns,
            )
        )

    def download_base_table(
        self,
        app_token: str,
        table_id: str,
        output_file: str | Path,
        *,
        view_id: str | None = None,
        field_names: list[str] | None = None,
        filter_info: (
            dict[str, Any] | None
        ) = None,
        sort: (
            list[dict[str, Any]] | None
        ) = None,
    ) -> Path:
        return self.base.export_records_csv(
            app_token=app_token,
            table_id=table_id,
            output_file=output_file,
            view_id=view_id,
            field_names=field_names,
            filter_info=filter_info,
            sort=sort,
        )

    @staticmethod
    def _column_number_to_name(
        column_number: int,
    ) -> str:
        """
        Chuyển số cột thành tên cột Excel.

        1  -> A
        14 -> N
        26 -> Z
        27 -> AA
        52 -> AZ
        53 -> BA
        """

        if column_number < 1:
            raise ValueError(
                "column_number phải >= 1"
            )

        result = ""
        current = column_number

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