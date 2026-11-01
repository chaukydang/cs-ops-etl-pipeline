"""Daily DAG: dashboard + lark in parallel, then archive (quality check +
Parquet), then PostgreSQL load, then dbt (staging, marts, tests). Each task calls the same CLI used locally,
so a failed task can be reproduced with `python main.py --module <name>`.
"""

from __future__ import annotations

import os
from datetime import timedelta

import pendulum
from airflow import DAG
from airflow.operators.bash import BashOperator

PROJECT_DIR = os.getenv("PIPELINE_HOME", "/opt/airflow/pipeline")

default_args = {
    "owner": "data",
    "retries": 2,
    "retry_delay": timedelta(minutes=10),
}

with DAG(
    dag_id="cs_ops_etl",
    description="Aeolus + Lark -> Parquet archive -> PostgreSQL",
    start_date=pendulum.datetime(2026, 11, 1, tz="Asia/Ho_Chi_Minh"),
    schedule="0 7 * * *",
    catchup=False,
    max_active_runs=1,
    default_args=default_args,
    tags=["etl", "cs-ops"],
) as dag:

    def stage(task_id: str, module: str, extra: str = "") -> BashOperator:
        return BashOperator(
            task_id=task_id,
            bash_command=f"cd {PROJECT_DIR} && python main.py --module {module} {extra}",
            # downloads are a few minutes at most; anything longer is stuck
            execution_timeout=timedelta(minutes=45),
        )

    dashboard = stage("dashboard", "dashboard")
    lark = stage("lark", "lark")
    archive = stage("archive", "archive")
    load = stage("load_postgres", "database", "--action load")

    # dbt lives in its own virtualenv (see Dockerfile) to keep its dependencies
    # away from Airflow's pinned ones.
    dbt_build = BashOperator(
        task_id="dbt_build",
        bash_command=(
            f"cd {PROJECT_DIR} && "
            "/home/airflow/dbt-venv/bin/dbt build --project-dir dbt --profiles-dir dbt"
        ),
        execution_timeout=timedelta(minutes=30),
    )

    [dashboard, lark] >> archive >> load >> dbt_build
