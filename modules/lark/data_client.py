from __future__ import annotations

import csv
import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote
from zoneinfo import ZoneInfo

import requests
from requests import Response
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


class LarkApiError(Exception):
    """Lỗi chung khi gọi Lark Open API."""


class LarkAuthenticationError(LarkApiError):
    """Không lấy được hoặc refresh được tenant_access_token."""


class LarkResponseError(LarkApiError):
    """Lark trả response không hợp lệ."""


class LarkApiClient:
    """HTTP client dùng chung cho Lark Sheets và Lark Base."""

    def __init__(
        self,
        app_id: str,
        app_secret: str,
        base_url: str = "https://open.larksuite.com/open-apis",
        timeout: int = 120,
        max_retries: int = 3,
    ) -> None:
        self.app_id = str(app_id).strip()
        self.app_secret = str(app_secret).strip()
        self.base_url = str(base_url).rstrip("/")
        self.timeout = int(timeout)

        if not self.app_id:
            raise ValueError("app_id không được để trống")
        if not self.app_secret:
            raise ValueError("app_secret không được để trống")

        self._tenant_access_token = ""
        self._token_expires_at = 0.0
        self.logger = logging.getLogger(self.__class__.__name__)

        retry = Retry(
            total=max_retries,
            connect=max_retries,
            read=max_retries,
            status=max_retries,
            backoff_factor=1,
            status_forcelist=(408, 425, 429, 500, 502, 503, 504),
            allowed_methods=frozenset(("GET", "POST")),
            raise_on_status=False,
        )

        adapter = HTTPAdapter(max_retries=retry)
        self.session = requests.Session()
        self.session.mount("https://", adapter)
        self.session.headers.update(
            {
                "Accept": "application/json",
                "Content-Type": "application/json; charset=utf-8",
            }
        )

    def get_tenant_access_token(self, force_refresh: bool = False) -> str:
        now = time.time()

        if (
            not force_refresh
            and self._tenant_access_token
            and now < self._token_expires_at - 120
        ):
            return self._tenant_access_token

        response = self.session.post(
            f"{self.base_url}/auth/v3/tenant_access_token/internal",
            json={
                "app_id": self.app_id,
                "app_secret": self.app_secret,
            },
            timeout=self.timeout,
        )

        try:
            response.raise_for_status()
        except requests.HTTPError as error:
            raise LarkAuthenticationError(
                f"Get tenant_access_token HTTP {response.status_code}: "
                f"{response.text[:1000]}"
            ) from error

        try:
            body = response.json()
        except ValueError as error:
            raise LarkAuthenticationError(
                "Get tenant_access_token không trả JSON"
            ) from error

        if int(body.get("code", -1)) != 0:
            raise LarkAuthenticationError(
                f"Không lấy được tenant_access_token: {body}"
            )

        token = str(body.get("tenant_access_token", "")).strip()
        if not token:
            raise LarkAuthenticationError("Lark không trả tenant_access_token")

        self._tenant_access_token = token
        self._token_expires_at = now + int(body.get("expire", 7200))
        return token

    def request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Gọi API JSON. Hỗ trợ cả json_body và json để tương thích code cũ."""

        request_json = json_body if json_body is not None else json

        for attempt in (1, 2):
            token = self.get_tenant_access_token(force_refresh=attempt == 2)

            response = self.session.request(
                method=method,
                url=f"{self.base_url}/{path.lstrip('/')}",
                headers={"Authorization": f"Bearer {token}"},
                params=params,
                json=request_json,
                timeout=self.timeout,
            )

            if response.status_code in (401, 403) and attempt == 1:
                continue

            self._raise_for_response(response)

            try:
                body = response.json()
            except ValueError as error:
                raise LarkResponseError(
                    f"Expected JSON | path={path} | preview={response.text[:500]}"
                ) from error

            if int(body.get("code", -1)) != 0:
                raise LarkResponseError(
                    f"Lark API error | path={path} | response={body}"
                )

            return body

        raise LarkAuthenticationError("Lark authentication failed after refresh")

    @staticmethod
    def _raise_for_response(response: Response) -> None:
        try:
            response.raise_for_status()
        except requests.HTTPError as error:
            raise LarkResponseError(
                f"HTTP {response.status_code}: {response.text[:1000]}"
            ) from error


class LarkSheetClient:
    """Đọc Lark Sheets và export range thành CSV."""

    def __init__(self, api: LarkApiClient) -> None:
        self.api = api

    def get_spreadsheet(self, spreadsheet_token: str) -> dict[str, Any]:
        body = self.api.request(
            "GET",
            f"sheets/v3/spreadsheets/{spreadsheet_token}",
        )
        return dict(body.get("data", {}).get("spreadsheet", {}) or {})

    def get_sheets(self, spreadsheet_token: str) -> list[dict[str, Any]]:
        body = self.api.request(
            "GET",
            f"sheets/v3/spreadsheets/{spreadsheet_token}/sheets/query",
        )
        return list(body.get("data", {}).get("sheets", []) or [])

    def get_values(
        self,
        spreadsheet_token: str,
        range_a1: str,
        value_render_option: str = "FormattedValue",
        date_time_render_option: str = "FormattedString",
    ) -> list[list[Any]]:
        encoded_range = quote(range_a1, safe="!:$")
        body = self.api.request(
            "GET",
            f"sheets/v2/spreadsheets/{spreadsheet_token}/values/{encoded_range}",
            params={
                "valueRenderOption": value_render_option,
                "dateTimeRenderOption": date_time_render_option,
            },
        )
        values = body.get("data", {}).get("valueRange", {}).get("values", [])
        return list(values or [])

    def export_range_csv(
        self,
        spreadsheet_token: str,
        range_a1: str,
        output_file: str | Path,
    ) -> Path:
        rows = self.get_values(spreadsheet_token, range_a1)
        output_path = Path(output_file).resolve()
        output_path.parent.mkdir(parents=True, exist_ok=True)

        with output_path.open("w", encoding="utf-8-sig", newline="") as file:
            writer = csv.writer(file, lineterminator="\n")
            for row in rows:
                writer.writerow([self._normalize_cell(value) for value in row])

        return output_path

    @classmethod
    def _normalize_cell(cls, value: Any) -> Any:
        if value is None:
            return ""
        if isinstance(value, (str, int, float, bool)):
            return value
        if isinstance(value, list):
            values = [cls._normalize_cell(item) for item in value]
            return " | ".join(str(item).strip() for item in values if str(item).strip())
        if isinstance(value, dict):
            if "value" in value:
                return cls._normalize_cell(value.get("value"))
            for key in ("text", "name", "email"):
                if value.get(key) not in (None, ""):
                    return value[key]
            link = value.get("link") or value.get("url")
            if link:
                text = str(link)
                return text[7:] if text.lower().startswith("mailto:") else text
            return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
        return str(value)


SYSTEM_EXPORT_FIELD_ORDER = [
    "index",
    "Ecode",
    "Date",
    "shift_code",
    "Date_convert",
    "Date Of Month",
    "FullName",
    "Email",
    "Role",
    "Task",
    "Function",
    "LineManager",
    "LineManagerID",
    "Shift No",
    "Working Hour",
    "Online",
    "Floor",
    "Shinkage",
    "Tier",
    "WeekNum",
    "Leave Type",
    "Schedule Hour",
    "StartHour",
    "EndHour",
    "Tier-Labelling",
    "Lunch Hour",
    "Shinkage Point",
    "New ShinkagePoint",
    "New Leave Type",
    "Month-Year",
    "LOB",
    "Tenure of Task",
    "Task Tenure Group",
    "Batch & Production Date",
    "Production Date",
    "Ordered HC",
    "Emp_Type",
    "Batch",
    "Production Tenure",
]


class LarkBaseClient:
    """Đọc Lark Base và xuất CSV gần giống file export từ giao diện system."""

    def __init__(self, api: LarkApiClient) -> None:
        self.api = api
        self.logger = logging.getLogger(self.__class__.__name__)

    def list_tables(self, app_token: str) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        page_token = ""

        while True:
            params: dict[str, Any] = {"page_size": 100}
            if page_token:
                params["page_token"] = page_token

            body = self.api.request(
                "GET",
                f"bitable/v1/apps/{app_token}/tables",
                params=params,
            )
            data = body.get("data", {}) or {}
            items.extend(data.get("items", []) or [])

            if not data.get("has_more"):
                break
            page_token = str(data.get("page_token", "")).strip()

        return items

    def list_fields(
        self,
        app_token: str,
        table_id: str,
    ) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        page_token = ""

        while True:
            params: dict[str, Any] = {"page_size": 100}
            if page_token:
                params["page_token"] = page_token

            body = self.api.request(
                "GET",
                f"bitable/v1/apps/{app_token}/tables/{table_id}/fields",
                params=params,
            )
            data = body.get("data", {}) or {}
            items.extend(data.get("items", []) or [])

            if not data.get("has_more"):
                break
            page_token = str(data.get("page_token", "")).strip()

        return items

    def search_records(
        self,
        app_token: str,
        table_id: str,
        *,
        view_id: str | None = None,
        filter_info: dict[str, Any] | None = None,
        field_names: list[str] | None = None,
        sort: list[dict[str, Any]] | None = None,
        page_size: int = 500,
    ) -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []
        page_token = ""
        page_number = 0
        page_size = min(max(int(page_size), 1), 500)

        while True:
            page_number += 1
            params: dict[str, Any] = {
                "page_size": page_size,
                "user_id_type": "open_id",
            }
            if page_token:
                params["page_token"] = page_token

            payload: dict[str, Any] = {}
            if view_id:
                payload["view_id"] = view_id
            if field_names:
                payload["field_names"] = field_names
            if filter_info:
                payload["filter"] = filter_info
            if sort:
                payload["sort"] = sort

            body = self.api.request(
                "POST",
                f"bitable/v1/apps/{app_token}/tables/{table_id}/records/search",
                params=params,
                json_body=payload,
            )

            data = body.get("data", {}) or {}
            page_records = list(data.get("items", []) or [])
            records.extend(page_records)

            print(
                "[LARK BASE] Page downloaded | "
                f"page={page_number} | page_records={len(page_records)} | "
                f"total_records={len(records)}"
            )

            if not data.get("has_more"):
                break

            next_page_token = str(data.get("page_token", "")).strip()
            if not next_page_token or next_page_token == page_token:
                raise LarkResponseError(
                    "Lark Base pagination không trả page_token mới | "
                    f"page={page_number}"
                )
            page_token = next_page_token

        return records

    def export_records_csv(
        self,
        app_token: str,
        table_id: str,
        output_file: str | Path,
        *,
        view_id: str | None = None,
        filter_info: dict[str, Any] | None = None,
        field_names: list[str] | None = None,
        sort: list[dict[str, Any]] | None = None,
        include_record_id: bool = False,
    ) -> Path:
        """
        Xuất Base theo format system:
        - Không thêm record_id mặc định.
        - Giữ đúng thứ tự field_names.
        - Flatten typed values {type, value}.
        - Chuyển timestamp Date/Date_convert/Production Date.
        - Phân trang đến khi has_more=false.
        """

        export_fields = list(field_names or SYSTEM_EXPORT_FIELD_ORDER)

        records = self.search_records(
            app_token=app_token,
            table_id=table_id,
            view_id=view_id,
            filter_info=filter_info,
            field_names=export_fields,
            sort=sort,
            page_size=500,
        )

        if not records:
            raise LarkResponseError(
                f"Lark Base không trả records | app={app_token} | table={table_id}"
            )

        headers = (["record_id"] if include_record_id else []) + export_fields
        output_path = Path(output_file).resolve()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = output_path.with_suffix(output_path.suffix + ".part")

        try:
            with temporary_path.open(
                "w",
                encoding="utf-8-sig",
                newline="",
            ) as file:
                writer = csv.DictWriter(
                    file,
                    fieldnames=headers,
                    extrasaction="ignore",
                    lineterminator="\n",
                )
                writer.writeheader()

                for record in records:
                    fields = record.get("fields", {}) or {}
                    row: dict[str, Any] = {}

                    if include_record_id:
                        row["record_id"] = record.get("record_id", "")

                    for field_name in export_fields:
                        row[field_name] = self._normalize_base_field(
                            field_name,
                            fields.get(field_name),
                        )

                    writer.writerow(row)

            if temporary_path.stat().st_size == 0:
                raise LarkResponseError("Lark Base CSV tạm bị rỗng")

            temporary_path.replace(output_path)

        finally:
            temporary_path.unlink(missing_ok=True)

        print(
            "[LARK BASE] Completed | "
            f"records={len(records)} | columns={len(headers)} | "
            f"bytes={output_path.stat().st_size} | file={output_path}"
        )
        return output_path

    @classmethod
    def _normalize_base_field(cls, field_name: str, value: Any) -> Any:
        value = cls._unwrap_base_value(value)

        if value in (None, ""):
            return ""

        if field_name == "Date":
            return cls._format_lark_timestamp(value, "%Y/%m/%d %H:%M")

        if field_name in {"Date_convert", "Production Date"}:
            return cls._format_lark_timestamp(value, "%Y-%m-%d")

        if field_name == "Ecode":
            try:
                number = float(str(value).replace(",", "").strip())
                return f"{number:.6e}"
            except (TypeError, ValueError):
                return value

        if isinstance(value, list):
            return " | ".join(
                str(cls._unwrap_base_value(item)).strip()
                for item in value
                if str(cls._unwrap_base_value(item)).strip()
            )

        if isinstance(value, dict):
            return json.dumps(value, ensure_ascii=False, separators=(",", ":"))

        return value

    @classmethod
    def _unwrap_base_value(cls, value: Any) -> Any:
        if value is None:
            return ""

        if isinstance(value, (str, int, float, bool)):
            return value

        if isinstance(value, list):
            values = [cls._unwrap_base_value(item) for item in value]
            values = [item for item in values if item not in (None, "")]
            if not values:
                return ""
            return values[0] if len(values) == 1 else values

        if not isinstance(value, dict):
            return str(value)

        # Formula, lookup, rollup fields often return a typed wrapper.
        if "value" in value:
            return cls._unwrap_base_value(value.get("value"))

        for key in ("text", "name", "email", "full_name"):
            if value.get(key) not in (None, ""):
                return value[key]

        link = value.get("link") or value.get("url")
        if link:
            text = str(link)
            return text[7:] if text.lower().startswith("mailto:") else text

        if "timestamp" in value:
            return value.get("timestamp")

        return value

    @staticmethod
    def _format_lark_timestamp(value: Any, output_format: str) -> Any:
        try:
            numeric = float(str(value).strip())
        except (TypeError, ValueError):
            return value

        if abs(numeric) > 10_000_000_000:
            numeric /= 1000

        try:
            date_value = datetime.fromtimestamp(
                numeric,
                tz=timezone.utc,
            ).astimezone(ZoneInfo("Asia/Ho_Chi_Minh"))
            return date_value.strftime(output_format)
        except (OverflowError, OSError, ValueError):
            return value
