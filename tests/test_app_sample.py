"""The dashboard in demo mode: no database, only the bundled sample CSVs."""

from pathlib import Path

import pytest

pytest.importorskip("streamlit")
pytest.importorskip("duckdb")

APP = Path(__file__).resolve().parents[1] / "app" / "streamlit_app.py"


@pytest.fixture(autouse=True)
def no_database(monkeypatch):
    monkeypatch.delenv("DB_HOST", raising=False)
    monkeypatch.setenv("SAMPLE_DATA", "1")


def test_demo_dashboard_renders_with_numbers():
    from streamlit.testing.v1 import AppTest

    at = AppTest.from_file(str(APP), default_timeout=90).run()

    assert not at.exception, [e.value for e in at.exception]
    assert len(at.metric) == 6
    assert any("Demo mode" in i.value for i in at.info)
    values = {m.label: m.value for m in at.metric}
    assert values["Tickets closed"] not in ("-", "0")
    assert values["CPH"] != "-"


def test_skill_group_filter_changes_the_numbers():
    from streamlit.testing.v1 import AppTest

    at = AppTest.from_file(str(APP), default_timeout=90).run()
    before = {m.label: m.value for m in at.metric}

    group = at.sidebar.multiselect[0].options[0]
    at.sidebar.multiselect[0].select(group).run()
    after = {m.label: m.value for m in at.metric}

    assert not at.exception
    assert after["Tickets closed"] != before["Tickets closed"]


def test_queries_match_the_csv_files():
    import pandas as pd

    from app import queries

    csv_total = pd.read_csv(queries.SAMPLE_DIR / "fct_productivity_daily.csv")["closed"].sum()
    first, last = queries.date_bounds()
    totals = queries.kpis(first, last, [])
    assert totals["closed"] == pytest.approx(csv_total)
