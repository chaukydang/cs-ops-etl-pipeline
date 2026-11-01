"""Historical backfill for the dashboard reports.

The daily run only downloads a rolling window (about 5 weeks). To load years of
history, this module walks a date range in chunks (month by default), and for
every chunk: downloads the report, loads it incrementally into PostgreSQL
(only that date range is replaced), and archives it as Parquet.

- A chunk that hits the export's row limit is split in half automatically.
- Finished chunks are recorded in a state file, so an interrupted run can be
  started again with the same arguments and continues where it stopped.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path

LOGGER = logging.getLogger("Backfill")

MIN_SPLIT_DAYS = 1


class RowLimitError(Exception):
    """The export for this window is incomplete because it hit the row limit."""


def parse_date(value: str) -> date:
    return date.fromisoformat(value)


def make_chunks(date_from: date, date_to: date, chunk: str = "month") -> list[tuple[date, date]]:
    if date_to < date_from:
        raise ValueError("--to must not be before --from")

    chunks: list[tuple[date, date]] = []
    cursor = date_from
    while cursor <= date_to:
        if chunk == "day":
            end = cursor
        elif chunk == "week":
            end = cursor + timedelta(days=6)
        elif chunk == "month":
            first_of_next = (cursor.replace(day=1) + timedelta(days=32)).replace(day=1)
            end = first_of_next - timedelta(days=1)
        else:
            raise ValueError("chunk must be day, week or month")

        end = min(end, date_to)
        chunks.append((cursor, end))
        cursor = end + timedelta(days=1)
    return chunks


def split_window(start: date, end: date) -> tuple[tuple[date, date], tuple[date, date]]:
    days = (end - start).days + 1
    if days <= MIN_SPLIT_DAYS:
        raise ValueError("cannot split a single day")
    middle = start + timedelta(days=days // 2 - 1)
    return (start, middle), (middle + timedelta(days=1), end)


@dataclass
class BackfillState:
    """Completed windows per metric, stored as JSON."""

    path: Path
    done: dict[str, list[list[str]]] = field(default_factory=dict)

    @classmethod
    def load(cls, path: Path) -> BackfillState:
        path = Path(path)
        done = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
        return cls(path=path, done=done)

    def mark(self, metric: str, start: date, end: date) -> None:
        self.done.setdefault(metric, []).append([start.isoformat(), end.isoformat()])
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp = self.path.with_suffix(".tmp")
        temp.write_text(json.dumps(self.done, indent=1), encoding="utf-8")
        temp.replace(self.path)

    def covered(self, metric: str, start: date, end: date) -> bool:
        """True if finished windows together cover every day of start..end."""
        intervals = sorted(
            (parse_date(a), parse_date(b)) for a, b in self.done.get(metric, [])
        )
        cursor = start
        for a, b in intervals:
            if a > cursor:
                break
            if b >= cursor:
                cursor = b + timedelta(days=1)
            if cursor > end:
                return True
        return cursor > end


# download(metric, start, end, out_file) -> Path ; raises RowLimitError when truncated
DownloadFn = Callable[[str, date, date, Path], Path]
# load(metric, file, start, end) -> dict
LoadFn = Callable[[str, Path, date, date], dict]
# archive(metric, file, end) -> rows
ArchiveFn = Callable[[str, Path, date], int]


def backfill_window(
    metric: str,
    start: date,
    end: date,
    *,
    work_dir: Path,
    state: BackfillState,
    download: DownloadFn,
    load: LoadFn,
    archive: ArchiveFn | None,
    keep_files: bool = False,
) -> list[dict]:
    """Process one window, splitting it when the export is truncated."""
    if state.covered(metric, start, end):
        print(f"[BACKFILL] skip {metric} {start}..{end} (already done)")
        return []

    out_file = work_dir / metric / f"{metric}-{start.isoformat()}_{end.isoformat()}.csv"
    try:
        file_path = download(metric, start, end, out_file)
    except RowLimitError:
        left, right = split_window(start, end)
        print(f"[BACKFILL] {metric} {start}..{end} hit the row limit, splitting")
        return backfill_window(
            metric, *left, work_dir=work_dir, state=state, download=download,
            load=load, archive=archive, keep_files=keep_files,
        ) + backfill_window(
            metric, *right, work_dir=work_dir, state=state, download=download,
            load=load, archive=archive, keep_files=keep_files,
        )

    result = load(metric, file_path, start, end)
    archived = archive(metric, file_path, end) if archive else None
    state.mark(metric, start, end)

    if not keep_files:
        file_path.unlink(missing_ok=True)
        Path(str(file_path) + ".meta.json").unlink(missing_ok=True)

    result = {**result, "metric": metric, "start": start.isoformat(), "end": end.isoformat(),
              "archived_rows": archived}
    print(f"[BACKFILL] done {metric} {start}..{end} | {result.get('inserted')} rows")
    return [result]


def run_backfill(
    metrics: list[str],
    date_from: date,
    date_to: date,
    *,
    chunk: str,
    work_dir: Path,
    state: BackfillState,
    download: DownloadFn,
    load: LoadFn,
    archive: ArchiveFn | None,
    keep_files: bool = False,
) -> dict:
    completed: list[dict] = []
    failed: list[dict] = []

    for metric in metrics:
        for start, end in make_chunks(date_from, date_to, chunk):
            try:
                completed += backfill_window(
                    metric, start, end, work_dir=work_dir, state=state, download=download,
                    load=load, archive=archive, keep_files=keep_files,
                )
            except Exception as error:
                LOGGER.exception("Backfill failed | %s %s..%s", metric, start, end)
                failed.append({"metric": metric, "start": start.isoformat(),
                               "end": end.isoformat(), "error": f"{type(error).__name__}: {error}"})
                print(f"[BACKFILL FAILED] {metric} {start}..{end} | {error}")
                break  # next chunks of this metric depend on a working session; retry later

    return {"completed": completed, "failed": failed}


def day_start(d: date) -> datetime:
    return datetime(d.year, d.month, d.day, 0, 0, 0)


def day_end(d: date) -> datetime:
    return datetime(d.year, d.month, d.day, 23, 59, 59)
