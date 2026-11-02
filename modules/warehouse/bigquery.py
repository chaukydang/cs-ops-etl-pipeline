"""Load the pipeline's CSV files into BigQuery.

Same behaviour as the PostgreSQL loader, adapted to BigQuery:

- raw columns are STRING (typing happens in dbt staging), plus metadata columns
  `_source_file`, `_source_row_number`, `_row_hash`, `_loaded_at`;
- incremental tables are partitioned by `_partition_date` (parsed from the
  source's date column) and optionally clustered, so replacing a date window
  only touches those partitions;
- a window is replaced with DELETE + INSERT inside one multi-statement
  transaction, after the same guards as PostgreSQL (empty file, invalid dates,
  rows outside the window, suspicious shrink);
- replace-mode sources (Lark sheets) are rebuilt with CREATE OR REPLACE.

Cost controls: `BQ_MAX_BYTES_BILLED` caps every query, and the DELETE is dry-run
first so the bytes it would scan are reported.
"""

from __future__ import annotations

import csv
import logging
import os
import tempfile
import uuid
from pathlib import Path

from google.api_core.exceptions import NotFound
from google.cloud import bigquery

from modules.database.csv_loader import CsvDatabaseLoader

LOGGER = logging.getLogger("BigQueryLoader")

META_COLUMNS = ["_source_file", "_source_row_number", "_row_hash"]
PARTITION_COLUMN = "_partition_date"


def parse_expr(column: str) -> str:
    """ISO date (or datetime) text -> DATE, NULL when it is not one."""
    return f"SAFE.PARSE_DATE('%Y-%m-%d', SUBSTR(`{column}`, 1, 10))"


class BigQueryLoader:
    def __init__(self, client, project: str, dataset: str, project_root, max_bytes_billed: int | None = None):
        self.client = client
        self.project = project
        self.dataset = dataset
        self.max_bytes_billed = max_bytes_billed
        # reuse the CSV helpers (profiling, header normalisation, window resolution)
        self._csv = CsvDatabaseLoader(None, project_root, "unused")

    # ---- naming -------------------------------------------------------
    def table_id(self, name: str) -> str:
        return f"{self.project}.{self.dataset}.{name}"

    def _quoted(self, name: str) -> str:
        return f"`{self.table_id(name)}`"

    # ---- queries ------------------------------------------------------
    def _query(self, sql: str, dry_run: bool = False):
        config = bigquery.QueryJobConfig(dry_run=dry_run, use_query_cache=False)
        if self.max_bytes_billed and not dry_run:
            config.maximum_bytes_billed = self.max_bytes_billed
        job = self.client.query(sql, job_config=config)
        if dry_run:
            return job
        return list(job.result())

    # ---- schema -------------------------------------------------------
    def _schema(self, headers: list[str]) -> list[bigquery.SchemaField]:
        fields = [bigquery.SchemaField(name, "STRING") for name in headers]
        fields += [
            bigquery.SchemaField("_source_file", "STRING"),
            bigquery.SchemaField("_source_row_number", "INT64"),
            bigquery.SchemaField("_row_hash", "STRING"),
            bigquery.SchemaField("_loaded_at", "TIMESTAMP"),
        ]
        return fields

    def _table_columns(self, name: str) -> list[str] | None:
        try:
            table = self.client.get_table(self.table_id(name))
        except NotFound:
            return None
        skip = set(META_COLUMNS) | {"_loaded_at", PARTITION_COLUMN}
        return [f.name for f in table.schema if f.name not in skip]

    def initialize_table(self, source, file_path=None) -> dict:
        path = Path(file_path).resolve() if file_path else self._csv.find_latest_file(source)
        profile = self._csv.profile_csv(path)

        existing = self._table_columns(source.table_name)
        if existing is not None:
            self._csv.validate_columns(source, profile.database_headers, existing)
            return {"status": "already_exists", "source": source.name, "table": source.table_name}

        table = bigquery.Table(self.table_id(source.table_name), schema=self._schema(profile.database_headers))
        if source.load_mode == "incremental":
            table.schema = list(table.schema) + [bigquery.SchemaField(PARTITION_COLUMN, "DATE")]
            table.time_partitioning = bigquery.TimePartitioning(
                type_=bigquery.TimePartitioningType.DAY, field=PARTITION_COLUMN
            )
            if source.cluster_by:
                table.clustering_fields = list(source.cluster_by)[:4]
        self.client.create_table(table)
        return {"status": "created", "source": source.name, "table": source.table_name,
                "columns": len(profile.database_headers)}

    # ---- staging file -------------------------------------------------
    def _write_staging_csv(self, source, profile, target: Path) -> None:
        """Rewrite the CSV with BigQuery-safe headers and the metadata columns."""
        headers = profile.database_headers + META_COLUMNS
        with profile.file_path.open("r", encoding="utf-8-sig", newline="") as src, \
                target.open("w", encoding="utf-8", newline="") as out:
            reader = csv.reader(src)
            next(reader, None)
            writer = csv.writer(out)
            writer.writerow(headers)
            for number, row in enumerate(reader, start=2):
                values = self._csv.normalize_row(row, len(profile.database_headers), source, number)
                writer.writerow(values + [profile.file_path.name, number, self._csv.hash_row(values)])

    def _load_staging(self, source, profile) -> str:
        staging = f"_stg_{source.table_name}_{uuid.uuid4().hex[:8]}"
        fields = [bigquery.SchemaField(n, "STRING") for n in profile.database_headers]
        fields += [
            bigquery.SchemaField("_source_file", "STRING"),
            bigquery.SchemaField("_source_row_number", "INT64"),
            bigquery.SchemaField("_row_hash", "STRING"),
        ]
        config = bigquery.LoadJobConfig(
            source_format=bigquery.SourceFormat.CSV,
            skip_leading_rows=1,
            allow_quoted_newlines=True,
            schema=fields,
            write_disposition=bigquery.WriteDisposition.WRITE_TRUNCATE,
        )
        with tempfile.TemporaryDirectory() as folder:
            staged = Path(folder) / "staging.csv"
            self._write_staging_csv(source, profile, staged)
            with staged.open("rb") as handle:
                job = self.client.load_table_from_file(handle, self.table_id(staging), job_config=config)
                job.result()
        return staging

    # ---- load ---------------------------------------------------------
    def load_table(self, source, file_path=None, window=None) -> dict:
        if source.load_mode not in ("replace", "incremental"):
            raise ValueError(f"{source.name}: unknown load_mode {source.load_mode!r}")
        if source.load_mode == "incremental" and not source.date_column:
            raise ValueError(f"{source.name}: incremental load needs date_column")

        path = Path(file_path).resolve() if file_path else self._csv.find_latest_file(source)
        profile = self._csv.profile_csv(path)

        existing = self._table_columns(source.table_name)
        if existing is None:
            raise RuntimeError(f"Table {self.table_id(source.table_name)} does not exist. Run init first.")
        self._csv.validate_columns(source, profile.database_headers, existing)

        if source.load_mode == "incremental" and profile.row_count == 0:
            raise ValueError(f"{source.name}: CSV has no rows; refusing to clear the date window")
        if source.load_mode == "incremental" and source.date_column not in profile.database_headers:
            raise ValueError(f"{source.name}: date_column {source.date_column!r} is not in the CSV")

        staging = self._load_staging(source, profile)
        try:
            rows = self._query(f"SELECT COUNT(*) AS n FROM {self._quoted(staging)}")[0]["n"]
            if rows != profile.row_count:
                raise RuntimeError(f"Staging count mismatch for {source.name}: CSV={profile.row_count}, BigQuery={rows}")

            if source.load_mode == "incremental":
                stats = self._replace_window(source, profile, staging, window)
            else:
                stats = self._replace_table(source, profile, staging)
        finally:
            self.client.delete_table(self.table_id(staging), not_found_ok=True)

        return {"status": "loaded", "source": source.name, "table": source.table_name,
                "file": str(path), "rows": profile.row_count, "mode": source.load_mode, **stats}

    def _columns_sql(self, profile) -> str:
        return ", ".join(f"`{c}`" for c in profile.database_headers + META_COLUMNS)

    def _replace_table(self, source, profile, staging) -> dict:
        columns = self._columns_sql(profile)
        self._query(
            f"CREATE OR REPLACE TABLE {self._quoted(source.table_name)} AS "
            f"SELECT {columns}, CURRENT_TIMESTAMP() AS `_loaded_at` FROM {self._quoted(staging)}"
        )
        return {"inserted": profile.row_count}

    def _replace_window(self, source, profile, staging, window) -> dict:
        parsed = parse_expr(source.date_column)
        stg = self._quoted(staging)
        target = self._quoted(source.table_name)

        check = self._query(
            f"SELECT COUNTIF({parsed} IS NULL) AS invalid, MIN({parsed}) AS dmin, MAX({parsed}) AS dmax FROM {stg}"
        )[0]
        if check["invalid"]:
            raise ValueError(f"{source.name}: {check['invalid']} rows have no valid date in {source.date_column}")

        date_from, date_to = self._csv.resolve_window(
            profile.file_path, window, check["dmin"].isoformat(), check["dmax"].isoformat()
        )
        if check["dmin"] < date_from or check["dmax"] > date_to:
            raise ValueError(
                f"{source.name}: rows fall outside the downloaded window {date_from}..{date_to} "
                f"(CSV has {check['dmin']}..{check['dmax']})"
            )

        where = f"`{PARTITION_COLUMN}` BETWEEN DATE '{date_from}' AND DATE '{date_to}'"
        existing = self._query(f"SELECT COUNT(*) AS n FROM {target} WHERE {where}")[0]["n"]

        max_shrink = float(os.getenv("LOAD_MAX_SHRINK_RATIO", "0.5"))
        if existing >= 100 and profile.row_count < existing * (1 - max_shrink):
            raise ValueError(
                f"{source.name}: window {date_from}..{date_to} would shrink from {existing} to "
                f"{profile.row_count} rows; set LOAD_MAX_SHRINK_RATIO to allow it"
            )

        delete_sql = f"DELETE FROM {target} WHERE {where}"
        estimated = self._query(delete_sql, dry_run=True).total_bytes_processed
        LOGGER.info("%s: DELETE would scan %s bytes", source.name, estimated)

        columns = self._columns_sql(profile)
        script = (
            "BEGIN TRANSACTION;\n"
            f"{delete_sql};\n"
            f"INSERT INTO {target} ({columns}, `_loaded_at`, `{PARTITION_COLUMN}`)\n"
            f"SELECT {columns}, CURRENT_TIMESTAMP(), {parsed} FROM {stg};\n"
            "COMMIT TRANSACTION;"
        )
        self._query(script)

        return {
            "window": [date_from.isoformat(), date_to.isoformat()],
            "deleted": existing,
            "inserted": profile.row_count,
            "estimated_delete_bytes": estimated,
        }


def create_client():
    """Credentials come from Application Default Credentials / GOOGLE_APPLICATION_CREDENTIALS."""
    project = os.getenv("BQ_PROJECT") or None
    client = bigquery.Client(project=project, location=os.getenv("BQ_LOCATION") or None)
    return client, client.project

