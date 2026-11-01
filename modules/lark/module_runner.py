from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from modules.core.env_loader import get_required_env
from modules.lark.data_client import (
    LarkApiClient,
    LarkBaseClient,
    LarkSheetClient,
)
from modules.lark.download_raw import download_raw_source
from modules.lark.transform_raw import (
    BACKLOG_COLUMN_COUNT,
    PRODUCTIVITY_COLUMN_COUNT,
    read_raw_csv,
    transform_backlog,
    transform_productivity,
    write_output_csv,
)


class LarkModuleRunner:
    def __init__(
        self,
        project_root: str | Path,
    ) -> None:
        self.project_root = Path(
            project_root
        ).resolve()

        self.settings_file = (
            self.project_root
            / "configs"
            / "lark"
            / "settings.json"
        )

        self.settings = self._load_json(
            self.settings_file
        )

        self.logger = logging.getLogger(
            self.__class__.__name__
        )

        self._sheet_client: (
            LarkSheetClient | None
        ) = None

        self._base_client: (
            LarkBaseClient | None
        ) = None

    def run(
        self,
        source_type: str | None = None,
        source_name: str | None = None,
    ) -> dict[str, list[dict[str, Any]]]:
        sources = self._discover_sources()

        if source_type:
            requested_type = (
                source_type
                .strip()
                .lower()
            )

            sources = [
                source
                for source in sources
                if str(
                    source.get(
                        "type",
                        "",
                    )
                ).strip().lower()
                == requested_type
            ]

        if source_name:
            requested_name = (
                source_name.strip()
            )

            sources = [
                source
                for source in sources
                if str(
                    source.get(
                        "name",
                        "",
                    )
                ).strip()
                == requested_name
            ]

        completed: list[
            dict[str, Any]
        ] = []

        failed: list[
            dict[str, Any]
        ] = []

        skipped: list[
            dict[str, Any]
        ] = []

        statuses: dict[
            str,
            str,
        ] = {}

        print(
            "[LARK MODULE] "
            f"Enabled sources={len(sources)}"
        )

        for index, source in enumerate(
            sources,
            start=1,
        ):
            name = str(
                source.get(
                    "name",
                    f"source_{index}",
                )
            ).strip()

            source_kind = str(
                source.get(
                    "type",
                    "",
                )
            ).strip().lower()

            dependencies = source.get(
                "depends_on",
                [],
            )

            if not isinstance(
                dependencies,
                list,
            ):
                raise ValueError(
                    f"depends_on của source "
                    f"'{name}' phải là list"
                )

            dependency_failed = any(
                statuses.get(
                    str(dependency)
                )
                in {
                    "failed",
                    "skipped",
                }
                for dependency in dependencies
            )

            if dependency_failed:
                statuses[name] = "skipped"

                skipped.append(
                    {
                        "name": name,
                        "type": source_kind,
                        "reason": (
                            "dependency failed"
                        ),
                    }
                )

                print(
                    "[LARK SKIPPED] "
                    f"{name} | "
                    "dependency failed"
                )

                continue

            print(
                "[LARK MODULE] "
                f"Running {index}/"
                f"{len(sources)} | "
                f"{name} | "
                f"{source_kind}"
            )

            try:
                output_file = (
                    self._run_source(
                        source
                    )
                )

                statuses[name] = (
                    "completed"
                )

                completed.append(
                    {
                        "name": name,
                        "type": source_kind,
                        "output": str(
                            output_file
                        ),
                    }
                )

                print(
                    "[LARK COMPLETED] "
                    f"{name} | "
                    f"{output_file}"
                )

            except Exception as error:
                statuses[name] = "failed"

                failed.append(
                    {
                        "name": name,
                        "type": source_kind,
                        "error_type": (
                            type(error).__name__
                        ),
                        "error": str(error),
                    }
                )

                self.logger.exception(
                    "Lark source failed | "
                    "name=%s",
                    name,
                )

                print(
                    "[LARK FAILED] "
                    f"{name} | "
                    f"{type(error).__name__}: "
                    f"{error}"
                )

                continue_on_error = bool(
                    self.settings.get(
                        "continue_on_error",
                        True,
                    )
                )

                if not continue_on_error:
                    raise

        print(
            "\n"
            "================================"
        )

        print(
            "LARK MODULE SUMMARY"
        )

        print(
            "================================"
        )

        print(
            f"Completed: {len(completed)}"
        )

        print(
            f"Failed: {len(failed)}"
        )

        print(
            f"Skipped: {len(skipped)}"
        )

        for item in completed:
            print(
                "  [OK] "
                f"{item['name']} "
                f"-> {item['output']}"
            )

        for item in failed:
            print(
                "  [FAILED] "
                f"{item['name']} | "
                f"{item['error_type']} | "
                f"{item['error']}"
            )

        for item in skipped:
            print(
                "  [SKIPPED] "
                f"{item['name']} | "
                f"{item['reason']}"
            )

        print(
            "================================"
        )

        return {
            "completed": completed,
            "failed": failed,
            "skipped": skipped,
        }

    def _run_source(
        self,
        source: dict[str, Any],
    ) -> Path:
        source_kind = str(
            source.get(
                "type",
                "",
            )
        ).strip().lower()

        if source_kind == "sheet_raw":
            prepared_source = (
                self._prepare_sheet_source(
                    source
                )
            )

            result = download_raw_source(
                client=(
                    self._get_sheet_client()
                ),
                source=prepared_source,
            )

            return Path(
                str(
                    result["output"]
                )
            ).resolve()

        if source_kind == "base":
            return self._download_base(
                source
            )

        if source_kind == "transform":
            return self._run_transform(
                source
            )

        raise ValueError(
            "Unsupported Lark source type: "
            f"{source_kind}"
        )

    def _prepare_sheet_source(
        self,
        source: dict[str, Any],
    ) -> dict[str, Any]:
        prepared_source = dict(
            source
        )

        prepared_source["output"] = str(
            self._resolve_path(
                self._required(
                    source,
                    "output",
                )
            )
        )

        return prepared_source

    def _get_sheet_client(
        self,
    ) -> LarkSheetClient:
        if self._sheet_client is None:
            api = LarkApiClient(
                app_id=get_required_env(
                    "LARK_SHEET_APP_ID"
                ),
                app_secret=(
                    get_required_env(
                        "LARK_SHEET_APP_SECRET"
                    )
                ),
                timeout=120,
            )

            self._sheet_client = (
                LarkSheetClient(api)
            )

        return self._sheet_client

    def _get_base_client(
        self,
    ) -> LarkBaseClient:
        if self._base_client is None:
            api = LarkApiClient(
                app_id=get_required_env(
                    "LARK_BASE_APP_ID"
                ),
                app_secret=(
                    get_required_env(
                        "LARK_BASE_APP_SECRET"
                    )
                ),
                timeout=120,
            )

            self._base_client = (
                LarkBaseClient(api)
            )

        return self._base_client

    def _download_base(
        self,
        source: dict[str, Any],
    ) -> Path:
        output_file = self._resolve_path(
            self._required(
                source,
                "output",
            )
        )

        field_names = source.get(
            "field_names"
        )

        if field_names == []:
            field_names = None

        if (
            field_names is not None
            and not isinstance(
                field_names,
                list,
            )
        ):
            raise ValueError(
                "field_names của Lark Base "
                "phải là list"
            )

        view_id = str(
            source.get(
                "view_id",
                "",
            )
        ).strip() or None

        return (
            self._get_base_client()
            .export_records_csv(
                app_token=self._required(
                    source,
                    "app_token",
                ),
                table_id=self._required(
                    source,
                    "table_id",
                ),
                output_file=output_file,
                view_id=view_id,
                field_names=field_names,
                filter_info=source.get(
                    "filter"
                ),
                sort=source.get(
                    "sort"
                ),
                include_record_id=bool(
                    source.get(
                        "include_record_id",
                        False,
                    )
                ),
            )
        )

    def _run_transform(
        self,
        source: dict[str, Any],
    ) -> Path:
        transformer_name = (
            self._required(
                source,
                "transformer",
            )
            .strip()
            .lower()
        )

        input_file = self._resolve_path(
            self._required(
                source,
                "input",
            )
        )

        output_file = self._resolve_path(
            self._required(
                source,
                "output",
            )
        )

        if transformer_name == "productivity":
            dataframe = read_raw_csv(
                input_file,
                PRODUCTIVITY_COLUMN_COUNT,
            )

            result = (
                transform_productivity(
                    dataframe
                )
            )

        elif transformer_name == "backlog":
            dataframe = read_raw_csv(
                input_file,
                BACKLOG_COLUMN_COUNT,
            )

            result = transform_backlog(
                dataframe
            )

        else:
            raise ValueError(
                "Transformer không hỗ trợ: "
                f"{transformer_name}"
            )

        return write_output_csv(
            result,
            output_file,
        )

    def _discover_sources(
        self,
    ) -> list[dict[str, Any]]:
        directories = self.settings.get(
            "directories",
            {},
        )

        if not isinstance(
            directories,
            dict,
        ):
            raise ValueError(
                "directories trong "
                "settings.json phải là object"
            )

        sources: list[
            dict[str, Any]
        ] = []

        for relative_directory in (
            directories.values()
        ):
            directory = self._resolve_path(
                str(
                    relative_directory
                )
            )

            if not directory.exists():
                self.logger.warning(
                    "Config directory "
                    "không tồn tại: %s",
                    directory,
                )
                continue

            for config_file in sorted(
                directory.glob(
                    "*.json"
                )
            ):
                source = (
                    self._load_json(
                        config_file
                    )
                )

                if source.get(
                    "enabled",
                    True,
                ):
                    source[
                        "__config_file"
                    ] = str(
                        config_file
                    )

                    sources.append(
                        source
                    )

        return sorted(
            sources,
            key=lambda item: int(
                item.get(
                    "run_order",
                    999,
                )
            ),
        )

    def _resolve_path(
        self,
        value: str,
    ) -> Path:
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
                "Config phải là "
                f"JSON object: {path}"
            )

        return data

    @staticmethod
    def _required(
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
                f"thiếu field bắt buộc: "
                f"{key}"
            )

        return value