"""Run history in PostgreSQL (`<schema>.pipeline_runs`).

Logging must never break a pipeline run, so every database error here is
caught and only written to the log.
"""

from __future__ import annotations

import json
import logging
import os
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone

from psycopg import sql

LOGGER = logging.getLogger("RunLog")

TABLE = "pipeline_runs"

DDL = """
CREATE TABLE IF NOT EXISTS {schema}.pipeline_runs (
    id          BIGSERIAL PRIMARY KEY,
    run_id      TEXT NOT NULL,
    stage       TEXT NOT NULL,
    source      TEXT NOT NULL,
    status      TEXT NOT NULL,
    rows        BIGINT,
    started_at  TIMESTAMPTZ NOT NULL,
    finished_at TIMESTAMPTZ NOT NULL,
    duration_s  NUMERIC(12, 2),
    error       TEXT,
    details     JSONB
)
"""


def default_run_id() -> str:
    """The orchestrator (Prefect) passes its run id through PIPELINE_RUN_ID; otherwise one per process."""
    return os.getenv("PIPELINE_RUN_ID") or uuid.uuid4().hex[:12]


class RunLog:
    def __init__(self, connection_factory, schema: str, run_id: str | None = None):
        self._factory = connection_factory
        self.schema = schema
        self.run_id = run_id or default_run_id()
        self._ready = False

    def record(
        self,
        stage: str,
        source: str,
        status: str,
        started_at: datetime,
        rows: int | None = None,
        error: str | None = None,
        details: dict | None = None,
    ) -> None:
        finished = datetime.now(timezone.utc)
        try:
            with self._factory() as connection:
                with connection.cursor() as cursor:
                    if not self._ready:
                        cursor.execute(
                            sql.SQL(DDL).format(schema=sql.Identifier(self.schema))
                        )
                        self._ready = True
                    cursor.execute(
                        sql.SQL(
                            "INSERT INTO {}.pipeline_runs (run_id, stage, source, status, rows, "
                            "started_at, finished_at, duration_s, error, details) "
                            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)"
                        ).format(sql.Identifier(self.schema)),
                        (
                            self.run_id,
                            stage,
                            source,
                            status,
                            rows,
                            started_at,
                            finished,
                            round((finished - started_at).total_seconds(), 2),
                            (error or None) and error[:2000],
                            json.dumps(details, default=str) if details else None,
                        ),
                    )
                connection.commit()
        except Exception as problem:  # noqa: BLE001 - logging must not fail the run
            LOGGER.warning("Could not write run log: %s", problem)

    @contextmanager
    def track(self, stage: str, source: str):
        """with log.track("database", "tickets") as run: ...; run["rows"] = n"""
        started = datetime.now(timezone.utc)
        info: dict = {"rows": None, "details": None}
        try:
            yield info
        except Exception as error:
            self.record(stage, source, "failed", started, info["rows"],
                        f"{type(error).__name__}: {error}", info["details"])
            raise
        else:
            self.record(stage, source, "success", started, info["rows"], None, info["details"])

    def last_success(self, stage: str, source: str) -> datetime | None:
        try:
            with self._factory() as connection, connection.cursor() as cursor:
                cursor.execute(
                    sql.SQL(
                        "SELECT max(finished_at) FROM {}.pipeline_runs "
                        "WHERE stage = %s AND source = %s AND status = 'success'"
                    ).format(sql.Identifier(self.schema)),
                    (stage, source),
                )
                return cursor.fetchone()[0]
        except Exception as problem:  # noqa: BLE001
            LOGGER.warning("Could not read run log: %s", problem)
            return None


class BigQueryRunLog(RunLog):
    """Same interface as RunLog, stored in `<dataset>.pipeline_runs` on BigQuery."""

    def __init__(self, client, project: str, dataset: str, run_id: str | None = None):
        super().__init__(None, dataset, run_id)
        self.client = client
        self.table = f"{project}.{dataset}.{TABLE}"

    def _ensure(self) -> None:
        if self._ready:
            return
        from google.cloud import bigquery

        schema = [
            bigquery.SchemaField("run_id", "STRING"),
            bigquery.SchemaField("stage", "STRING"),
            bigquery.SchemaField("source", "STRING"),
            bigquery.SchemaField("status", "STRING"),
            bigquery.SchemaField("rows", "INT64"),
            bigquery.SchemaField("started_at", "TIMESTAMP"),
            bigquery.SchemaField("finished_at", "TIMESTAMP"),
            bigquery.SchemaField("duration_s", "FLOAT64"),
            bigquery.SchemaField("error", "STRING"),
            bigquery.SchemaField("details", "STRING"),
        ]
        self.client.create_table(bigquery.Table(self.table, schema=schema), exists_ok=True)
        self._ready = True

    def record(self, stage, source, status, started_at, rows=None, error=None, details=None) -> None:
        finished = datetime.now(timezone.utc)
        try:
            self._ensure()
            errors = self.client.insert_rows_json(
                self.table,
                [{
                    "run_id": self.run_id,
                    "stage": stage,
                    "source": source,
                    "status": status,
                    "rows": rows,
                    "started_at": started_at.isoformat(),
                    "finished_at": finished.isoformat(),
                    "duration_s": round((finished - started_at).total_seconds(), 2),
                    "error": (error or None) and error[:2000],
                    "details": json.dumps(details, default=str) if details else None,
                }],
            )
            if errors:
                LOGGER.warning("Could not write run log: %s", errors)
        except Exception as problem:  # noqa: BLE001 - logging must not fail the run
            LOGGER.warning("Could not write run log: %s", problem)

    def last_success(self, stage: str, source: str):
        from google.cloud import bigquery

        try:
            config = bigquery.QueryJobConfig(
                query_parameters=[
                    bigquery.ScalarQueryParameter("stage", "STRING", stage),
                    bigquery.ScalarQueryParameter("source", "STRING", source),
                ]
            )
            rows = list(
                self.client.query(
                    f"SELECT MAX(finished_at) AS last FROM `{self.table}` "
                    "WHERE stage = @stage AND source = @source AND status = 'success'",
                    job_config=config,
                ).result()
            )
            return rows[0]["last"] if rows else None
        except Exception as problem:  # noqa: BLE001
            LOGGER.warning("Could not read run log: %s", problem)
            return None
