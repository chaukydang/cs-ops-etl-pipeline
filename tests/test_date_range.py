from datetime import datetime

import pytest

from modules.dashboard.downloader import (
    AeolusDownloader,
    AeolusDownloadError,
)

calc = AeolusDownloader.calculate_date_range


def test_sunday_start_five_weeks():
    # 2026-10-27 is a Tuesday, its Sunday-based week starts 2026-10-25
    start, end = calc(
        weeks_back=5,
        week_start="sunday",
        now=datetime(2026, 10, 27, 9, 30),
    )
    assert start == datetime(2026, 9, 27, 0, 0, 0)
    assert end == datetime(2026, 10, 27, 23, 59, 59)


def test_monday_start_exclude_current_week():
    start, _ = calc(
        weeks_back=2,
        include_current_week=False,
        week_start="monday",
        now=datetime(2026, 10, 27, 9, 30),
    )
    assert start == datetime(2026, 10, 12, 0, 0, 0)


def test_invalid_arguments():
    with pytest.raises(AeolusDownloadError):
        calc(weeks_back=0)
    with pytest.raises(AeolusDownloadError):
        calc(week_start="friday")
