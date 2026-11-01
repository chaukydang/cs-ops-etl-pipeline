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
    """Airflow passes its run id through PIPELINE_RUN_ID; otherwise one per process."""
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
