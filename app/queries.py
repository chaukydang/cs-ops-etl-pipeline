"""Queries behind the dashboard. Everything reads from the dbt `marts` schema.

Two backends, same SQL:

- PostgreSQL, when the DB_* variables are set (the real warehouse);
- sample mode otherwise (or with SAMPLE_DATA=1): the CSV files in
  `sample_data/` are loaded into an in-memory DuckDB, so the app runs anywhere
  without a database, for example on Streamlit Community Cloud.
"""

from __future__ import annotations

import os
import re
import threading
from datetime import date
from decimal import Decimal
from pathlib import Path

import pandas as pd

SAMPLE_DIR = Path(__file__).resolve().parent / "sample_data"
_sample_lock = threading.Lock()
_sample_connection = None


def sample_mode() -> bool:
    return os.getenv("SAMPLE_DATA") == "1" or not os.getenv("DB_HOST")


def _sample():
    """One in-memory DuckDB per process, with the marts loaded from the sample CSVs."""
    global _sample_connection
    with _sample_lock:
        if _sample_connection is None:
            import duckdb

            connection = duckdb.connect()
            connection.execute("create schema marts")
            for csv_file in sorted(SAMPLE_DIR.glob("*.csv")):
                connection.execute(
                    f"create table marts.{csv_file.stem} as "
                    f"select * from read_csv_auto('{csv_file.as_posix()}')"
                )
            _sample_connection = connection
        return _sample_connection.cursor()


def connect():
    import psycopg

    return psycopg.connect(
        host=os.environ["DB_HOST"],
        port=int(os.getenv("DB_PORT", "5432")),
        dbname=os.environ["DB_NAME"],
        user=os.environ["DB_USER"],
        password=os.environ["DB_PASSWORD"],
        sslmode=os.getenv("DB_SSLMODE", "prefer"),
        connect_timeout=10,
    )


def query(sql: str, params: tuple | dict | None = None) -> pd.DataFrame:
    if sample_mode():
        # psycopg style %(name)s -> DuckDB style $name
        cursor = _sample()
        used = set(re.findall(r"%\((\w+)\)s", sql))
        # psycopg ignores parameters a statement does not use; DuckDB raises
        cursor.execute(
            re.sub(r"%\((\w+)\)s", r"$\1", sql),
            {k: v for k, v in (params or {}).items() if k in used},
        )
        frame = cursor.fetchdf()
        for column in frame.columns:
            if str(frame[column].dtype).startswith("datetime64"):
                frame[column] = frame[column].dt.date
        return frame

    with connect() as connection, connection.cursor() as cursor:
        cursor.execute(sql, params)
        columns = [c.name for c in cursor.description]
        frame = pd.DataFrame(cursor.fetchall(), columns=columns)

    # NUMERIC columns arrive as Decimal; charts need real floats
    for column in frame.columns:
        if frame[column].map(lambda v: isinstance(v, Decimal)).any():
            frame[column] = pd.to_numeric(frame[column])
    return frame


def date_bounds() -> tuple[date, date]:
    row = query("select min(date_day), max(date_day) from marts.dim_date").iloc[0]
    return row.iloc[0], row.iloc[1]


def skill_groups() -> list[str]:
    frame = query(
        "select distinct skill_group from marts.fct_productivity_daily "
        "where skill_group is not null order by 1"
    )
    return frame["skill_group"].tolist()


def _skill_filter(skills: list[str]) -> tuple[str, dict]:
    if not skills:
        return "", {}
    names = {f"skill{i}": name for i, name in enumerate(skills)}
    marks = ", ".join(f"%({key})s" for key in names)
    return f"and skill_group in ({marks})", names


def kpis(start: date, end: date, skills: list[str]) -> dict:
    clause, extra = _skill_filter(skills)
    params = {"start": start, "end": end, **extra}

    prod = query(
        f"""
        select sum(closed) as closed,
               sum(closed) / nullif(sum(productivity_hrs), 0) as cph,
               sum(busy_hrs) / nullif(sum(online_hrs), 0)     as occupancy
        from marts.fct_productivity_daily
        where business_date between %(start)s and %(end)s {clause}
        """,
        params,
    ).iloc[0]
    csat = query(
        f"""
        select sum(satisfied)::numeric / nullif(sum(responses), 0) as csat
        from marts.fct_csat_daily
        where survey_date between %(start)s and %(end)s {clause}
        """,
        params,
    ).iloc[0]
    tickets = query(
        f"""
        select sum(tickets) as tickets, sum(fcr_tickets)::numeric / nullif(sum(tickets), 0) as fcr
        from marts.fct_tickets_daily
        where create_date between %(start)s and %(end)s {clause}
        """,
        params,
    ).iloc[0]
    attendance = query(
        """
        select 1 - sum(late_count) / nullif(sum(attendance_count), 0) as on_time
        from marts.fct_attendance_daily
        where schedule_date between %(start)s and %(end)s
        """,
        params,
    ).iloc[0]
    return {
        "closed": prod["closed"],
        "cph": prod["cph"],
        "occupancy": prod["occupancy"],
        "csat": csat["csat"],
        "tickets": tickets["tickets"],
        "fcr": tickets["fcr"],
        "on_time": attendance["on_time"],
    }


def weekly_productivity(start: date, end: date, skills: list[str]) -> pd.DataFrame:
    clause, extra = _skill_filter(skills)
    return query(
        f"""
        select (business_date - extract(dow from business_date)::int) as week_start,
               segment,
               sum(closed) / nullif(sum(productivity_hrs), 0) as cph
        from marts.fct_productivity_daily
        where business_date between %(start)s and %(end)s {clause}
        group by 1, 2 order by 1
        """,
        {"start": start, "end": end, **extra},
    )


def daily_tickets(start: date, end: date, skills: list[str]) -> pd.DataFrame:
    clause, extra = _skill_filter(skills)
    return query(
        f"""
        select create_date, sum(tickets) as tickets, sum(closed_tickets) as closed_tickets
        from marts.fct_tickets_daily
        where create_date between %(start)s and %(end)s {clause}
        group by 1 order by 1
        """,
        {"start": start, "end": end, **extra},
    )


def daily_csat(start: date, end: date, skills: list[str]) -> pd.DataFrame:
    clause, extra = _skill_filter(skills)
    return query(
        f"""
        select survey_date, sum(satisfied)::numeric / nullif(sum(responses), 0) as csat_pct
        from marts.fct_csat_daily
        where survey_date between %(start)s and %(end)s {clause}
        group by 1 order by 1
        """,
        {"start": start, "end": end, **extra},
    )


def backlog(start: date, end: date) -> pd.DataFrame:
    return query(
        """
        select backlog_date, user_type, open_tickets
        from marts.fct_backlog_daily
        where backlog_date between %(start)s and %(end)s order by 1
        """,
        {"start": start, "end": end},
    )


def forecast(start: date, end: date, skills: list[str]) -> pd.DataFrame:
    clause, extra = _skill_filter(skills)
    return query(
        f"""
        select business_date,
               sum(forecast_traffic) as forecast,
               sum(actual_traffic)   as actual
        from marts.fct_forecast_vs_actual
        where business_date between %(start)s and %(end)s {clause}
        group by 1 order by 1
        """,
        {"start": start, "end": end, **extra},
    )


def agent_scorecard(week_start: date, show_email: bool) -> pd.DataFrame:
    who = "a.agent_email" if show_email else "left(a.agent_key, 8)"
    return query(
        f"""
        select {who} as agent, a.department, a.tier, a.tenure,
               w.closed, round(w.cph::numeric, 2) as cph,
               round(w.occupancy::numeric, 3) as occupancy,
               round(w.on_time_rate::numeric, 3) as on_time_rate,
               round(w.csat_pct::numeric, 3) as csat_pct
        from marts.mart_agent_weekly w
        join marts.dim_agent a using (agent_key)
        where w.week_start = %(week)s
        order by w.cph desc nulls last
        """,
        {"week": week_start},
    )


def weeks() -> list[date]:
    return query("select distinct week_start from marts.mart_agent_weekly order by 1 desc")[
        "week_start"
    ].tolist()


def recent_runs(limit: int = 30) -> pd.DataFrame:
    if sample_mode():
        raise RuntimeError("no run history in sample mode")
    schema = os.getenv("DB_SCHEMA", "Service")
    return query(
        f'select finished_at, stage, source, status, rows, duration_s, error '
        f'from "{schema}".pipeline_runs order by id desc limit %(n)s',
        {"n": limit},
    )
