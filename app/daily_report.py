"""Daily report tables: KA / Non-KA x metric, over the last 7 days, recent weeks and month to date."""

from __future__ import annotations

from datetime import date, timedelta

import pandas as pd
from targets import METRICS, rag, target_for

SUM_COLUMNS = [
    "closed", "contacts", "productivity_hrs", "available_hrs", "paid_hours", "agents",
    "tickets", "closed_tickets", "fcr_tickets", "resolved_24h_tickets", "responses", "satisfied",
]


def _ratio(num, den):
    return float(num) / float(den) if den and den == den else None


def metrics_for(rows: pd.DataFrame) -> dict[str, float | None]:
    """Headline metrics for a block of days (sums first, then ratios, never averages of ratios)."""
    total = {c: float(rows[c].fillna(0).sum()) if c in rows else 0.0 for c in SUM_COLUMNS}
    return {
        "cph": _ratio(total["closed"], total["productivity_hrs"]),
        "conpd": _ratio(total["contacts"], total["agents"]),
        "occupancy": _ratio(total["productivity_hrs"], total["available_hrs"]),
        "utilization": _ratio(total["available_hrs"], total["paid_hours"]),
        "csat": _ratio(total["satisfied"], total["responses"]),
        "fcr": _ratio(total["fcr_tickets"], total["tickets"]),
        "resolved_24h": _ratio(total["resolved_24h_tickets"], total["closed_tickets"]),
    }


def periods(end: date, weeks: int = 4) -> list[tuple[str, date, date]]:
    """Columns: the last 7 days, the last complete Sunday-Saturday weeks, and month to date."""
    cols = [(f"{d:%a %d}", d, d) for d in (end - timedelta(days=n) for n in range(6, -1, -1))]
    last_saturday = end - timedelta(days=(end.weekday() - 5) % 7)
    for n in range(weeks - 1, -1, -1):
        sat = last_saturday - timedelta(days=7 * n)
        sun = sat - timedelta(days=6)
        cols.append((f"Wk {sun:%d %b}", sun, sat))
    cols.append((f"MTD {end:%b}", end.replace(day=1), end))
    return cols


def build_table(daily: pd.DataFrame, group: str, end: date, metric_keys: list[str]) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Return (values, status) frames: rows = metrics, columns = periods."""
    frame = daily[daily["ka_group"] == group].copy()
    frame["day"] = pd.to_datetime(frame["day"]).dt.date
    values, status = {}, {}
    for label, start, stop in periods(end):
        block = frame[(frame["day"] >= start) & (frame["day"] <= stop)]
        computed = metrics_for(block)
        values[label], status[label] = {}, {}
        for key in metric_keys:
            value = computed.get(key)
            values[label][key] = value
            status[label][key] = rag(value, target_for(key, group, stop), METRICS[key][1])
    return pd.DataFrame(values), pd.DataFrame(status)


FORMATS = {"num0": "{:,.0f}", "num1": "{:,.1f}", "pct": "{:.1%}"}
ICONS = {"green": "●", "amber": "▲", "red": "■", "none": ""}
COLORS = {
    "green": "background-color: #d6efe3; color: #0b5c3b",
    "amber": "background-color: #fbe8c8; color: #7a4b00",
    "red": "background-color: #f8d4cf; color: #8a1f12",
    "none": "",
}


def render(values: pd.DataFrame, status: pd.DataFrame, group: str, end: date):
    """Pandas Styler. Colour is never the only signal: each cell carries a shape (● ▲ ■)."""
    text = values.copy().astype(object)
    for key in values.index:
        fmt = FORMATS[METRICS[key][2]]
        for col in values.columns:
            v = values.loc[key, col]
            text.loc[key, col] = "-" if v is None or v != v else f"{ICONS[status.loc[key, col]]} {fmt.format(v)}"
    text.index = [f"{METRICS[k][0]}  (target {_target_text(k, group, end)})" for k in values.index]
    styles = status.copy()
    styles.index = text.index
    styles = styles.apply(lambda col: col.map(COLORS))
    return text.style.apply(lambda _: styles, axis=None)


def _target_text(key: str, group: str, end: date) -> str:
    target = target_for(key, group, end)
    if target is None:
        return "n/a"
    return FORMATS[METRICS[key][2]].format(target)
