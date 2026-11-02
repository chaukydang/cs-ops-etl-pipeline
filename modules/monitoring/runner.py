from __future__ import annotations

import os
from datetime import date
from pathlib import Path

from psycopg import sql

from modules.database.connection import DatabaseConnectionFactory
from modules.database.runner import DatabaseRunner
from modules.monitoring.freshness import Issue, check
from modules.monitoring.run_log import RunLog


def latest_dates(connection, schema: str, sources) -> tuple[dict, list[str]]:
    """Newest date per incremental source, plus the sources whose table is missing."""
    result = {}
    missing = []
    with connection.cursor() as cursor:
        for source in sources:
            cursor.execute(
                "SELECT to_regclass(%s)",
                ('"{}"."{}"'.format(schema, source.table_name),),
            )
            if cursor.fetchone()[0] is None:
                missing.append(source.name)
                continue
            if source.load_mode != "incremental":
                continue
            cursor.execute(
                sql.SQL(
                    "SELECT max(left({c}, 10)) FROM {s}.{t} WHERE {c} ~ '^[0-9]{{4}}-[0-9]{{2}}-[0-9]{{2}}' "
                    "AND left({c}, 10) <> '1970-01-01'"
                ).format(
                    c=sql.Identifier(source.date_column),
                    s=sql.Identifier(schema),
                    t=sql.Identifier(source.table_name),
                )
            )
            value = cursor.fetchone()[0]
            result[source.name] = date.fromisoformat(value) if value else None
    return result, missing


def latest_dates_bigquery(client, project: str, dataset: str, sources) -> tuple[dict, list[str]]:
    """BigQuery version: tables are partitioned, so MAX(_partition_date) is cheap."""
    from google.api_core.exceptions import NotFound

    result, missing = {}, []
    for source in sources:
        try:
            client.get_table(f"{project}.{dataset}.{source.table_name}")
        except NotFound:
            missing.append(source.name)
            continue
        if source.load_mode != "incremental":
            continue
        rows = list(
            client.query(
                f"SELECT MAX(`_partition_date`) AS latest FROM `{project}.{dataset}.{source.table_name}`"
            ).result()
        )
        result[source.name] = rows[0]["latest"] if rows else None
    return result, missing


def run(base_dir: Path, notify: bool = True) -> list[Issue]:
    runner = DatabaseRunner(base_dir)
    sources = runner._load_sources()
    max_age = float(os.getenv("MONITOR_MAX_LOAD_AGE_HOURS", "36"))

    if os.getenv("WAREHOUSE", "postgres").strip().lower() == "bigquery":
        from modules.monitoring.run_log import BigQueryRunLog
        from modules.warehouse.runner import bq_dataset, make_loader

        client, project, _ = make_loader(base_dir)
        log = BigQueryRunLog(client, project, bq_dataset())
        dates, missing = latest_dates_bigquery(client, project, bq_dataset(), sources)
    else:
        schema = runner.settings.get("schema", os.getenv("DB_SCHEMA", "Service"))
        log = RunLog(DatabaseConnectionFactory.connect, schema)
        with DatabaseConnectionFactory.connect() as connection:
            dates, missing = latest_dates(connection, schema, sources)
    present = [s for s in sources if s.name not in missing]
    last = {s.name: log.last_success("database", s.name) for s in present}

    issues = [Issue(name, "missing_table", "table does not exist (run init)") for name in missing]
    issues += check(present, dates, last, max_age_hours=max_age)

    print(f"[MONITOR] sources={len(sources)} issues={len(issues)}")
    for issue in issues:
        print(f"[MONITOR] {issue}")

    if issues and notify:
        from modules.core.env_loader import get_optional_env
        from modules.dashboard.notifier import LarkNotifier

        LarkNotifier(get_optional_env("LARK_WEBHOOK_URL")).send_warning(
            title="Data freshness check",
            message=f"{len(issues)} source(s) need attention",
            details={issue.source: f"{issue.kind}: {issue.message}" for issue in issues},
        )
    return issues
