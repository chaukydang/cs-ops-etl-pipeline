from __future__ import annotations

import csv
import json
import logging
import time
import uuid
from copy import deepcopy
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import requests
from requests import Response
from requests.exceptions import (
    ConnectionError,
    HTTPError,
    RequestException,
    Timeout,
)


class AeolusDownloadError(Exception):
    """Lỗi chung khi download dữ liệu từ Aeolus."""


class AeolusRowLimitError(AeolusDownloadError):
    """The export reached its row limit, so the file is incomplete."""


class AeolusUnauthorizedError(AeolusDownloadError):
    """Token hoặc session Dashboard không còn hợp lệ."""


class AeolusEmptyResponseError(AeolusDownloadError):
    """Dashboard trả về response rỗng."""


class AeolusInvalidResponseError(AeolusDownloadError):
    """Dashboard trả về response không hợp lệ."""


class AeolusDownloader:
    """Download CSV từ Dashboard bằng Open-Api-Token và cookies."""

    DEFAULT_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"
    AUTH_STATUS_CODES = (401, 403)
    RETRYABLE_STATUS_CODES = (408, 425, 429, 500, 502, 503, 504)

    def __init__(
        self,
        open_api_token: str,
        app_id: str | int,
        cookies: dict[str, str] | None = None,
        timeout: int = 300,
        max_retries: int = 2,
    ) -> None:
        self.open_api_token = str(open_api_token).strip()
        self.app_id = str(app_id).strip()
        self.cookies = cookies or {}
        self.timeout = timeout
        self.max_retries = max_retries

        if not self.open_api_token:
            raise ValueError("open_api_token không được để trống")
        if not self.app_id:
            raise ValueError("app_id không được để trống")

        self.session = requests.Session()
        self.session.headers.update(
            {
                "Accept": "*/*",
                "Content-Type": "application/json",
                "App-Id": self.app_id,
                "Open-Api-Token": self.open_api_token,
            }
        )
        if self.cookies:
            self.session.cookies.update(self.cookies)

        self.logger = logging.getLogger(self.__class__.__name__)

    def download_metric(
        self,
        config: dict[str, Any],
        window: tuple[datetime, datetime] | None = None,
        output_file: Path | None = None,
    ) -> Path:
        """Download one report.

        window:      explicit (start, end) instead of the rolling window from
                     the config; used for backfills.
        output_file: write here instead of the configured download directory.
        """
        self.validate_config(config)

        metric_name = str(config["metric_name"]).strip()
        endpoint = str(config["endpoint"]).strip()
        payload = deepcopy(config["payload"])

        if output_file is None:
            output_directory = self.get_output_directory(config)
            filename = self.build_filename(config, metric_name)
            output_file = output_directory / filename
        else:
            output_file = Path(output_file)
            output_file.parent.mkdir(parents=True, exist_ok=True)
            filename = output_file.name

        self.update_report_name(payload, filename)
        applied_window = self.apply_dynamic_date(payload, config, window)

        self.logger.info(
            "Starting Dashboard download | metric=%s | endpoint=%s",
            metric_name,
            endpoint,
        )

        response = self.post_with_retry(endpoint, payload)
        self.validate_response(response)
        self.save_response(response, output_file)

        row_count = self.count_csv_rows(output_file)
        file_size = output_file.stat().st_size

        # The export silently stops at its row limit; a truncated file must
        # never reach the database.
        limit = payload.get("downloadConfig", {}).get("limit")
        if limit and row_count >= int(limit):
            output_file.unlink(missing_ok=True)
            raise AeolusRowLimitError(
                f"{metric_name}: export hit the {limit} row limit; use a smaller date window"
            )

        if applied_window is not None:
            self.write_window_sidecar(output_file, metric_name, applied_window, row_count)

        self.logger.info(
            "Dashboard download completed | metric=%s | file=%s | rows=%s | bytes=%s",
            metric_name,
            output_file,
            row_count,
            file_size,
        )
        print(
            "[DashboardDOWNLOAD] "
            f"Completed | File={output_file} | Rows={row_count} | Bytes={file_size}"
        )
        return output_file

    @staticmethod
    def validate_config(config: dict[str, Any]) -> None:
        required = ("metric_name", "endpoint", "payload")
        missing = [key for key in required if key not in config]
        if missing:
            raise AeolusDownloadError(
                "Metric config thiếu key: " + ", ".join(missing)
            )
        if not str(config.get("endpoint", "")).strip():
            raise AeolusDownloadError("Metric endpoint đang trống")
        if not isinstance(config.get("payload"), dict):
            raise AeolusDownloadError("Metric payload phải là dictionary")

    @staticmethod
    def get_output_directory(config: dict[str, Any]) -> Path:
        directory = str(
            config.get("output", {}).get("directory", "downloads")
        ).strip()
        output_directory = Path(directory).resolve()
        output_directory.mkdir(parents=True, exist_ok=True)
        return output_directory

    @staticmethod
    def build_filename(config: dict[str, Any], metric_name: str) -> str:
        prefix = str(
            config.get("output", {}).get("filename_prefix", metric_name)
        ).strip()
        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        return f"{prefix}-{timestamp}.csv"

    @staticmethod
    def update_report_name(payload: dict[str, Any], filename: str) -> None:
        download_config = payload.setdefault("downloadConfig", {})
        download_config["reportName"] = filename
        download_config.setdefault("dataType", "csv")

    @staticmethod
    def write_window_sidecar(
        output_file: Path,
        metric_name: str,
        window: tuple[datetime, datetime],
        row_count: int,
    ) -> None:
        """Record which dates the file covers, so the loader replaces exactly that range."""
        meta = {
            "metric": metric_name,
            "date_from": window[0].date().isoformat(),
            "date_to": window[1].date().isoformat(),
            "rows": row_count,
            "downloaded_at": datetime.now().isoformat(timespec="seconds"),
        }
        Path(str(output_file) + ".meta.json").write_text(
            json.dumps(meta, indent=2), encoding="utf-8"
        )

    def apply_dynamic_date(
        self,
        payload: dict[str, Any],
        config: dict[str, Any],
        window: tuple[datetime, datetime] | None = None,
    ) -> tuple[datetime, datetime] | None:
        """
        Với weeks_back=5 và include_current_week=true:
        - Tìm Chủ nhật của tuần hiện tại.
        - Lùi 4 tuần, vì tuần hiện tại được tính là tuần 1.
        - End date là cuối ngày hiện tại.

        Ví dụ 27/10/2026:
        start=27/09/2026 00:00:00
        end=27/10/2026 23:59:59
        """
        dynamic_date = config.get("dynamic_date", {})
        if not dynamic_date.get("enabled", False):
            return None

        field_id = str(dynamic_date.get("field_id", "")).strip()
        if not field_id:
            raise AeolusDownloadError(
                "dynamic_date.enabled=true nhưng thiếu field_id"
            )

        weeks_back = int(dynamic_date.get("weeks_back", 5))
        include_current_week = bool(
            dynamic_date.get("include_current_week", True)
        )
        week_start = str(
            dynamic_date.get("week_start", "sunday")
        ).strip().lower()

        if window is not None:
            start_datetime, end_datetime = window
        else:
            start_datetime, end_datetime = self.calculate_date_range(
                weeks_back=weeks_back,
                include_current_week=include_current_week,
                week_start=week_start,
            )
        date_values = [
            start_datetime.strftime(self.DEFAULT_DATE_FORMAT),
            end_datetime.strftime(self.DEFAULT_DATE_FORMAT),
        ]

        query = payload.get("query") or {}
        schema = payload.get("schema") or {}
        if not isinstance(query, dict):
            raise AeolusDownloadError("payload.query phải là dictionary")
        if not isinstance(schema, dict):
            raise AeolusDownloadError("payload.schema phải là dictionary")

        query_where_list = query.get("whereList") or []
        schema_where_list = schema.get("whereList") or []
        if not isinstance(query_where_list, list):
            raise AeolusDownloadError("payload.query.whereList phải là list")
        if not isinstance(schema_where_list, list):
            raise AeolusDownloadError("payload.schema.whereList phải là list")

        updated_count = self.update_where_list(
            query_where_list,
            field_id,
            date_values,
        )
        updated_count += self.update_schema_where_list(
            schema_where_list,
            field_id,
            date_values,
        )

        if updated_count == 0:
            self.logger.warning(
                "Dynamic date field was not found in payload | field_id=%s",
                field_id,
            )
        else:
            self.logger.info(
                "Dynamic date applied | field_id=%s | start=%s | end=%s | updated=%s",
                field_id,
                date_values[0],
                date_values[1],
                updated_count,
            )

        return (start_datetime, end_datetime) if updated_count else None

    @staticmethod
    def calculate_date_range(
        weeks_back: int = 5,
        include_current_week: bool = True,
        week_start: str = "sunday",
        now: datetime | None = None,
    ) -> tuple[datetime, datetime]:
        if weeks_back < 1:
            raise AeolusDownloadError("weeks_back phải lớn hơn hoặc bằng 1")

        current = now or datetime.now()
        normalized_week_start = week_start.strip().lower()

        if normalized_week_start == "sunday":
            days_since_week_start = (current.weekday() + 1) % 7
        elif normalized_week_start == "monday":
            days_since_week_start = current.weekday()
        else:
            raise AeolusDownloadError(
                "week_start chỉ hỗ trợ 'sunday' hoặc 'monday'"
            )

        current_week_start = (
            current - timedelta(days=days_since_week_start)
        ).replace(hour=0, minute=0, second=0, microsecond=0)

        weeks_to_shift = (
            weeks_back - 1 if include_current_week else weeks_back
        )
        start_datetime = current_week_start - timedelta(weeks=weeks_to_shift)
        end_datetime = current.replace(
            hour=23,
            minute=59,
            second=59,
            microsecond=0,
        )
        return start_datetime, end_datetime

    @staticmethod
    def update_where_list(
        where_list: list[Any],
        field_id: str,
        date_values: list[str],
    ) -> int:
        updated = 0
        for condition in where_list:
            if not isinstance(condition, dict):
                continue
            if str(condition.get("id", "")) != field_id:
                continue
            condition["op"] = "between"
            condition["val"] = date_values.copy()
            condition.setdefault("option", {})["dateMode"] = "absolute"
            updated += 1
        return updated

    @staticmethod
    def update_schema_where_list(
        where_list: list[Any],
        field_id: str,
        date_values: list[str],
    ) -> int:
        updated = 0
        for condition in where_list:
            if not isinstance(condition, dict):
                continue
            if str(condition.get("id", "")) != field_id:
                continue
            filter_config = condition.setdefault("filter", {})
            filter_config["op"] = "between"
            filter_config["val"] = date_values.copy()
            filter_config.setdefault("option", {})["dateMode"] = "absolute"
            updated += 1
        return updated

    def post_with_retry(
        self,
        endpoint: str,
        payload: dict[str, Any],
    ) -> Response:
        last_error: Exception | None = None
        total_attempts = self.max_retries + 1

        for attempt in range(1, total_attempts + 1):
            self.update_request_headers()
            try:
                print(
                    "[DashboardDOWNLOAD] "
                    f"Request attempt={attempt}/{total_attempts}"
                )
                response = self.session.post(
                    endpoint,
                    json=payload,
                    timeout=self.timeout,
                )
                if response.status_code in self.AUTH_STATUS_CODES:
                    raise AeolusUnauthorizedError(
                        f"Dashboard trả về HTTP {response.status_code}. "
                        "Token hoặc session có thể đã hết hạn."
                    )
                if response.status_code in self.RETRYABLE_STATUS_CODES:
                    raise AeolusDownloadError(
                        f"Dashboard temporary error: HTTP {response.status_code}"
                    )
                response.raise_for_status()
                return response

            except AeolusUnauthorizedError:
                raise
            except (
                Timeout,
                ConnectionError,
                HTTPError,
                RequestException,
                AeolusDownloadError,
            ) as error:
                last_error = error
                self.logger.warning(
                    "Dashboard request failed | attempt=%s/%s | type=%s | error=%s",
                    attempt,
                    total_attempts,
                    type(error).__name__,
                    error,
                )
                if attempt >= total_attempts:
                    break
                wait_seconds = min(2**attempt, 10)
                print(
                    "[DashboardDOWNLOAD] "
                    f"Retrying after {wait_seconds}s..."
                )
                time.sleep(wait_seconds)

        raise AeolusDownloadError(
            f"Không download được dữ liệu sau {total_attempts} lần. "
            f"Last error={last_error}"
        )

    def update_request_headers(self) -> None:
        request_id = str(uuid.uuid4())
        request_timestamp = str(int(time.time() * 1000))
        self.session.headers.update(
            {
                "Request-Id": request_id,
                "X-Request-Id": request_id,
                "Request-Timestamp": request_timestamp,
                "Open-Api-Token": self.open_api_token,
                "App-Id": self.app_id,
            }
        )

    @staticmethod
    def validate_response(response: Response) -> None:
        if not response.content:
            raise AeolusEmptyResponseError("Dashboard trả về response rỗng")

        content_type = str(
            response.headers.get("Content-Type", "")
        ).lower()
        preview = response.content[:200].lower()

        if "application/json" in content_type:
            try:
                result = response.json()
            except ValueError as error:
                raise AeolusInvalidResponseError(
                    "Response được đánh dấu JSON nhưng không parse được"
                ) from error
            raise AeolusInvalidResponseError(
                f"Dashboard trả về JSON thay vì CSV: {result}"
            )

        if preview.startswith(b"<!doctype html") or preview.startswith(b"<html"):
            raise AeolusInvalidResponseError(
                "Dashboard trả về HTML thay vì CSV. "
                "Token hoặc endpoint có thể không hợp lệ."
            )

    @staticmethod
    def save_response(response: Response, output_file: Path) -> None:
        output_file.parent.mkdir(parents=True, exist_ok=True)
        temporary_file = output_file.with_suffix(output_file.suffix + ".part")
        try:
            temporary_file.write_bytes(response.content)
            if not temporary_file.exists() or temporary_file.stat().st_size == 0:
                raise AeolusEmptyResponseError("File tạm sau download bị rỗng")
            temporary_file.replace(output_file)
        finally:
            if temporary_file.exists():
                try:
                    temporary_file.unlink()
                except OSError:
                    pass

    @staticmethod
    def count_csv_rows(csv_file: Path) -> int:
        encodings = ("utf-8-sig", "utf-8", "latin-1")
        last_error: Exception | None = None

        for encoding in encodings:
            try:
                with csv_file.open("r", encoding=encoding, newline="") as file:
                    total_rows = sum(1 for _ in csv.reader(file))
                return max(total_rows - 1, 0)
            except (UnicodeDecodeError, csv.Error) as error:
                last_error = error

        raise AeolusInvalidResponseError(
            f"Không đọc được CSV vừa tải. Last error={last_error}"
        )

    def update_authentication(
        self,
        open_api_token: str,
        cookies: dict[str, str] | None = None,
    ) -> None:
        clean_token = str(open_api_token).strip()
        if not clean_token:
            raise ValueError("open_api_token mới đang trống")

        self.open_api_token = clean_token
        self.session.headers.update({"Open-Api-Token": clean_token})

        if cookies is not None:
            self.cookies = cookies
            self.session.cookies.clear()
            self.session.cookies.update(cookies)
