"""Wires the backfill core to the real dashboard, database and archive."""

from __future__ import annotations

from datetime import date
from pathlib import Path

from modules.dashboard.backfill import (
    BackfillState,
    RowLimitError,
    day_end,
    day_start,
    run_backfill,
)


def run(
    base_dir: Path,
    date_from: date,
    date_to: date,
    chunk: str = "month",
    source: str | None = None,
    archive: bool = True,
    keep_files: bool = False,
) -> dict:
    from modules.core.env_loader import get_optional_env
    from modules.dashboard import runner as dash
    from modules.dashboard.downloader import AeolusRowLimitError, AeolusUnauthorizedError
    from modules.database.connection import DatabaseConnectionFactory
    from modules.database.csv_loader import CsvDatabaseLoader
    from modules.database.runner import DatabaseRunner
    from modules.storage.parquet_archive import csv_to_parquet, partition_path, upload_to_s3
    from modules.storage.runner import ArchiveRunner

    base_dir = Path(base_dir).resolve()

    configs = {
        str(cfg["metric_name"]).strip(): cfg
        for _, cfg in dash.discover_source_configs()
    }
    if source:
        if source not in configs:
            raise ValueError(f"Unknown source {source!r}; available: {sorted(configs)}")
        configs = {source: configs[source]}

    db_runner = DatabaseRunner(base_dir)
    db_sources = {s.name: s for s in db_runner._load_sources()}
    for metric, cfg in configs.items():
        if not cfg.get("dynamic_date", {}).get("enabled"):
            raise ValueError(f"{metric}: dynamic_date is not enabled, cannot window the export")
        db_source = db_sources.get(metric)
        if db_source is None or db_source.load_mode != "incremental":
            raise ValueError(
                f"{metric}: backfill needs a database source with load_mode=incremental "
                "(a replace-mode load would wipe the table)"
            )

    auth_manager = dash.create_auth_manager()
    downloader = dash.create_downloader(auth_manager.ensure_authenticated())
    archive_root = ArchiveRunner(base_dir).archive_root
    work_dir = base_dir / "downloads" / "backfill"
    state = BackfillState.load(base_dir / "data" / "backfill_state.json")

    def download(metric: str, start: date, end: date, out_file: Path) -> Path:
        window = (day_start(start), day_end(end))
        try:
            try:
                return downloader.download_metric(configs[metric], window=window, output_file=out_file)
            except AeolusUnauthorizedError:
                context = auth_manager.refresh_auth()
                downloader.update_authentication(context.open_api_token, context.cookies)
                return downloader.download_metric(configs[metric], window=window, output_file=out_file)
        except AeolusRowLimitError as error:
            raise RowLimitError(str(error)) from error

    connection = DatabaseConnectionFactory.connect()
    schema = db_runner.settings.get("schema", get_optional_env("DB_SCHEMA", "Service"))
    loader = CsvDatabaseLoader(connection, base_dir, schema)

    def load(metric: str, file_path: Path, start: date, end: date) -> dict:
        db_source = db_sources[metric]
        loader.initialize_table(db_source, file_path=file_path)
        return loader.load_table(db_source, file_path=file_path, window=(start, end))

    def archive_chunk(metric: str, file_path: Path, end: date) -> int:
        target = partition_path(archive_root, metric, end)
        rows = csv_to_parquet(file_path, target)
        upload_to_s3(target, archive_root)
        return rows

    try:
        return run_backfill(
            list(configs),
            date_from,
            date_to,
            chunk=chunk,
            work_dir=work_dir,
            state=state,
            download=download,
            load=load,
            archive=archive_chunk if archive else None,
            keep_files=keep_files,
        )
    finally:
        connection.close()
        auth_manager.close()
