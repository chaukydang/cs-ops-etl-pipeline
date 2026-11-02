"""Customer service operations report, on top of the dbt marts.

    streamlit run app/streamlit_app.py
"""

from __future__ import annotations

import os
import sys
from datetime import timedelta
from pathlib import Path

import pandas as pd
import streamlit as st

# works both inside the repository and when this folder is deployed on its own
sys.path.insert(0, str(Path(__file__).resolve().parent))

import charts  # noqa: E402
import daily_report  # noqa: E402
import queries as data  # noqa: E402

st.set_page_config(page_title="CS Operations Report", layout="wide")

# make the tab bar read as navigation: larger labels, a filled selected tab, a visible bar underneath
st.markdown(
    """
    <style>
    [role="tablist"] { gap: 6px; padding: 6px; background: #eef3fb; border-radius: 10px; border: 0; }
    [role="tab"] { height: 42px; padding: 0 18px; border-radius: 8px; background: transparent; }
    [role="tab"] p { font-size: 1.02rem; font-weight: 600; color: #3b4a5f; }
    [role="tab"]:hover { background: #dce8f8; }
    [role="tab"][aria-selected="true"] { background: #2a78d6; box-shadow: 0 1px 3px rgba(42,120,214,.35); }
    [role="tab"][aria-selected="true"] p { color: #ffffff; }
    [role="tab"] .react-aria-SelectionIndicator, [data-baseweb="tab-highlight"], [data-baseweb="tab-border"] { display: none; }
    </style>
    """,
    unsafe_allow_html=True,
)


@st.cache_data(ttl=300, show_spinner=False)
def cached(name: str, *args):
    return getattr(data, name)(*args)


def ts(frame: pd.DataFrame, *columns: str) -> pd.DataFrame:
    frame = frame.copy()
    for column in columns:
        frame[column] = pd.to_datetime(frame[column])
    return frame


def missing(value) -> bool:
    return value is None or value != value


def pct(value, digits: int = 1) -> str:
    return "-" if missing(value) else f"{float(value):.{digits}%}"


def num(value, digits: int = 0) -> str:
    return "-" if missing(value) else f"{float(value):,.{digits}f}"


def complete_weeks(frame: pd.DataFrame, column: str, period_start, period_end) -> pd.DataFrame:
    """Keep only weeks fully inside the period, so a partial week never looks like a drop."""
    week_start = frame[column].dt.date
    keep = (week_start >= period_start) & (week_start + timedelta(days=6) <= period_end)
    return frame[keep]


def delta_relative(cur, prev) -> str | None:
    if missing(cur) or missing(prev) or not prev:
        return None
    return f"{(float(cur) / float(prev) - 1):+.1%}"


def delta_points(cur, prev) -> str | None:
    if missing(cur) or missing(prev):
        return None
    return f"{(float(cur) - float(prev)) * 100:+.1f} pp"


def delta_units(unit: str, digits: int = 1):
    def build(cur, prev) -> str | None:
        if missing(cur) or missing(prev):
            return None
        return f"{float(cur) - float(prev):+.{digits}f} {unit}"

    return build


def status(ok: bool | None, target_text: str) -> str:
    """Status is always an icon plus a word, never colour alone."""
    if ok is None:
        return f"Target {target_text}"
    mark = ":green[✓ On target]" if ok else ":red[✕ Off target]"
    return f"{mark}  \nTarget {target_text}"


# ---------------------------------------------------------------- header + filters
st.title("Customer service operations report")

try:
    first_day, last_day = cached("date_bounds")
except Exception as error:  # noqa: BLE001
    st.error(f"Cannot read the marts schema. Run the pipeline and `dbt build` first.\n\n{error}")
    st.stop()

with st.sidebar:
    st.header("Filters")
    # default: the last four complete weeks (Sunday to Saturday)
    days_since_saturday = (last_day.weekday() - 5) % 7
    last_saturday = last_day - timedelta(days=days_since_saturday)
    default_end = last_saturday if last_saturday - timedelta(days=27) >= first_day else last_day
    default_start = max(first_day, default_end - timedelta(days=27))
    picked = st.date_input("Period", (default_start, default_end), min_value=first_day, max_value=last_day)
    start, end = (picked if len(picked) == 2 else (picked[0], picked[0]))
    skills = st.multiselect("Skill group", cached("skill_groups"))

    with st.expander("Targets"):
        t_csat = st.number_input("CSAT, at least (%)", 0.0, 100.0, 85.0, 0.5) / 100
        t_fcr = st.number_input("FCR, at least (%)", 0.0, 100.0, 72.0, 0.5) / 100
        t_res = st.number_input("Resolved in 24h, at least (%)", 0.0, 100.0, 95.0, 0.5) / 100
        t_cph = st.number_input("CPH, at least", 0.0, 60.0, 16.0, 0.5)
        t_occ = st.number_input("Occupancy, at least (%)", 0.0, 100.0, 80.0, 1.0) / 100
        t_ontime = st.number_input("On-time attendance, at least (%)", 0.0, 100.0, 95.0, 0.5) / 100
        t_frt = st.number_input("First response, at most (min)", 0.0, 600.0, 30.0, 1.0)
        st.caption("Targets are adjustable placeholders.")

span = (end - start).days + 1
prev_end = start - timedelta(days=1)
prev_start = prev_end - timedelta(days=span - 1)
has_previous = prev_start >= first_day

st.caption(
    f"Period {start:%d %b %Y} - {end:%d %b %Y} ({span} days)"
    + (f", compared with {prev_start:%d %b} - {prev_end:%d %b %Y}" if has_previous else "")
    + f" · data through {last_day:%d %b %Y}"
)

cur = cached("kpis", start, end, skills)
prev = cached("kpis", prev_start, prev_end, skills) if has_previous else {}

# ---------------------------------------------------------------- KPI cards
cards = [
    (
        "Tickets created", num(cur["created"]), delta_relative(cur["created"], prev.get("created")), False,
        f"Previous period  \n{num(prev.get('created'))}",
    ),
    (
        "Tickets closed", num(cur["closed"]), delta_relative(cur["closed"], prev.get("closed")), False,
        f"Previous period  \n{num(prev.get('closed'))}",
    ),
    (
        "CPH", num(cur["cph"], 1), delta_relative(cur["cph"], prev.get("cph")), False,
        status(None if missing(cur["cph"]) else cur["cph"] >= t_cph, f"≥ {t_cph:.1f}"),
    ),
    (
        "Occupancy", pct(cur["occupancy"]), delta_points(cur["occupancy"], prev.get("occupancy")), False,
        status(None if missing(cur["occupancy"]) else cur["occupancy"] >= t_occ, f"≥ {t_occ:.0%}"),
    ),
    (
        "CSAT", pct(cur["csat"]), delta_points(cur["csat"], prev.get("csat")), False,
        status(None if missing(cur["csat"]) else cur["csat"] >= t_csat, f"≥ {t_csat:.0%}"),
    ),
    (
        "First-contact resolution", pct(cur["fcr"]), delta_points(cur["fcr"], prev.get("fcr")), False,
        status(None if missing(cur["fcr"]) else cur["fcr"] >= t_fcr, f"≥ {t_fcr:.0%}"),
    ),
    (
        "Resolved within 24h", pct(cur["resolved_24h"]), delta_points(cur["resolved_24h"], prev.get("resolved_24h")), False,
        status(None if missing(cur["resolved_24h"]) else cur["resolved_24h"] >= t_res, f"≥ {t_res:.0%}"),
    ),
    (
        "First response (min)", num(cur["first_response_min"], 1),
        delta_units("min")(cur["first_response_min"], prev.get("first_response_min")), True,
        status(None if missing(cur["first_response_min"]) else cur["first_response_min"] <= t_frt, f"≤ {t_frt:.1f} min"),
    ),
    (
        "On-time attendance", pct(cur["on_time"]), delta_points(cur["on_time"], prev.get("on_time")), False,
        status(None if missing(cur["on_time"]) else cur["on_time"] >= t_ontime, f"≥ {t_ontime:.0%}"),
    ),
]
for row in (cards[:5], cards[5:]):
    columns = st.columns(len(row))
    for column, (label, value, delta, inverse, note) in zip(columns, row):
        with column, st.container(border=True):
            st.metric(label, value, delta, delta_color="inverse" if inverse else "normal")
            if note:
                st.caption(note)

SEGMENTS = ["IM", "Ticket"]
GROUPS = cached("skill_groups")

tab_daily, tab_overview, tab_prod, tab_quality, tab_backlog, tab_capacity, tab_agents, tab_status = st.tabs(
    ["Daily report", "Overview", "Productivity", "Quality", "Backlog", "Capacity", "Agents", "Data status"]
)

# ---------------------------------------------------------------- daily report (KA / Non-KA)
with tab_daily:
    st.caption(
        "Key accounts (KA, SPG) and non-key accounts (Non-KA, SPS). Columns: last 7 days, last four "
        "Sunday-Saturday weeks and month to date. ● at or above target · ▲ at least 80% of target · ■ below 80%."
    )
    report_end = min(end, last_day)
    window_start = max(first_day, report_end.replace(day=1) - timedelta(days=45))
    daily = cached("daily_metrics", window_start, report_end)
    keys = ["cph", "conpd", "occupancy", "utilization", "csat", "fcr", "resolved_24h"]
    for group, title in (("KA", "Key accounts (KA)"), ("Non-KA", "Non-key accounts (Non-KA)")):
        st.subheader(title)
        values, flags = daily_report.build_table(daily, group, report_end, keys)
        st.dataframe(daily_report.render(values, flags, group, report_end), width="stretch")

# ---------------------------------------------------------------- overview
with tab_overview:
    left, right = st.columns(2)

    flow = ts(cached("daily_flow", start, end, skills), "day")
    with left:
        st.subheader("Tickets created vs closed")
        if flow.empty:
            st.info("No data in this period.")
        else:
            long = flow.melt("day", ["created", "closed"], var_name="series", value_name="tickets")
            long["series"] = long["series"].map({"created": "Created", "closed": "Closed"})
            st.altair_chart(
                charts.line(long, "day", "tickets", series="series", order=["Created", "Closed"]),
                width="stretch",
            )

    backlog = ts(cached("backlog", start, end), "day")
    with right:
        st.subheader("Open backlog")
        if backlog.empty:
            st.info("No data in this period.")
        else:
            total = backlog.groupby("day", as_index=False)["open_tickets"].sum()
            st.altair_chart(charts.line(total, "day", "open_tickets", zero=True), width="stretch")
            st.caption("All skill groups; the backlog is not split by skill group in the source.")

    weekly_q = complete_weeks(ts(cached("weekly_quality", start, end, skills), "week_start"), "week_start", start, end)
    weekly_p = complete_weeks(ts(cached("weekly_productivity", start, end, skills), "week_start"), "week_start", start, end)
    c1, c2, c3 = st.columns(3)
    with c1:
        st.subheader("CSAT by week")
        if not weekly_q.empty:
            st.altair_chart(
                charts.line(weekly_q, "week_start", "csat", fmt=".1%", weekly=True, height=220,
                            target=t_csat, target_label=f"Target {t_csat:.0%}"),
                width="stretch",
            )
    with c2:
        st.subheader("First-contact resolution by week")
        if not weekly_q.empty:
            st.altair_chart(
                charts.line(weekly_q, "week_start", "fcr", fmt=".1%", weekly=True, height=220,
                            target=t_fcr, target_label=f"Target {t_fcr:.0%}"),
                width="stretch",
            )
    with c3:
        st.subheader("CPH by week")
        if not weekly_p.empty:
            total_cph = weekly_p.groupby("week_start", as_index=False).agg(
                closed=("closed", "sum"), hours=("productivity_hrs", "sum")
            )
            total_cph["cph"] = total_cph["closed"] / total_cph["hours"]
            st.altair_chart(
                charts.line(total_cph, "week_start", "cph", fmt=".1f", weekly=True, height=220,
                            target=t_cph, target_label=f"Target {t_cph:.0f}"),
                width="stretch",
            )

# ---------------------------------------------------------------- productivity
with tab_prod:
    weekly_p = complete_weeks(ts(cached("weekly_productivity", start, end, skills), "week_start"), "week_start", start, end)
    if weekly_p.empty:
        st.info("No complete week of productivity data in this period.")
    else:
        a, b = st.columns(2)
        with a:
            st.subheader("CPH by week and segment")
            st.altair_chart(
                charts.line(weekly_p, "week_start", "cph", series="segment", order=SEGMENTS, fmt=".1f", weekly=True),
                width="stretch",
            )
        with b:
            st.subheader("Occupancy by week and segment")
            st.altair_chart(
                charts.line(weekly_p, "week_start", "occupancy", series="segment", order=SEGMENTS, fmt=".1%", weekly=True),
                width="stretch",
            )

        hours = complete_weeks(ts(cached("weekly_hours", start, end, skills), "week_start"), "week_start", start, end)
        hours = hours.rename(columns={"busy": "Busy", "idle": "Idle while online", "non_production": "Breaks, training, meetings"})
        order = ["Busy", "Idle while online", "Breaks, training, meetings"]
        long = hours.melt("week_start", order, var_name="series", value_name="hours")
        st.subheader("Where paid time goes (hours per week)")
        st.altair_chart(
            charts.stacked_bars(long, "week_start", "hours", "series", order=order), width="stretch"
        )

        st.subheader("CPH by tenure, tier and team")
        c1, c2, c3 = st.columns(3)
        by_tenure = cached("productivity_by", "tenure", start, end, skills)
        by_tier = cached("productivity_by", "tier", start, end, skills)
        by_team = cached("productivity_by", "team", start, end, skills)
        tenure_order = ["<90", "91-180", "180-270", "271-360", ">361"]
        y_max = max(float(f["cph"].max()) for f in (by_tenure, by_tier, by_team)) * 1.15  # same scale on all three
        with c1:
            st.caption("Tenure (days)")
            st.altair_chart(charts.bars(by_tenure, "tenure", "cph", order=tenure_order, fmt=".1f", y_max=y_max), width="stretch")
        with c2:
            st.caption("Tier")
            st.altair_chart(charts.bars(by_tier, "tier", "cph", fmt=".1f", y_max=y_max), width="stretch")
        with c3:
            st.caption("Team")
            st.altair_chart(charts.bars(by_team, "team", "cph", fmt=".1f", y_max=y_max), width="stretch")

# ---------------------------------------------------------------- quality
with tab_quality:
    csat_daily = ts(cached("daily_csat", start, end, skills), "day")
    if csat_daily.empty:
        st.info("No survey responses in this period.")
    else:
        csat_daily["satisfied"] = csat_daily["csat"] * csat_daily["responses"]
        window = csat_daily["satisfied"].rolling(7, min_periods=3).sum() / csat_daily["responses"].rolling(7, min_periods=3).sum()
        csat_daily["csat_7d"] = window
        a, b = st.columns(2)
        with a:
            st.subheader("CSAT, 7-day rolling")
            st.altair_chart(
                charts.line(csat_daily.dropna(subset=["csat_7d"]), "day", "csat_7d", fmt=".1%",
                            target=t_csat, target_label=f"Target {t_csat:.0%}"),
                width="stretch",
            )
        with b:
            st.subheader("Survey responses per day")
            st.altair_chart(charts.line(csat_daily, "day", "responses", zero=True), width="stretch")

    weekly_q = complete_weeks(ts(cached("weekly_quality", start, end, skills), "week_start"), "week_start", start, end)
    if not weekly_q.empty:
        c1, c2 = st.columns(2)
        with c1:
            st.subheader("First-contact resolution by week")
            st.altair_chart(
                charts.line(weekly_q, "week_start", "fcr", fmt=".1%", weekly=True,
                            target=t_fcr, target_label=f"Target {t_fcr:.0%}"),
                width="stretch",
            )
        with c2:
            st.subheader("Resolved within 24h by week")
            st.altair_chart(
                charts.line(weekly_q, "week_start", "resolved_24h", fmt=".1%", weekly=True,
                            target=t_res, target_label=f"Target {t_res:.0%}"),
                width="stretch",
            )

    st.subheader("By skill group")
    by_group = cached("quality_by_group", start, end)
    if not by_group.empty:
        st.dataframe(
            by_group,
            hide_index=True,
            width="stretch",
            column_config={
                "skill_group": "Skill group",
                "tickets": st.column_config.NumberColumn("Tickets", format="localized", width="small"),
                "csat": st.column_config.ProgressColumn("CSAT", format="percent", min_value=0, max_value=1),
                "fcr": st.column_config.ProgressColumn("FCR", format="percent", min_value=0, max_value=1),
                "resolved_24h": st.column_config.ProgressColumn("Resolved 24h", format="percent", min_value=0, max_value=1),
                "first_response_min": st.column_config.NumberColumn("1st response (min)", format="%.1f", width="small"),
                "resolution_hrs": st.column_config.NumberColumn("Resolution (h)", format="%.1f", width="small"),
                "responses": st.column_config.NumberColumn("Responses", format="localized", width="small"),
            },
        )

# ---------------------------------------------------------------- backlog
with tab_backlog:
    backlog = ts(cached("backlog", start, end), "day")
    if backlog.empty:
        st.info("No backlog data in this period.")
    else:
        per_day = backlog.groupby("day", as_index=False)[["open_tickets", "aged_over_24h", "aged_over_72h"]].sum()
        latest = per_day.iloc[-1]
        peak = per_day.loc[per_day["open_tickets"].idxmax()]
        m1, m2, m3 = st.columns(3)
        m1.metric("Open tickets, latest day", num(latest["open_tickets"]))
        m2.metric("Older than 24h, latest day", num(latest["aged_over_24h"]))
        m3.metric("Peak in period", num(peak["open_tickets"]))
        m3.caption(f"on {peak['day']:%d %b}")

        st.subheader("Open tickets by user type")
        st.altair_chart(
            charts.stacked_area(backlog, "day", "open_tickets", "user_type", order=["Seller", "Creator", "Buyer"]),
            width="stretch",
        )
        st.subheader("Aged tickets")
        aged = per_day.melt("day", ["aged_over_24h", "aged_over_72h"], var_name="series", value_name="tickets")
        aged["series"] = aged["series"].map({"aged_over_24h": "Older than 24h", "aged_over_72h": "Older than 72h"})
        st.altair_chart(
            charts.line(aged, "day", "tickets", series="series", order=["Older than 24h", "Older than 72h"], zero=True),
            width="stretch",
        )

# ---------------------------------------------------------------- capacity
with tab_capacity:
    fc = ts(cached("forecast", start, end, skills), "day")
    if fc.empty:
        st.info("No forecast data in this period.")
    else:
        error = (fc["actual"] - fc["forecast"]).abs().sum() / max(fc["actual"].sum(), 1)
        bias = (fc["actual"].sum() - fc["forecast"].sum()) / max(fc["forecast"].sum(), 1)
        m1, m2 = st.columns(2)
        m1.metric("Forecast error (WAPE)", pct(error))
        m2.metric("Bias (actual vs forecast)", f"{bias:+.1%}")

        a, b = st.columns(2)
        with a:
            st.subheader("Forecast vs actual traffic")
            traffic = fc.melt("day", ["forecast", "actual"], var_name="series", value_name="traffic")
            traffic["series"] = traffic["series"].map({"forecast": "Forecast", "actual": "Actual"})
            st.altair_chart(charts.line(traffic, "day", "traffic", series="series", order=["Forecast", "Actual"]), width="stretch")
        with b:
            st.subheader("Required vs scheduled FTE")
            fte = fc.melt("day", ["required_fte", "scheduled_fte"], var_name="series", value_name="fte")
            fte["series"] = fte["series"].map({"required_fte": "Required", "scheduled_fte": "Scheduled"})
            st.altair_chart(charts.line(fte, "day", "fte", series="series", order=["Required", "Scheduled"], fmt=",.1f"), width="stretch")

        st.subheader("By skill group")
        st.dataframe(
            cached("forecast_by_group", start, end),
            hide_index=True,
            width="stretch",
            column_config={
                "skill_group": "Skill group",
                "forecast": st.column_config.NumberColumn("Forecast", format="localized"),
                "actual": st.column_config.NumberColumn("Actual", format="localized"),
                "wape": st.column_config.NumberColumn("Error (WAPE)", format="percent"),
                "avg_fte_gap": st.column_config.NumberColumn("Avg FTE gap", format="%.1f"),
            },
        )

# ---------------------------------------------------------------- agents
with tab_agents:
    available = [w for w in cached("weeks") if w + timedelta(days=6) <= last_day]
    if not available:
        st.info("No weekly agent data yet.")
    else:
        show_email = os.getenv("SHOW_AGENT_EMAIL", "0") == "1"
        f1, f2, f3, f4 = st.columns(4)
        week = f1.selectbox("Week starting", available)
        board = cached("agent_scorecard", week, show_email)
        team = f2.multiselect("Team", sorted(board["team"].dropna().unique()))
        tier = f3.multiselect("Tier", sorted(board["tier"].dropna().unique()))
        tenure = f4.multiselect("Tenure", ["<90", "91-180", "180-270", "271-360", ">361"])
        if team:
            board = board[board["team"].isin(team)]
        if tier:
            board = board[board["tier"].isin(tier)]
        if tenure:
            board = board[board["tenure"].isin(tenure)]

        st.caption(f"{len(board)} agents")
        st.dataframe(
            board,
            hide_index=True,
            width="stretch",
            column_config={
                "agent": "Agent",
                "team": "Team",
                "tier": "Tier",
                "tenure": "Tenure",
                "closed": st.column_config.NumberColumn("Closed", format="%d"),
                "cph": st.column_config.ProgressColumn("CPH", format="%.1f", min_value=0, max_value=max(float(board["cph"].max() or 1), 1)),
                "occupancy": st.column_config.ProgressColumn("Occupancy", format="percent", min_value=0, max_value=1),
                "on_time_rate": st.column_config.ProgressColumn("On-time", format="percent", min_value=0, max_value=1),
                "csat": st.column_config.ProgressColumn("CSAT", format="percent", min_value=0, max_value=1),
            },
        )
        if not show_email:
            st.caption("Agents are shown by an anonymised id.")

# ---------------------------------------------------------------- data status
with tab_status:
    freshness = cached("freshness").copy()
    newest = pd.to_datetime(freshness["latest"]).max()
    freshness["Latest date"] = pd.to_datetime(freshness["latest"]).dt.strftime("%d %b %Y")
    freshness["Days behind newest"] = (newest - pd.to_datetime(freshness["latest"])).dt.days
    freshness["Status"] = freshness["Days behind newest"].map(lambda d: "● Current" if d <= 1 else "▲ Behind")
    st.subheader("Data freshness")
    st.dataframe(
        freshness[["dataset", "Latest date", "Days behind newest", "Status"]].rename(columns={"dataset": "Dataset"}),
        hide_index=True,
        width="stretch",
    )

    st.subheader("How this report is built")
    st.markdown(
        "- Dashboard exports and Lark sheets are downloaded and checked every morning.\n"
        "- Raw files are archived as Parquet and loaded into the warehouse; a re-download replaces only its own date window.\n"
        "- dbt cleans and deduplicates the data, builds the dimension and fact tables and runs reconciliation tests.\n"
        "- This report reads the fact tables."
    )

    if not data.sample_mode():
        st.subheader("Recent pipeline runs")
        try:
            st.dataframe(cached("recent_runs"), width="stretch", hide_index=True)
        except Exception:  # noqa: BLE001
            st.info("No run history yet (the table is created on the first database load).")

if data.sample_mode():
    st.divider()
    st.caption("Source: sample dataset (synthetic). Figures are illustrative and do not describe any real operation.")
