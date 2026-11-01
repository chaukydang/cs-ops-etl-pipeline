import csv
from datetime import date, timedelta

import pytest

from modules.database.csv_loader import CsvDatabaseLoader, CsvDefinition


def write_csv(path, days, per_day, value="x"):
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["Business Date", "Agent", "Closed"])
        for day in days:
            for n in range(per_day):
                writer.writerow([day.isoformat(), f"a{n}", value])
    return path


def days(start, count):
    return [start + timedelta(days=i) for i in range(count)]


def make(connection, schema, csv_file, **overrides):
    source = CsvDefinition(
        name="s",
        table_name="t",
        file_pattern=str(csv_file),
        load_mode=overrides.get("load_mode", "incremental"),
        date_column="business_date",
    )
    loader = CsvDatabaseLoader(connection, ".", schema)
    loader.initialize_table(source)
    return loader, source


def count(connection, schema, where=""):
    with connection.cursor() as cur:
        cur.execute(f'SELECT count(*) FROM "{schema}".t {where}')
        return cur.fetchone()[0]


def test_old_rows_survive_and_window_is_replaced(connection, schema, tmp_path):
    old = write_csv(tmp_path / "old.csv", days(date(2026, 1, 1), 10), 5)
    loader, source = make(connection, schema, old)

    r = loader.load_table(source, file_path=old, window=(date(2026, 1, 1), date(2026, 1, 10)))
    assert (r["deleted"], r["inserted"]) == (0, 50)

    recent = write_csv(tmp_path / "recent.csv", days(date(2026, 3, 1), 10), 5)
    loader.load_table(source, file_path=recent, window=(date(2026, 3, 1), date(2026, 3, 10)))
    assert count(connection, schema) == 100

    # the same window downloaded again with corrected data: replaced, not duplicated
    fixed = write_csv(tmp_path / "fixed.csv", days(date(2026, 3, 1), 10), 6, value="y")
    r = loader.load_table(source, file_path=fixed, window=(date(2026, 3, 1), date(2026, 3, 10)))
    assert (r["deleted"], r["inserted"]) == (50, 60)
    assert count(connection, schema) == 110
    assert count(connection, schema, "WHERE business_date < '2026-02-01'") == 50  # untouched


def test_sidecar_defines_window_so_vanished_days_are_cleared(connection, schema, tmp_path):
    first = write_csv(tmp_path / "a.csv", days(date(2026, 3, 1), 5), 2)
    loader, source = make(connection, schema, first)
    loader.load_table(source, file_path=first, window=(date(2026, 3, 1), date(2026, 3, 5)))

    # day 2026-03-05 no longer has data; the window still covers it
    second = write_csv(tmp_path / "b.csv", days(date(2026, 3, 1), 4), 2)
    (tmp_path / "b.csv.meta.json").write_text(
        '{"date_from": "2026-03-01", "date_to": "2026-03-05"}', encoding="utf-8"
    )
    loader.load_table(source, file_path=second)
    assert count(connection, schema, "WHERE business_date = '2026-03-05'") == 0
    assert count(connection, schema) == 8


def test_rows_outside_window_are_rejected_and_nothing_changes(connection, schema, tmp_path):
    base = write_csv(tmp_path / "a.csv", days(date(2026, 3, 1), 3), 2)
    loader, source = make(connection, schema, base)
    loader.load_table(source, file_path=base, window=(date(2026, 3, 1), date(2026, 3, 3)))

    bad = write_csv(tmp_path / "bad.csv", [date(1970, 1, 1), date(2026, 3, 2)], 2)
    with pytest.raises(ValueError, match="outside"):
        loader.load_table(source, file_path=bad, window=(date(2026, 3, 2), date(2026, 3, 2)))
    assert count(connection, schema) == 6


def test_empty_file_never_clears_the_window(connection, schema, tmp_path):
    base = write_csv(tmp_path / "a.csv", days(date(2026, 3, 1), 3), 2)
    loader, source = make(connection, schema, base)
    loader.load_table(source, file_path=base, window=(date(2026, 3, 1), date(2026, 3, 3)))

    empty = tmp_path / "empty.csv"
    empty.write_text("Business Date,Agent,Closed\n", encoding="utf-8")
    with pytest.raises(ValueError, match="no rows"):
        loader.load_table(source, file_path=empty, window=(date(2026, 3, 1), date(2026, 3, 3)))
    assert count(connection, schema) == 6


def test_big_shrink_is_blocked(connection, schema, tmp_path):
    base = write_csv(tmp_path / "a.csv", days(date(2026, 3, 1), 10), 20)  # 200 rows
    loader, source = make(connection, schema, base)
    loader.load_table(source, file_path=base, window=(date(2026, 3, 1), date(2026, 3, 10)))

    partial = write_csv(tmp_path / "p.csv", days(date(2026, 3, 1), 2), 5)  # 10 rows
    with pytest.raises(ValueError, match="shrink"):
        loader.load_table(source, file_path=partial, window=(date(2026, 3, 1), date(2026, 3, 10)))
    assert count(connection, schema) == 200


def test_replace_mode_still_truncates(connection, schema, tmp_path):
    base = write_csv(tmp_path / "a.csv", days(date(2026, 3, 1), 3), 2)
    loader, source = make(connection, schema, base, load_mode="replace")
    loader.load_table(source)
    smaller = write_csv(tmp_path / "a.csv", days(date(2026, 3, 1), 1), 2)
    loader.load_table(source, file_path=smaller)
    assert count(connection, schema) == 2


def test_backfill_end_to_end_keeps_adjacent_months(connection, schema, tmp_path):
    """Month-by-month backfill, then a daily-style reload of the last days."""
    from modules.dashboard.backfill import BackfillState, run_backfill

    seed = write_csv(tmp_path / "seed.csv", days(date(2026, 1, 1), 1), 1)
    loader, source = make(connection, schema, seed)

    def download(metric, start, end, out):
        n = (end - start).days + 1
        out.parent.mkdir(parents=True, exist_ok=True)
        return write_csv(out, days(start, n), 3)

    def load(metric, file, start, end):
        return loader.load_table(source, file_path=file, window=(start, end))

    state = BackfillState.load(tmp_path / "state.json")
    result = run_backfill(
        ["s"], date(2026, 1, 1), date(2026, 3, 31), chunk="month",
        work_dir=tmp_path / "w", state=state, download=download, load=load, archive=None,
    )

    assert not result["failed"]
    assert count(connection, schema) == 90 * 3

    # re-run of the final week (like the nightly rolling window): replaced, history kept
    week = write_csv(tmp_path / "week.csv", days(date(2026, 3, 25), 7), 4)
    loader.load_table(source, file_path=week, window=(date(2026, 3, 25), date(2026, 3, 31)))
    assert count(connection, schema) == 83 * 3 + 7 * 4
