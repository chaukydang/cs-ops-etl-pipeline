import pytest

from modules.database.csv_loader import CsvDatabaseLoader
from modules.lark.transform_raw import column_number_to_name


@pytest.mark.parametrize(
    "number, expected",
    [(1, "A"), (26, "Z"), (27, "AA"), (30, "AD"), (703, "AAA")],
)
def test_column_number_to_name(number, expected):
    assert column_number_to_name(number) == expected


def test_column_number_to_name_invalid():
    with pytest.raises(ValueError):
        column_number_to_name(0)


def test_make_identifier():
    make = CsvDatabaseLoader.make_identifier
    assert make("Paid Hours") == "paid_hours"
    assert make("  #close ") == "close"
    assert make("2nd Tier") == "col_2nd_tier"
    assert make("", fallback="column_3") == "column_3"
    assert len(make("a" * 100)) <= 63


def test_normalize_headers_dedupes():
    out = CsvDatabaseLoader.normalize_headers(["Name", "name", "NAME", ""])
    assert out == ["name", "name_2", "name_3", "column_4"]
