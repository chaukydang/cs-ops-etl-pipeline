from datetime import date

import pandas as pd
import pytest

pytest.importorskip("pyspark")

from modules.storage.parquet_archive import partition_path  # noqa: E402

HEADER = {
    "email": "Agent Email",
    "date": "业务日期｜Business Date",
    "segment": "Segment",
    "skill": "主技能组名称｜agent_primary_skill_group_name",
    "tenure": "Tenure",
    "close": "#close",
    "contact": "# Contact (new)",
    "paid": "Paid Hours",
    "online": "Online (hrs)",
    "busy": "Busy (hrs)",
    "prod": "Productivity_numerator (hrs)",
}


def write_snapshot(root, day, rows):
    frame = pd.DataFrame(
        [
            {
                HEADER["email"]: email,
                HEADER["date"]: business_date,
                HEADER["segment"]: "IM",
                HEADER["skill"]: "SG1",
                HEADER["tenure"]: "91-180",
                HEADER["close"]: str(closed),
                HEADER["contact"]: "1",
                HEADER["paid"]: "4",
                HEADER["online"]: "3",
                HEADER["busy"]: "1",
                HEADER["prod"]: str(prod),
            }
            for email, business_date, closed, prod in rows
        ]
    )
    target = partition_path(root, "cph_details", day)
    target.parent.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(target, index=False)


@pytest.fixture(scope="module")
def spark():
    from pyspark.sql import SparkSession

    session = (
        SparkSession.builder.master("local[1]")
        .appName("test")
        .config("spark.ui.enabled", "false")
        .config("spark.sql.shuffle.partitions", "1")
        .getOrCreate()
    )
    yield session
    session.stop()


def test_latest_snapshot_wins_and_trend(spark, tmp_path):
    from spark.productivity_history import (
        clean,
        dedupe_latest,
        read_snapshots,
        tenure_monthly,
        weekly_trend,
    )

    # 2026-10-26 (Mon) appears in both snapshots; the later one corrects 10 -> 20
    write_snapshot(tmp_path, date(2026, 10, 27), [("A@x.com", "2026-10-26", 10, 2), ("b@x.com", "2026-10-26", 5, 1)])
    write_snapshot(tmp_path, date(2026, 10, 28), [("a@x.com", "2026-10-26", 20, 2), ("a@x.com", "2026-10-27", 30, 3)])

    history = dedupe_latest(clean(read_snapshots(spark, tmp_path))).cache()
    rows = {(r.agent_email, str(r.business_date)): r.close for r in history.collect()}

    assert rows == {
        ("a@x.com", "2026-10-26"): 20.0,  # correction from the newest snapshot
        ("a@x.com", "2026-10-27"): 30.0,
        ("b@x.com", "2026-10-26"): 5.0,
    }

    week = [r for r in weekly_trend(history).collect() if r.agent_email == "a@x.com"]
    assert len(week) == 1
    assert str(week[0].week_start) == "2026-10-25"  # Sunday
    assert week[0].closed == 50.0
    assert week[0].cph == pytest.approx(10.0)  # 50 closed / 5 productivity hours

    cohort = tenure_monthly(history).collect()
    assert cohort[0].agents == 2
