"""Refresh app/sample_data from a warehouse built with the demo data.

    python scripts/make_demo_data.py --days 56 --agents 40
    # ... load into PostgreSQL and run `dbt build` (see the README) ...
    python scripts/export_sample_data.py            # uses the DB_* variables

Only run it on a warehouse filled by make_demo_data.py: the sample is published
with the repository and must never contain real data.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path

import psycopg

TABLES = [
    "dim_date", "dim_agent", "fct_productivity_daily", "fct_attendance_daily",
    "fct_tickets_daily", "fct_csat_daily", "fct_backlog_daily",
    "fct_forecast_vs_actual", "mart_agent_weekly",
]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--out", type=Path, default=Path(__file__).resolve().parents[1] / "app" / "sample_data")
    parser.add_argument("--schema", default="marts")
    parser.add_argument(
        "--i-know-this-is-demo-data", action="store_true",
        help="required: confirms the warehouse only holds synthetic data",
    )
    args = parser.parse_args()

    if not args.i_know_this_is_demo_data:
        raise SystemExit("Refusing to export: pass --i-know-this-is-demo-data if the warehouse is synthetic.")

    args.out.mkdir(parents=True, exist_ok=True)
    with psycopg.connect(
        host=os.environ["DB_HOST"], port=int(os.getenv("DB_PORT", "5432")), dbname=os.environ["DB_NAME"],
        user=os.environ["DB_USER"], password=os.environ["DB_PASSWORD"], sslmode=os.getenv("DB_SSLMODE", "prefer"),
    ) as connection, connection.cursor() as cursor:
        for table in TABLES:
            target = args.out / f"{table}.csv"
            with target.open("wb") as handle, cursor.copy(
                f'COPY (SELECT * FROM "{args.schema}"."{table}" ORDER BY 1) TO STDOUT WITH CSV HEADER'
            ) as copy:
                for chunk in copy:
                    handle.write(bytes(chunk))
            print(f"{target.name}: {target.stat().st_size} bytes")


if __name__ == "__main__":
    main()
