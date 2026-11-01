from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from modules.lark.data_manager import (
    LarkDataManager,
)


class LarkSourceRunner:
    """
    Đọc configs/lark_sources.json và chạy nhiều source:

    Sheet:
    - mode=range
    - mode=full_tab
    - mode=all_tabs

    Base:
    - download toàn bộ records
    - hỗ trợ view_id, filter, field_names, sort
    """

    def __init__(
        self,
        manager: LarkDataManager,
        project_root: str | Path,
        continue_on_error: bool = True,
    ) -> None:
        self.manager = manager

        self.project_root = Path(
            project_root
        ).resolve()

        self.continue_on_error = (
            continue_on_error
        )

        self.logger = logging.getLogger(
            self.__class__.__name__
        )

    def run_config(
        self,
        config_file: str | Path,
    ) -> dict[str, list[dict[str, Any]]]:
        """
        Chạy tất cả source trong config JSON.

        Returns:
            {
                "completed": [...],
                "failed": [...]
            }
        """

        config_path = self._resolve_path(
            config_file
        )

        config = self._load_json(
            config_path
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
                "lark_sources.sources phải là list"
            )

        enabled_sources = [
            source
            for source in sources
            if (
                isinstance(source, dict)
                and source.get(
                    "enabled",
                    True,
                )
            )
        ]

        completed: list[
            dict[str, Any]
        ] = []

        failed: list[
            dict[str, Any]
        ] = []

        print(
            "[LARK DATA] "
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

            source_type = str(
                source.get(
                    "type",
                    "",
                )
            ).strip().lower()

            print(
                "[LARK DATA] "
                f"Running {index}/"
                f"{len(enabled_sources)} "
                f"| {name} "
                f"| {source_type}"
            )

            try:
                output_files = (
                    self._run_source(
                        source
                    )
                )

                completed.append(
                    {
                        "name": name,
                        "type": source_type,
                        "files": [
                            str(path)
                            for path
                            in output_files
                        ],
                    }
                )

                for output_file in (
                    output_files
                ):
                    print(
                        "[LARK DATA] "
                        f"Completed | "
                        f"{name} | "
                        f"{output_file}"
                    )

            except Exception as error:
                self.logger.exception(
                    "Lark source failed | "
                    "name=%s",
                    name,
                )

                failed.append(
                    {
                        "name": name,
                        "type": source_type,
                        "error_type": (
                            type(error).__name__
                        ),
                        "error": str(
                            error
                        ),
                    }
                )

                print(
                    "[LARK DATA FAILED] "
                    f"{name} | "
                    f"{type(error).__name__}: "
                    f"{error}"
                )

                if not self.continue_on_error:
                    raise

        return {
            "completed": completed,
            "failed": failed,
        }

    def _run_source(
        self,
        source: dict[str, Any],
    ) -> list[Path]:
        """
        Chạy một Lark source theo type.
        """

        source_type = str(
            source.get(
                "type",
                "",
            )
        ).strip().lower()

        if source_type == "sheet":
            return self._run_sheet_source(
                source
            )

        if source_type == "base":
            return self._run_base_source(
                source
            )

        raise ValueError(
            "Unsupported Lark source type: "
            f"{source_type}"
        )

    def _run_sheet_source(
        self,
        source: dict[str, Any],
    ) -> list[Path]:
        """
        Chạy một Lark Sheet source.

        Supported modes:
        - full_tab
        - range
        - all_tabs
        """

        spreadsheet_token = (
            self._required(
                source,
                "spreadsheet_token",
            )
        )

        mode = str(
            source.get(
                "mode",
                "range",
            )
        ).strip().lower()

        # ====================================================
        # FULL TAB
        # ====================================================

        if mode == "full_tab":
            sheet_name = self._required(
                source,
                "sheet_name",
            )

            output_file = self._resolve_path(
                self._required(
                    source,
                    "output",
                )
            )

            result = (
                self.manager
                .download_full_sheet_tab(
                    spreadsheet_token=(
                        spreadsheet_token
                    ),
                    sheet_name=sheet_name,
                    output_file=output_file,
                )
            )

            return [
                result
            ]

        # ====================================================
        # ALL TABS
        # ====================================================

        if mode == "all_tabs":
            output_directory = (
                self._resolve_path(
                    self._required(
                        source,
                        "output_directory",
                    )
                )
            )

            max_columns = str(
                source.get(
                    "max_columns",
                    "ZZ",
                )
            ).strip()

            return (
                self.manager
                .download_all_sheet_tabs(
                    spreadsheet_token=(
                        spreadsheet_token
                    ),
                    output_directory=(
                        output_directory
                    ),
                    max_columns=max_columns,
                )
            )

        # ====================================================
        # SPECIFIC RANGE
        # ====================================================

        if mode == "range":
            range_a1 = self._required(
                source,
                "range",
            )

            output_file = self._resolve_path(
                self._required(
                    source,
                    "output",
                )
            )

            result = (
                self.manager
                .download_sheet_range(
                    spreadsheet_token=(
                        spreadsheet_token
                    ),
                    range_a1=range_a1,
                    output_file=output_file,
                )
            )

            return [
                result
            ]

        raise ValueError(
            "Unsupported Sheet mode: "
            f"{mode}"
        )

    def _run_base_source(
        self,
        source: dict[str, Any],
    ) -> list[Path]:
        """
        Chạy một Lark Base source.
        """

        app_token = self._required(
            source,
            "app_token",
        )

        table_id = self._required(
            source,
            "table_id",
        )

        output_file = self._resolve_path(
            self._required(
                source,
                "output",
            )
        )

        view_id = str(
            source.get(
                "view_id",
                "",
            )
        ).strip() or None

        field_names = source.get(
            "field_names"
        )

        if (
            field_names is not None
            and not isinstance(
                field_names,
                list,
            )
        ):
            raise ValueError(
                "field_names phải là list"
            )

        # [] được xem là không giới hạn field.
        if field_names == []:
            field_names = None

        filter_info = source.get(
            "filter"
        )

        if (
            filter_info is not None
            and not isinstance(
                filter_info,
                dict,
            )
        ):
            raise ValueError(
                "filter phải là object"
            )

        sort = source.get(
            "sort"
        )

        if (
            sort is not None
            and not isinstance(
                sort,
                list,
            )
        ):
            raise ValueError(
                "sort phải là list"
            )

        result = (
            self.manager
                .download_base_table(
                app_token=app_token,
                table_id=table_id,
                output_file=output_file,
                view_id=view_id,
                field_names=field_names,
                filter_info=filter_info,
                sort=sort,
            )
        )

        return [
            result
        ]

    def _resolve_path(
        self,
        value: str | Path,
    ) -> Path:
        """
        Resolve relative path theo project root.
        """

        path = Path(
            value
        )

        if path.is_absolute():
            return path.resolve()

        return (
            self.project_root
            / path
        ).resolve()

    @staticmethod
    def _load_json(
        path: Path,
    ) -> dict[str, Any]:
        """
        Load JSON với UTF-8 BOM support.
        """

        if not path.exists():
            raise FileNotFoundError(
                f"Không tìm thấy config: "
                f"{path}"
            )

        try:
            with path.open(
                "r",
                encoding="utf-8-sig",
            ) as file:
                data = json.load(
                    file
                )

        except json.JSONDecodeError as error:
            raise ValueError(
                "JSON không hợp lệ | "
                f"file={path} | "
                f"line={error.lineno} | "
                f"column={error.colno} | "
                f"error={error.msg}"
            ) from error

        if not isinstance(
            data,
            dict,
        ):
            raise ValueError(
                "Config phải là JSON object: "
                f"{path}"
            )

        return data

    @staticmethod
    def _required(
        source: dict[str, Any],
        key: str,
    ) -> str:
        """
        Lấy required string field từ source config.
        """

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
                f"Lark source '{source_name}' "
                f"thiếu field bắt buộc: {key}"
            )

        return value