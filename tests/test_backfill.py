import csv
from datetime import date, timedelta

import pytest

from modules.dashboard.backfill import (
    BackfillState,
    RowLimitError,
    backfill_window,
    make_chunks,
    run_backfill,
    split_window,
)


def test_month_chunks():
    assert make_chunks(date(2025, 11, 15), date(2026, 2, 10)) == [
        (date(2025, 11, 15), date(2025, 11, 30)),
        (date(2025, 12, 1), date(2025, 12, 31)),
        (date(2026, 1, 1), date(2026, 1, 31)),
        (date(2026, 2, 1), date(2026, 2, 10)),
    ]


def test_week_and_day_chunks_cover_range_without_gaps():
    for kind in ("week", "day"):
        chunks = make_chunks(date(2026, 1, 1), date(2026, 3, 9), kind)
        assert chunks[0][0] == date(2026, 1, 1) and chunks[-1][1] == date(2026, 3, 9)
        for (_, end), (start, _) in zip(chunks, chunks[1:]):
            assert start == end + timedelta(days=1)


def test_bad_range_and_kind():
    with pytest.raises(ValueError):
        make_chunks(date(2026, 2, 1), date(2026, 1, 1))
    with pytest.raises(ValueError):
        make_chunks(date(2026, 1, 1), date(2026, 1, 2), "year")


def test_split_window_halves():
    left, right = split_window(date(2026, 1, 1), date(2026, 1, 10))
    assert left == (date(2026, 1, 1), date(2026, 1, 5))
    assert right == (date(2026, 1, 6), date(2026, 1, 10))
    with pytest.raises(ValueError):
        split_window(date(2026, 1, 1), date(2026, 1, 1))


def test_state_coverage_and_persistence(tmp_path):
    path = tmp_path / "state.json"
    state = BackfillState.load(path)
    state.mark("m", date(2026, 1, 1), date(2026, 1, 5))
    state.mark("m", date(2026, 1, 6), date(2026, 1, 10))

    reloaded = BackfillState.load(path)
    assert reloaded.covered("m", date(2026, 1, 1), date(2026, 1, 10))
    assert reloaded.covered("m", date(2026, 1, 3), date(2026, 1, 8))
    assert not reloaded.covered("m", date(2026, 1, 1), date(2026, 1, 11))
    assert not reloaded.covered("other", date(2026, 1, 1), date(2026, 1, 2))


def fake_pipeline(tmp_path, limit):
    """Download fake: writes one row per day, raises RowLimitError above `limit` days."""
    calls = []
    loaded = []

    def download(metric, start, end, out):
        calls.append((start, end))
        days = (end - start).days + 1
        if days > limit:
            raise RowLimitError("too big")
        out.parent.mkdir(parents=True, exist_ok=True)
        with out.open("w", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(["d"])
            writer.writerows([[(start + timedelta(days=i)).isoformat()] for i in range(days)])
        return out

    def load(metric, file, start, end):
        loaded.append((start, end))
        return {"inserted": (end - start).days + 1}

    return download, load, calls, loaded


def test_row_limit_splits_until_it_fits(tmp_path):
    download, load, calls, loaded = fake_pipeline(tmp_path, limit=8)
    state = BackfillState.load(tmp_path / "s.json")

    results = backfill_window(
        "m", date(2026, 1, 1), date(2026, 1, 31),
        work_dir=tmp_path / "w", state=state, download=download, load=load, archive=None,
    )

    assert sum(r["inserted"] for r in results) == 31
    covered_days = sorted(d for s, e in loaded for d in [(e - s).days + 1])
    assert max(covered_days) <= 8
    assert state.covered("m", date(2026, 1, 1), date(2026, 1, 31))
    # downloaded chunk files are removed after loading
    assert not list((tmp_path / "w").rglob("*.csv"))


def test_rerun_skips_finished_work(tmp_path):
    download, load, calls, loaded = fake_pipeline(tmp_path, limit=100)
    state = BackfillState.load(tmp_path / "s.json")
    kwargs = dict(chunk="month", work_dir=tmp_path / "w", state=state,
                  download=download, load=load, archive=None)

    run_backfill(["m"], date(2026, 1, 1), date(2026, 3, 31), **kwargs)
    first_calls = len(calls)
    run_backfill(["m"], date(2026, 1, 1), date(2026, 3, 31), **kwargs)
    assert len(calls) == first_calls  # nothing downloaded the second time


def test_failure_stops_that_metric_but_keeps_progress(tmp_path):
    download, load, calls, loaded = fake_pipeline(tmp_path, limit=100)

    def flaky(metric, start, end, out):
        if start.month == 2:
            raise RuntimeError("session expired")
        return download(metric, start, end, out)

    state = BackfillState.load(tmp_path / "s.json")
    result = run_backfill(
        ["m"], date(2026, 1, 1), date(2026, 3, 31), chunk="month",
        work_dir=tmp_path / "w", state=state, download=flaky, load=load, archive=None,
    )

    assert len(result["completed"]) == 1 and len(result["failed"]) == 1
    assert state.covered("m", date(2026, 1, 1), date(2026, 1, 31))
    assert not state.covered("m", date(2026, 2, 1), date(2026, 2, 28))
