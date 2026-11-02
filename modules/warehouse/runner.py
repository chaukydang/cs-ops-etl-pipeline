"""BigQuery counterpart of modules.database.runner.DatabaseRunner."""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone

from modules.database.runner import DatabaseRunner
from modules.monitoring.run_log import BigQueryRunLog
from modules.warehouse.bigquery import BigQueryLoader, create_client


def bq_dataset() -> str:
    return os.getenv("BQ_DATASET", "raw")


def make_loader(project_root):
    client, project = create_client()
    max_bytes = os.getenv("BQ_MAX_BYTES_BILLED")
    loader = BigQueryLoader(
        client, project, bq_dataset(), project_root,
        max_bytes_billed=int(max_bytes) if max_bytes else None,
    )
    return client, project, loader


class BigQueryRunner(DatabaseRunner):
    """Same sources and config as the PostgreSQL runner, different target."""

    def run(self, action, source_name=None):
        action = str(action).strip().lower()
        if action not in {"init", "load"}:
            raise ValueError("Database action must be init or load")

        sources = self._load_sources()
        if source_name:
            sources = [s for s in sources if s.name == source_name]
        if not sources:
            raise ValueError("No matching database sources")

        client, project, loader = make_loader(self.project_root)
        run_log = BigQueryRunLog(client, project, bq_dataset())
        logger = logging.getLogger(self.__class__.__name__)
        completed, failed = [], []

        print(f"[BIGQUERY] Action={action} | Sources={len(sources)} | {project}.{bq_dataset()}")
        for index, source in enumerate(sources, start=1):
            print(f"[BIGQUERY] Running {index}/{len(sources)} | {source.name} | {source.table_name}")
            started_at = datetime.now(timezone.utc)
            try:
                result = (
                    loader.initialize_table(source) if action == "init" else loader.load_table(source)
                )
                completed.append(result)
                run_log.record(
                    "database", source.name, "success", started_at,
                    rows=result.get("inserted", result.get("rows")),
                    details={"action": action, **result},
                )
                print(f"[BIGQUERY COMPLETED] {source.name} | {result['status']} | {source.table_name}")
            except Exception as error:
                run_log.record(
                    "database", source.name, "failed", started_at,
                    error=f"{type(error).__name__}: {error}", details={"action": action},
                )
                failed.append({
                    "source": source.name, "table": source.table_name,
                    "error_type": type(error).__name__, "error": str(error),
                })
                logger.exception("BigQuery source failed | source=%s", source.name)
                print(f"[BIGQUERY FAILED] {source.name} | {type(error).__name__}: {error}")
                if not self.settings.get("continue_on_error", True):
                    raise

        print(f"[BIGQUERY] completed={len(completed)} failed={len(failed)}")
        return {"completed": completed, "failed": failed}
