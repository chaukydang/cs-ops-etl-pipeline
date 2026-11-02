"""Run the Streamlit script against the real marts (needs a warehouse built by dbt)."""

import os
from pathlib import Path

import pytest

pytest.importorskip("streamlit")

APP = Path(__file__).resolve().parents[2] / "app" / "streamlit_app.py"


@pytest.fixture()
def marts_available():
    if not os.getenv("DB_HOST"):
        pytest.skip("DB_HOST not set")
    import psycopg

    from app import queries as data

    try:
        with data.connect() as connection, connection.cursor() as cursor:
            cursor.execute("select to_regclass('marts.mart_agent_weekly')")
            if cursor.fetchone()[0] is None:
                pytest.skip("marts not built")
    except psycopg.OperationalError:
        pytest.skip("database not reachable")


def test_dashboard_renders_without_errors(marts_available):
    from streamlit.testing.v1 import AppTest

    at = AppTest.from_file(str(APP), default_timeout=60).run()
    assert not at.exception, [e.value for e in at.exception]
    assert "kpi-value" in "".join(m.value for m in at.markdown)  # KPI strip rendered
    assert at.tabs  # tabs rendered
