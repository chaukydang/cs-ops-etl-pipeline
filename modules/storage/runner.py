from __future__ import annotations

import glob
import json
import logging
import os
from datetime import date
from pathlib import Path

from modules.storage.parquet_archive import (
    csv_to_parquet,
    partition_path,
    previous_row_count,
    upload_to_s3,
)
from modules.storage.quality import DataQualityError, check_row_count


class ArchiveRunner:
    """For each configured source: check the newest CSV, then archive it as Parquet.

    Sources and file patterns come from configs/database/sources, so the
    archive and the database load always look at the same files.
    """

    def __init__(self, project_root, run_date: date | None = None):
        self.project_root = Path(project_root).resolve()
        self.run_date = run_date or date.today()
        self.logger = logging.getLogger(self.__class__.__name__)

        root = os.getenv("ARCHIVE_DIR", "").strip() or "data/archive"
        path = Path(root)
        self.archive_root = path if path.is_absolute() else self.project_root / path

        settings_file = self.project_root / "configs" / "database" / "settings.json"
        settings = json.loads(settings_file.read_text(encoding="utf-8-sig"))
        self.source_dir = self.project_root / settings.get(
            "source_directory", "configs/database/sources"
        )
        self.min_rows = int(os.getenv("ARCHIVE_MIN_ROWS", "1"))
        self.max_drop = float(os.getenv("ARCHIVE_MAX_DROP_RATIO", "0.5"))

    def run(self, source_name: str | None = None) -> dict:
        completed, failed = [], []

        for config_file in sorted(self.source_dir.glob("*.json")):
            config = json.loads(config_file.read_text(encoding="utf-8-sig"))
            name = str(config["name"]).strip()

            if not config.get("enabled", True):
                continue
            if source_name and name != source_name:
                continue

            try:
                completed.append(self._archive_one(name, config))
            except Exception as error:
                self.logger.exception("Archive failed | source=%s", name)
                failed.append(
                    {"source": name, "error_type": type(error).__name__, "error": str(error)}
                )
                print(f"[ARCHIVE FAILED] {name} | {type(error).__name__}: {error}")

        print(f"[ARCHIVE] completed={len(completed)} failed={len(failed)}")
        return {"completed": completed, "failed": failed}

    def _archive_one(self, name: str, config: dict) -> dict:
        csv_file = self._latest_file(config)
        target = partition_path(self.archive_root, name, self.run_date)

        rows = csv_to_parquet(csv_file, target)
        previous = previous_row_count(self.archive_root, name, self.run_date)

        try:
            check_row_count(rows, previous, self.min_rows, self.max_drop)
        except DataQualityError:
            target.unlink(missing_ok=True)
            raise

        key = upload_to_s3(target, self.archive_root)
        print(f"[ARCHIVE] {name} | rows={rows} | previous={previous} | {target.name}")
        return {"source": name, "rows": rows, "previous_rows": previous, "s3_key": key}

    def _latest_file(self, config: dict) -> Path:
        pattern = Path(config["file_pattern"])
        if not pattern.is_absolute():
            pattern = self.project_root / pattern
        files = [
            Path(f)
            for f in glob.glob(str(pattern), recursive=bool(config.get("recursive", True)))
            if Path(f).is_file()
        ]
        if not files:
            raise FileNotFoundError(f"No CSV for {config['name']}: {config['file_pattern']}")
        return max(files, key=lambda p: p.stat().st_mtime)
