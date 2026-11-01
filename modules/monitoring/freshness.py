from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone


@dataclass(frozen=True)
class Issue:
    source: str
    kind: str
    message: str

    def __str__(self) -> str:
        return f"{self.source} [{self.kind}] {self.message}"


def evaluate_lag(source: str, latest: date | None, today: date, max_lag_days: int) -> Issue | None:
    """Data is stale when its newest date is more than max_lag_days behind today."""
    if latest is None:
        return Issue(source, "empty", "table has no rows with a valid date")
    lag = (today - latest).days
    if lag > max_lag_days:
        return Issue(source, "stale", f"newest data is {latest} ({lag} days old, limit {max_lag_days})")
    return None


def evaluate_last_success(
    source: str, last: datetime | None, now: datetime, max_age_hours: float
) -> Issue | None:
    if last is None:
        return Issue(source, "never_loaded", "no successful load recorded")
    age = now - last
    if age > timedelta(hours=max_age_hours):
        hours = age.total_seconds() / 3600
        return Issue(source, "no_recent_load", f"last successful load {hours:.0f}h ago (limit {max_age_hours:.0f}h)")
    return None


def check(sources, latest_dates: dict, last_success: dict, today: date | None = None,
          now: datetime | None = None, max_age_hours: float = 36) -> list[Issue]:
    today = today or date.today()
    now = now or datetime.now(timezone.utc)
    issues: list[Issue] = []
    for source in sources:
        if source.load_mode == "incremental":
            issue = evaluate_lag(source.name, latest_dates.get(source.name), today, source.max_lag_days)
            if issue:
                issues.append(issue)
        issue = evaluate_last_success(source.name, last_success.get(source.name), now, max_age_hours)
        if issue:
            issues.append(issue)
    return issues
