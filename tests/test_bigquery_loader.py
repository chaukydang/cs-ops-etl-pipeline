"""BigQuery loader against a recording fake client (no network, no credentials)."""

import csv
import io
import re
from datetime import date, datetime, timezone

import pytest

pytest.importorskip("google.cloud.bigquery")

from google.api_core.exceptions import NotFound  # noqa: E402
from google.cloud import bigquery  # noqa: E402

from modules.database.csv_loader import CsvDefinition  # noqa: E402
from modules.monitoring.run_log import BigQueryRunLog  # noqa: E402
from modules.warehouse.bigquery import BigQueryLoader  # noqa: E402

PROJECT, DATASET = "proj", "raw"


class Job:
    def __init__(self, rows=None, total_bytes_processed=0):
        self._rows = rows or []
        self.total_bytes_processed = total_bytes_processed

    def result(self):
        return self._rows


class FakeClient:
    def __init__(self, existing_rows_in_window=0):
        self.tables: dict[str, list[bigquery.SchemaField]] = {}
        self.table_objects: dict[str, bigquery.Table] = {}
        self.queries: list[str] = []
        self.query_configs: list[bigquery.QueryJobConfig] = []
        self.staged_header: list[str] = []
        self.staged_rows: list[list[str]] = []
        self.deleted_tables: list[str] = []
        self.existing_rows_in_window = existing_rows_in_window
        self.inserted_json: list[dict] = []

    # --- table API
    def get_table(self, table_id):
        if table_id not in self.tables:
            raise NotFound(table_id)
        return type("T", (), {"schema": self.tables[table_id]})()

    def create_table(self, table, exists_ok=False):
        self.tables[table.full_table_id.replace(":", ".") if table.full_table_id else
                    f"{table.project}.{table.dataset_id}.{table.table_id}"] = list(table.schema)
        self.table_objects[f"{table.project}.{table.dataset_id}.{table.table_id}"] = table

    def delete_table(self, table_id, not_found_ok=False):
        self.deleted_tables.append(table_id)

    def load_table_from_file(self, handle, table_id, job_config=None):
        reader = csv.reader(io.StringIO(handle.read().decode("utf-8")))
        self.staged_header = next(reader)
        self.staged_rows = list(reader)
        return Job()

    def insert_rows_json(self, table_id, rows):
        self.inserted_json += rows
        return []

    # --- queries
    def query(self, sql, job_config=None):
        self.queries.append(sql)
        self.query_configs.append(job_config)
        if job_config is not None and job_config.dry_run:
            return Job(total_bytes_processed=4096)
        if "COUNTIF(" in sql:
            dates = [r[0][:10] for r in self.staged_rows]
            good = [d for d in dates if re.fullmatch(r"\d{4}-\d{2}-\d{2}", d)]
            return Job([{
                "invalid": len(dates) - len(good),
                "dmin": date.fromisoformat(min(good)) if good else None,
                "dmax": date.fromisoformat(max(good)) if good else None,
            }])
        if "FROM `proj.raw._stg_" in sql and "COUNT(*) AS n" in sql:
            return Job([{"n": len(self.staged_rows)}])
        if "COUNT(*) AS n" in sql:
            return Job([{"n": self.existing_rows_in_window}])
        return Job()

    # --- helpers for assertions
    def script(self):
        return next((q for q in self.queries if "BEGIN TRANSACTION" in q), None)


def write_csv(path, rows, header=("Business Date", "Agent", "Closed")):
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(header)
        writer.writerows(rows)
    return path


def source(csv_file, mode="incremental", cluster=()):
    return CsvDefinition(
        name="s", table_name="t", file_pattern=str(csv_file), load_mode=mode,
        date_column="business_date", cluster_by=tuple(cluster),
    )


def loader(client, **kw):
    return BigQueryLoader(client, PROJECT, DATASET, ".", **kw)


def test_init_creates_partitioned_clustered_table(tmp_path):
    client = FakeClient()
    f = write_csv(tmp_path / "a.csv", [["2026-03-01", "a", "1"]])
    result = loader(client).initialize_table(source(f, cluster=["agent"]))

    assert result["status"] == "created"
    table = client.table_objects[f"{PROJECT}.{DATASET}.t"]
    assert table.time_partitioning.field == "_partition_date"
    assert table.clustering_fields == ["agent"]
    names = [f.name for f in table.schema]
    assert names[:3] == ["business_date", "agent", "closed"]
    assert {"_source_file", "_row_hash", "_loaded_at", "_partition_date"} <= set(names)
    assert all(f.field_type == "STRING" for f in table.schema[:3])


def test_init_replace_mode_is_not_partitioned(tmp_path):
    client = FakeClient()
    f = write_csv(tmp_path / "a.csv", [["2026-03-01", "a", "1"]])
    loader(client).initialize_table(source(f, mode="replace"))
    assert client.table_objects[f"{PROJECT}.{DATASET}.t"].time_partitioning is None


def prepared(tmp_path, rows, existing=0, **kw):
    client = FakeClient(existing_rows_in_window=existing)
    f = write_csv(tmp_path / "a.csv", rows)
    bq = loader(client, **kw)
    src = source(f)
    bq.initialize_table(src)
    return client, bq, src, f


def test_window_is_replaced_in_one_transaction(tmp_path):
    rows = [["2026-03-01", "a", "1"], ["2026-03-02", "b", "2"]]
    client, bq, src, f = prepared(tmp_path, rows, existing=2)

    result = bq.load_table(src, window=(date(2026, 3, 1), date(2026, 3, 5)))

    script = client.script()
    assert script.index("BEGIN TRANSACTION") < script.index("DELETE FROM") < script.index("INSERT INTO") < script.index("COMMIT")
    assert "`_partition_date` BETWEEN DATE '2026-03-01' AND DATE '2026-03-05'" in script
    assert "SAFE.PARSE_DATE('%Y-%m-%d', SUBSTR(`business_date`, 1, 10))" in script
    assert (result["deleted"], result["inserted"]) == (2, 2)
    assert result["estimated_delete_bytes"] == 4096
    # staging file: BigQuery-safe headers plus metadata, and the staging table is dropped
    assert client.staged_header == ["business_date", "agent", "closed", "_source_file", "_source_row_number", "_row_hash"]
    assert client.staged_rows[0][3] == "a.csv"
    assert client.deleted_tables and client.deleted_tables[0].startswith(f"{PROJECT}.{DATASET}._stg_t_")


@pytest.mark.parametrize(
    "rows, existing, window, message",
    [
        ([["not-a-date", "a", "1"]], 0, (date(2026, 3, 1), date(2026, 3, 5)), "no valid date"),
        ([["2026-03-01", "a", "1"], ["1970-01-01", "b", "2"]], 0, (date(2026, 3, 1), date(2026, 3, 5)), "outside"),
        ([["2026-03-01", "a", "1"]], 500, (date(2026, 3, 1), date(2026, 3, 5)), "shrink"),
    ],
)
def test_guards_stop_before_anything_is_deleted(tmp_path, rows, existing, window, message):
    client, bq, src, f = prepared(tmp_path, rows, existing=existing)

    with pytest.raises(ValueError, match=message):
        bq.load_table(src, window=window)

    assert client.script() is None
    assert not any(q.startswith("DELETE") for q in client.queries)
    assert client.deleted_tables  # staging table is cleaned up even on failure


def test_empty_csv_is_refused_without_loading_anything(tmp_path):
    client, bq, src, f = prepared(tmp_path, [["2026-03-01", "a", "1"]])
    write_csv(f, [])
    with pytest.raises(ValueError, match="no rows"):
        bq.load_table(src, window=(date(2026, 3, 1), date(2026, 3, 5)))
    assert client.staged_rows == [] and client.script() is None


def test_schema_mismatch_is_detected(tmp_path):
    client, bq, src, f = prepared(tmp_path, [["2026-03-01", "a", "1"]])
    write_csv(f, [["2026-03-01", "a", "1"]], header=("Business Date", "Agent", "Other"))
    with pytest.raises(ValueError, match="Schema mismatch"):
        bq.load_table(src, window=(date(2026, 3, 1), date(2026, 3, 1)))


def test_missing_table_asks_for_init(tmp_path):
    client = FakeClient()
    f = write_csv(tmp_path / "a.csv", [["2026-03-01", "a", "1"]])
    with pytest.raises(RuntimeError, match="Run init"):
        loader(client).load_table(source(f))


def test_replace_mode_rebuilds_table_without_transaction(tmp_path):
    client = FakeClient()
    f = write_csv(tmp_path / "a.csv", [["x", "a", "1"]])
    bq = loader(client)
    src = source(f, mode="replace")
    bq.initialize_table(src)

    result = bq.load_table(src)

    assert any(q.startswith("CREATE OR REPLACE TABLE `proj.raw.t`") for q in client.queries)
    assert client.script() is None
    assert result["inserted"] == 1


def test_bytes_billed_cap_applies_to_real_queries_not_dry_runs(tmp_path):
    client, bq, src, f = prepared(tmp_path, [["2026-03-01", "a", "1"]], max_bytes_billed=1_000_000)
    bq.load_table(src, window=(date(2026, 3, 1), date(2026, 3, 1)))

    real = [c for c in client.query_configs if c is not None and not c.dry_run]
    dry = [c for c in client.query_configs if c is not None and c.dry_run]
    assert real and all(c.maximum_bytes_billed == 1_000_000 for c in real)
    assert dry and all(c.maximum_bytes_billed is None for c in dry)


def test_bigquery_run_log_inserts_rows_and_never_raises():
    client = FakeClient()
    log = BigQueryRunLog(client, PROJECT, DATASET, run_id="r1")
    started = datetime.now(timezone.utc)

    with log.track("database", "tickets") as run:
        run["rows"] = 7
    assert client.inserted_json[0]["status"] == "success" and client.inserted_json[0]["rows"] == 7
    assert f"{PROJECT}.{DATASET}.pipeline_runs" in client.tables or client.table_objects

    class Broken(FakeClient):
        def insert_rows_json(self, *a, **k):
            raise RuntimeError("quota")

    BigQueryRunLog(Broken(), PROJECT, DATASET).record("database", "x", "failed", started, error="boom")
