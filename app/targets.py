"""Effective-dated targets for the daily report.

A target applies from `effective_from` until a later record for the same
metric and group replaces it, so changing a target never rewrites history.
`group` is "All" or one of the key-account splits ("KA" / "Non-KA").
Colour rule used by the report: at or above target is green, at or above
80% of the target amber, below that red. For metrics where lower is better
the comparison is inverted.
"""

from __future__ import annotations

from datetime import date

# metric: (label, higher_is_better, format)
METRICS = {
    "cph": ("CPH", True, "num1"),
    "conpd": ("ConPD", True, "num0"),
    "occupancy": ("Occupancy", True, "pct"),
    "utilization": ("Utilization", True, "pct"),
    "csat": ("CSAT (score ≥ 4)", True, "pct"),
    "fcr": ("First-contact resolution", True, "pct"),
    "resolved_24h": ("24h resolution rate", True, "pct"),
    "on_time": ("On-time attendance", True, "pct"),
}

# (metric, group, effective_from, target)
RECORDS = [
    ("cph", "KA", date(2026, 1, 1), 14.0),
    ("cph", "Non-KA", date(2026, 1, 1), 15.0),
    ("cph", "KA", date(2026, 10, 1), 16.0),
    ("cph", "Non-KA", date(2026, 10, 1), 16.5),
    ("conpd", "KA", date(2026, 1, 1), 95.0),
    ("conpd", "Non-KA", date(2026, 1, 1), 105.0),
    ("occupancy", "All", date(2026, 1, 1), 0.78),
    ("occupancy", "All", date(2026, 10, 1), 0.80),
    ("utilization", "All", date(2026, 1, 1), 0.85),
    ("csat", "All", date(2026, 1, 1), 0.85),
    ("fcr", "All", date(2026, 1, 1), 0.72),
    ("resolved_24h", "All", date(2026, 1, 1), 0.95),
    ("on_time", "All", date(2026, 1, 1), 0.95),
]


def target_for(metric: str, group: str, day: date) -> float | None:
    """Latest target whose effective date is on or before `day`."""
    best = None
    for name, scope, effective_from, value in RECORDS:
        if name != metric or scope not in (group, "All") or effective_from > day:
            continue
        # a group-specific record beats an "All" record, then the newer date wins
        rank = (scope == group, effective_from)
        if best is None or rank > best[0]:
            best = (rank, value)
    return None if best is None else best[1]


def rag(value: float | None, target: float | None, higher_is_better: bool = True) -> str:
    """'green' | 'amber' | 'red' | 'none'."""
    if value is None or target is None or value != value:
        return "none"
    if higher_is_better:
        if value >= target:
            return "green"
        return "amber" if value >= 0.8 * target else "red"
    if value <= target:
        return "green"
    return "amber" if value <= target / 0.8 else "red"
