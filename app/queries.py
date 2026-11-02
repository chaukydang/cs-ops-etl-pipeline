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


def _params(start: date, end: date, skills: list[str]) -> tuple[str, dict]:
    clause, extra = _skill_filter(skills)
    return clause, {"start": start, "end": end, **extra}


def kpis(start: date, end: date, skills: list[str]) -> dict:
    clause, params = _params(start, end, skills)

    prod = query(
        f"""
        select sum(closed) as closed,
               sum(closed) * 1.0 / nullif(sum(productivity_hrs), 0) as cph,
               sum(busy_hrs) * 1.0 / nullif(sum(online_hrs), 0)     as occupancy
        from marts.fct_productivity_daily
        where business_date between %(start)s and %(end)s {clause}
        """,
        params,
    ).iloc[0]
    tickets = query(
        f"""
        select sum(tickets) as created,
               sum(fcr_tickets) * 1.0 / nullif(sum(tickets), 0) as fcr,
               sum(resolved_24h_tickets) * 1.0 / nullif(sum(closed_tickets), 0) as resolved_24h,
               sum(avg_first_response_hrs * tickets) * 60.0 / nullif(sum(tickets), 0) as first_response_min
        from marts.fct_tickets_daily
        where create_date between %(start)s and %(end)s {clause}
        """,
        params,
    ).iloc[0]
    csat = query(
        f"""
        select sum(satisfied) * 1.0 / nullif(sum(responses), 0) as csat
        from marts.fct_csat_daily
        where survey_date between %(start)s and %(end)s {clause}
        """,
        params,
    ).iloc[0]
    attendance = query(
        """
        select 1 - sum(late_count) * 1.0 / nullif(sum(attendance_count), 0) as on_time
        from marts.fct_attendance_daily
        where schedule_date between %(start)s and %(end)s
        """,
        params,
    ).iloc[0]
    return {
        "created": tickets["created"],
        "closed": prod["closed"],
        "cph": prod["cph"],
        "occupancy": prod["occupancy"],
        "csat": csat["csat"],
        "fcr": tickets["fcr"],
        "resolved_24h": tickets["resolved_24h"],
        "first_response_min": tickets["first_response_min"],
        "on_time": attendance["on_time"],
    }


def daily_flow(start: date, end: date, skills: list[str]) -> pd.DataFrame:
    """Tickets created vs tickets closed by agents, per day."""
    clause, params = _params(start, end, skills)
    created = query(
        f"""
        select create_date as day, sum(tickets) as created
        from marts.fct_tickets_daily
        where create_date between %(start)s and %(end)s {clause}
        group by 1
        """,
        params,
    )
    closed = query(
        f"""
        select business_date as day, sum(closed) as closed
        from marts.fct_productivity_daily
        where business_date between %(start)s and %(end)s {clause}
        group by 1
        """,
        params,
    )
    return created.merge(closed, on="day", how="outer").sort_values("day").fillna(0)


def weekly_productivity(start: date, end: date, skills: list[str]) -> pd.DataFrame:
    clause, params = _params(start, end, skills)
    return query(
        f"""
        select (business_date - extract(dow from business_date)::int) as week_start,
               segment,
               sum(closed) * 1.0 / nullif(sum(productivity_hrs), 0) as cph,
               sum(busy_hrs) * 1.0 / nullif(sum(online_hrs), 0) as occupancy,
               sum(closed) as closed,
               sum(productivity_hrs) as productivity_hrs
        from marts.fct_productivity_daily
        where business_date between %(start)s and %(end)s {clause}
        group by 1, 2 order by 1
        """,
        params,
    )


PRODUCTIVITY_DIMENSIONS = {"tenure": "a.tenure", "tier": "a.tier", "team": "a.department"}


def productivity_by(dimension: str, start: date, end: date, skills: list[str]) -> pd.DataFrame:
    column = PRODUCTIVITY_DIMENSIONS[dimension]  # whitelist: never interpolate user input
    clause, params = _params(start, end, skills)
    clause = clause.replace("skill_group", "f.skill_group")
    return query(
        f"""
        select {column} as {dimension},
               count(distinct f.agent_key) as agents,
               sum(f.closed) * 1.0 / nullif(sum(f.productivity_hrs), 0) as cph,
               sum(f.busy_hrs) * 1.0 / nullif(sum(f.online_hrs), 0) as occupancy
        from marts.fct_productivity_daily f
        join marts.dim_agent a using (agent_key)
        where f.business_date between %(start)s and %(end)s {clause}
        group by 1 order by 1
        """,
        params,
    )


def weekly_hours(start: date, end: date, skills: list[str]) -> pd.DataFrame:
    """Where paid time goes: busy, idle while online, and non-production time."""
    clause, params = _params(start, end, skills)
    return query(
        f"""
        select (business_date - extract(dow from business_date)::int) as week_start,
               sum(busy_hrs) as busy,
               sum(online_hrs) - sum(busy_hrs) as idle,
               sum(non_production_hrs) as non_production
        from marts.fct_productivity_daily
        where business_date between %(start)s and %(end)s {clause}
        group by 1 order by 1
        """,
        params,
    )


def weekly_quality(start: date, end: date, skills: list[str]) -> pd.DataFrame:
    clause, params = _params(start, end, skills)
    tickets = query(
        f"""
        select (create_date - extract(dow from create_date)::int) as week_start,
               sum(fcr_tickets) * 1.0 / nullif(sum(tickets), 0) as fcr,
               sum(resolved_24h_tickets) * 1.0 / nullif(sum(closed_tickets), 0) as resolved_24h
        from marts.fct_tickets_daily
        where create_date between %(start)s and %(end)s {clause}
        group by 1
        """,
        params,
    )
    csat = query(
        f"""
        select (survey_date - extract(dow from survey_date)::int) as week_start,
               sum(satisfied) * 1.0 / nullif(sum(responses), 0) as csat
        from marts.fct_csat_daily
        where survey_date between %(start)s and %(end)s {clause}
        group by 1
        """,
        params,
    )
    return tickets.merge(csat, on="week_start", how="outer").sort_values("week_start")


def quality_by_group(start: date, end: date) -> pd.DataFrame:
    params = {"start": start, "end": end}
    return query(
        """
        with t as (
            select skill_group,
                   sum(tickets) as tickets,
                   sum(fcr_tickets) * 1.0 / nullif(sum(tickets), 0) as fcr,
                   sum(resolved_24h_tickets) * 1.0 / nullif(sum(closed_tickets), 0) as resolved_24h,
                   sum(avg_first_response_hrs * tickets) * 60.0 / nullif(sum(tickets), 0) as first_response_min,
                   sum(avg_resolution_hrs * tickets) / nullif(sum(tickets), 0) as resolution_hrs
            from marts.fct_tickets_daily
            where create_date between %(start)s and %(end)s
            group by 1
        ), c as (
            select skill_group,
                   sum(responses) as responses,
                   sum(satisfied) * 1.0 / nullif(sum(responses), 0) as csat
            from marts.fct_csat_daily
            where survey_date between %(start)s and %(end)s
            group by 1
        )
        select t.skill_group, t.tickets, c.csat, t.fcr, t.resolved_24h,
               t.first_response_min, t.resolution_hrs, c.responses
        from t left join c using (skill_group)
        order by t.skill_group
        """,
        params,
    )


def daily_csat(start: date, end: date, skills: list[str]) -> pd.DataFrame:
    clause, params = _params(start, end, skills)
    return query(
        f"""
        select survey_date as day,
               sum(satisfied) * 1.0 / nullif(sum(responses), 0) as csat,
               sum(responses) as responses
        from marts.fct_csat_daily
        where survey_date between %(start)s and %(end)s {clause}
        group by 1 order by 1
        """,
        params,
    )


def backlog(start: date, end: date) -> pd.DataFrame:
    return query(
        """
        select backlog_date as day, user_type, open_tickets, aged_over_24h, aged_over_72h, closed
        from marts.fct_backlog_daily
        where backlog_date between %(start)s and %(end)s order by 1
        """,
        {"start": start, "end": end},
    )


def forecast(start: date, end: date, skills: list[str]) -> pd.DataFrame:
    clause, params = _params(start, end, skills)
    return query(
        f"""
        select business_date as day,
               sum(forecast_traffic) as forecast,
               sum(actual_traffic)   as actual,
               sum(forecast_fte)     as required_fte,
               sum(scheduled_fte)    as scheduled_fte
        from marts.fct_forecast_vs_actual
        where business_date between %(start)s and %(end)s {clause}
        group by 1 order by 1
        """,
        params,
    )


def forecast_by_group(start: date, end: date) -> pd.DataFrame:
    return query(
        """
        select skill_group,
               sum(forecast_traffic) as forecast,
               sum(actual_traffic) as actual,
               sum(abs(actual_traffic - forecast_traffic)) * 1.0 / nullif(sum(actual_traffic), 0) as wape,
               avg(fte_gap) as avg_fte_gap
        from marts.fct_forecast_vs_actual
        where business_date between %(start)s and %(end)s
        group by 1 order by 1
        """,
        {"start": start, "end": end},
    )


def weeks() -> list[date]:
    return query("select distinct week_start from marts.mart_agent_weekly order by 1 desc")[
        "week_start"
    ].tolist()


def agent_scorecard(week_start: date, show_email: bool) -> pd.DataFrame:
    who = "a.agent_email" if show_email else "left(a.agent_key, 8)"
    return query(
        f"""
        select {who} as agent, a.department as team, a.tier, a.tenure,
               w.closed, w.cph, w.occupancy, w.on_time_rate, w.csat_pct as csat
        from marts.mart_agent_weekly w
        join marts.dim_agent a using (agent_key)
        where w.week_start = %(week)s
        order by w.cph desc
        """,
        {"week": week_start},
    )


def freshness() -> pd.DataFrame:
    """Newest date available in each fact, so readers can see how current the report is."""
    return query(
        """
        select 'Productivity' as dataset, max(business_date) as latest from marts.fct_productivity_daily
        union all select 'Tickets', max(create_date) from marts.fct_tickets_daily
        union all select 'CSAT', max(survey_date) from marts.fct_csat_daily
        union all select 'Attendance', max(schedule_date) from marts.fct_attendance_daily
        union all select 'Backlog', max(backlog_date) from marts.fct_backlog_daily
        union all select 'Forecast', max(business_date) from marts.fct_forecast_vs_actual
        """
    )


def recent_runs(limit: int = 30) -> pd.DataFrame:
    if sample_mode():
        raise RuntimeError("no run history in sample mode")
    schema = os.getenv("DB_SCHEMA", "Service")
    return query(
        f'select finished_at, stage, source, status, rows, duration_s, error '
        f'from "{schema}".pipeline_runs order by id desc limit %(n)s',
        {"n": limit},
    )
