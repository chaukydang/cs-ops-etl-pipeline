from datetime import date

import pyarrow.parquet as pq
import pytest

from modules.storage.parquet_archive import (
    csv_to_parquet,
    make_unique,
    partition_path,
    previous_row_count,
)
from modules.storage.quality import (
    DataQualityError,
    check_header_unchanged,
    check_row_count,
)


def write_csv(path, rows):
    lines = ["id,Name,Name"] + [f"{i},a{i},b{i}" for i in range(rows)]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8-sig")
    return path


def test_make_unique():
    assert make_unique(["a", "a", "", "a"]) == ["a", "a_2", "column", "a_3"]


def test_csv_to_parquet_roundtrip(tmp_path):
    src = write_csv(tmp_path / "x.csv", 5)
    out = tmp_path / "out" / "x.parquet"

    assert csv_to_parquet(src, out) == 5

    table = pq.read_table(out)
    assert table.column_names == ["id", "Name", "Name_2"]
    assert table.num_rows == 5
    assert table.column("id").to_pylist()[0] == "0"


def test_empty_csv_is_rejected(tmp_path):
    src = tmp_path / "empty.csv"
    src.write_text("a,b\n", encoding="utf-8")
    with pytest.raises(ValueError):
        csv_to_parquet(src, tmp_path / "e.parquet")


def test_previous_row_count_picks_latest_older_partition(tmp_path):
    for day, rows in ((date(2026, 11, 1), 3), (date(2026, 11, 2), 7), (date(2026, 11, 3), 9)):
        src = write_csv(tmp_path / "t.csv", rows)
        csv_to_parquet(src, partition_path(tmp_path, "s", day))

    assert previous_row_count(tmp_path, "s", date(2026, 11, 3)) == 7
    assert previous_row_count(tmp_path, "s", date(2026, 11, 1)) is None
    assert previous_row_count(tmp_path, "missing", date(2026, 11, 3)) is None


def test_row_count_checks():
    check_row_count(100, None)
    check_row_count(60, 100)
    with pytest.raises(DataQualityError):
        check_row_count(0, None)
    with pytest.raises(DataQualityError):
        check_row_count(40, 100)


def test_header_check():
    check_header_unchanged(["a", "b"], None)
    check_header_unchanged(["a", "b"], ["a", "b"])
    with pytest.raises(DataQualityError, match="missing"):
        check_header_unchanged(["a"], ["a", "b"])
