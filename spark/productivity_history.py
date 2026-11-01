"""Build long-term productivity history from the daily Parquet archive.

Every daily download covers a rolling window (the last ~5 weeks), so the
archive holds the same business date many times, sometimes with corrected
numbers. This job:

  1. reads all `dt=` snapshots of cph_details,
  2. keeps, for each agent / date / segment / skill group, the row from the
     newest snapshot (so late corrections win),
  3. writes the de-duplicated history partitioned by month,
  4. writes weekly agent trends with a rolling 4-week CPH, and monthly CPH by
     tenure band.

    python -m spark.productivity_history --archive-dir data/archive --out-dir data/lake
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path

from pyspark.sql import DataFrame, SparkSession, Window
from pyspark.sql import functions as F

from modules.database.csv_loader import CsvDatabaseLoader

SOURCE = "cph_details"
DEDUPE_KEY = ["agent_email", "business_date", "segment", "agent_primary_skill_group_name"]
NUMERIC = [
    "close",
    "contact_new",
    "paid_hours",
    "online_hrs",
    "busy_hrs",
    "productivity_numerator_hrs",
]


def read_snapshots(spark: SparkSession, archive_dir: Path, source: str = SOURCE) -> DataFrame:
    base = archive_dir / source
    df = (
        spark.read.option("basePath", str(base))
        .parquet(str(base / "dt=*" / f"{source}.parquet"))
    )

    # same header normalisation as the PostgreSQL loader, so names match the DB
    original = [c for c in df.columns if c != "dt"]
    renamed = CsvDatabaseLoader.normalize_headers(original)
    for old, new in zip(original, renamed):
        df = df.withColumnRenamed(old, new)
    return df


def clean(df: DataFrame) -> DataFrame:
    def text(name: str) -> F.Column:
        col = F.trim(F.col(name))
        return F.when((col == "") | (col == "NULL"), None).otherwise(col)

    out = (
        df.withColumn("dt", F.to_date("dt"))
        .withColumn("agent_email", F.lower(text("agent_email")))
        .withColumn("business_date", F.expr("try_cast(business_date as date)"))
        .withColumn("segment", text("segment"))
        .withColumn("tenure", text("tenure"))
        .withColumn(
            "agent_primary_skill_group_name", text("agent_primary_skill_group_name")
        )
    )
    for name in NUMERIC:
        out = out.withColumn(name, F.coalesce(F.expr(f"try_cast(`{name}` as double)"), F.lit(0.0)))
    return out.where(F.col("business_date").isNotNull() & F.col("agent_email").isNotNull())


def dedupe_latest(df: DataFrame) -> DataFrame:
    window = Window.partitionBy(*DEDUPE_KEY).orderBy(F.col("dt").desc())
    return (
        df.withColumn("_rn", F.row_number().over(window))
        .where(F.col("_rn") == 1)
        .drop("_rn")
    )


def weekly_trend(history: DataFrame) -> DataFrame:
    weekly = (
        history.withColumn(
            "week_start", F.date_sub("business_date", F.dayofweek("business_date") - 1)
        )
        .groupBy("agent_email", "week_start")
        .agg(
            F.sum("close").alias("closed"),
            F.sum("paid_hours").alias("paid_hours"),
            F.sum("productivity_numerator_hrs").alias("productivity_hrs"),
        )
        .withColumn("cph", F.col("closed") / F.when(F.col("productivity_hrs") > 0, F.col("productivity_hrs")))
    )

    # rolling window of the agent's last 4 weeks that have data
    rolling = (
        Window.partitionBy("agent_email").orderBy("week_start").rowsBetween(-3, 0)
    )
    return (
        weekly.withColumn("rolling_closed", F.sum("closed").over(rolling))
        .withColumn("rolling_hrs", F.sum("productivity_hrs").over(rolling))
        .withColumn(
            "cph_4w",
            F.col("rolling_closed") / F.when(F.col("rolling_hrs") > 0, F.col("rolling_hrs")),
        )
        .drop("rolling_closed", "rolling_hrs")
    )


def tenure_monthly(history: DataFrame) -> DataFrame:
    return (
        history.withColumn("month", F.date_trunc("month", "business_date").cast("date"))
        .groupBy("month", "tenure")
        .agg(
            F.countDistinct("agent_email").alias("agents"),
            F.sum("close").alias("closed"),
            F.sum("productivity_numerator_hrs").alias("productivity_hrs"),
        )
        .withColumn("cph", F.col("closed") / F.when(F.col("productivity_hrs") > 0, F.col("productivity_hrs")))
    )


def run(archive_dir: Path, out_dir: Path) -> dict[str, int]:
    spark = (
        SparkSession.builder.appName("productivity_history")
        .config("spark.sql.session.timeZone", "Asia/Ho_Chi_Minh")
        .config("spark.sql.sources.partitionOverwriteMode", "dynamic")
        # the default of 200 shuffle partitions is far too many for this volume
        .config("spark.sql.shuffle.partitions", os.getenv("SPARK_SHUFFLE_PARTITIONS", "8"))
        .getOrCreate()
    )
    try:
        history = dedupe_latest(clean(read_snapshots(spark, archive_dir))).cache()

        (
            history.withColumn("month", F.date_format("business_date", "yyyy-MM"))
            .write.mode("overwrite")
            .partitionBy("month")
            .parquet(str(out_dir / "productivity_history"))
        )
        trend = weekly_trend(history)
        trend.write.mode("overwrite").parquet(str(out_dir / "agent_weekly_trend"))
        cohort = tenure_monthly(history)
        cohort.write.mode("overwrite").parquet(str(out_dir / "tenure_monthly"))

        return {
            "history_rows": history.count(),
            "weekly_rows": trend.count(),
            "tenure_rows": cohort.count(),
        }
    finally:
        spark.stop()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--archive-dir", type=Path, default=Path("data/archive"))
    parser.add_argument("--out-dir", type=Path, default=Path("data/lake"))
    args = parser.parse_args()
    print(run(args.archive_dir.resolve(), args.out_dir.resolve()))


if __name__ == "__main__":
    main()
