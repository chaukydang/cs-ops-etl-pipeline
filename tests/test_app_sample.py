"""The dashboard in demo mode: no database, only the bundled sample CSVs."""

import re
from pathlib import Path

import pytest

pytest.importorskip("streamlit")
pytest.importorskip("duckdb")

APP = Path(__file__).resolve().parents[1] / "app" / "streamlit_app.py"


def kpis(at) -> dict[str, str]:
    """KPI tiles are HTML in one markdown block: label -> value."""
    html = "".join(m.value for m in at.markdown)
    found = re.findall(r'kpi-label">([^<]+)</div><div class="kpi-row"><span class="kpi-value">([^<]+)<', html)
    return {label: value for label, value in found}


@pytest.fixture(autouse=True)
def no_database(monkeypatch):
    monkeypatch.delenv("DB_HOST", raising=False)
    monkeypatch.setenv("SAMPLE_DATA", "1")


def test_demo_dashboard_renders_with_numbers():
    from streamlit.testing.v1 import AppTest

    at = AppTest.from_file(str(APP), default_timeout=90).run()

    assert not at.exception, [e.value for e in at.exception]
    values = kpis(at)
    for label in ("Created", "Closed", "CPH", "Occupancy", "CSAT", "FCR",
                  "Resolved 24h", "1st response (min)", "On-time"):
        assert values[label] != "-", label
    assert values["Closed"] not in ("-", "0")
    # the sample is labelled, quietly, in the footer
    assert any("sample dataset" in c.value for c in at.caption)


def test_skill_group_filter_changes_the_numbers():
    from streamlit.testing.v1 import AppTest

    at = AppTest.from_file(str(APP), default_timeout=90).run()
    before = kpis(at)

    group = at.sidebar.multiselect[0].options[0]
    at.sidebar.multiselect[0].select(group).run()
    after = kpis(at)

    assert not at.exception
    assert after["Closed"] != before["Closed"]


def test_queries_match_the_csv_files():
    import pandas as pd

    from app import queries

    csv_total = pd.read_csv(queries.SAMPLE_DIR / "fct_productivity_daily.csv")["closed"].sum()
    first, last = queries.date_bounds()
    totals = queries.kpis(first, last, [])
    assert totals["closed"] == pytest.approx(csv_total)


def test_default_period_is_whole_weeks_and_weekly_charts_skip_partial_weeks():
    from datetime import timedelta

    from streamlit.testing.v1 import AppTest

    at = AppTest.from_file(str(APP), default_timeout=90).run()
    start, end = at.sidebar.date_input[0].value
    assert start.weekday() == 6  # Sunday
    assert end.weekday() == 5  # Saturday
    assert (end - start) == timedelta(days=27)

    from app import queries

    weekly = queries.weekly_quality(start, end, [])
    assert len(weekly) == 4
