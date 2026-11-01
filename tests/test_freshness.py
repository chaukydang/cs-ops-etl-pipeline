from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace

from modules.monitoring.freshness import check, evaluate_lag, evaluate_last_success

TODAY = date(2026, 11, 2)
NOW = datetime(2026, 11, 2, 8, 0, tzinfo=timezone.utc)


def src(name, mode="incremental", lag=3):
    return SimpleNamespace(name=name, load_mode=mode, max_lag_days=lag)


def test_lag():
    assert evaluate_lag("s", date(2026, 11, 1), TODAY, 3) is None
    assert evaluate_lag("s", date(2026, 10, 30), TODAY, 3) is None  # exactly at the limit
    assert evaluate_lag("s", date(2026, 10, 29), TODAY, 3).kind == "stale"
    assert evaluate_lag("s", None, TODAY, 3).kind == "empty"


def test_last_success():
    assert evaluate_last_success("s", NOW - timedelta(hours=5), NOW, 36) is None
    assert evaluate_last_success("s", NOW - timedelta(hours=40), NOW, 36).kind == "no_recent_load"
    assert evaluate_last_success("s", None, NOW, 36).kind == "never_loaded"


def test_check_combines_sources_and_skips_lag_for_replace_mode():
    sources = [src("a"), src("b"), src("sheet", mode="replace")]
    fresh = NOW - timedelta(hours=2)
    issues = check(
        sources,
        latest_dates={"a": date(2026, 11, 1), "b": date(2026, 10, 1)},
        last_success={"a": fresh, "b": fresh, "sheet": fresh},
        today=TODAY,
        now=NOW,
    )
    assert [(i.source, i.kind) for i in issues] == [("b", "stale")]
