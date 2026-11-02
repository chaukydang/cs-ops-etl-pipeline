"""Daily pipeline as a Prefect flow.

    dashboard --\\
                 +--> archive --> load_postgres --> dbt_build --> monitor
    lark -------/         \\
                           +--> spark_history

Every task runs the same CLI you would run by hand (`python main.py --module
...`), so a failed task can be reproduced in a terminal. A task whose upstream
failed is not run, which means a bad download never reaches the database.

    python -m flows.cs_ops_etl          # serve: runs every day at 07:00
    python -m flows.cs_ops_etl --once   # run once now
"""

from __future__ import annotations

import os
import subprocess
import sys
import threading
from pathlib import Path

from prefect import flow, get_run_logger, task
from prefect.runtime import flow_run
from prefect.schedules import Cron

PROJECT_DIR = Path(os.getenv("PIPELINE_HOME", Path(__file__).resolve().parents[1]))
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

DBT_BIN = os.getenv("DBT_BIN", "dbt")
SPARK_PYTHON = os.getenv("SPARK_PYTHON", sys.executable)

MINUTES = 60

# name -> (command, timeout in seconds)
STAGES: dict[str, tuple[list[str], int]] = {
    "dashboard": ([sys.executable, "main.py", "--module", "dashboard"], 45 * MINUTES),
    "lark": ([sys.executable, "main.py", "--module", "lark"], 45 * MINUTES),
    "archive": ([sys.executable, "main.py", "--module", "archive"], 45 * MINUTES),
    "load_postgres": (
        [sys.executable, "main.py", "--module", "database", "--action", "load"],
        45 * MINUTES,
    ),
    "dbt_build": (
        [DBT_BIN, "build", "--project-dir", "dbt", "--profiles-dir", "dbt"],
        30 * MINUTES,
    ),
    "spark_history": (
        [
            SPARK_PYTHON, "-m", "spark.productivity_history",
            "--archive-dir", "data/archive", "--out-dir", "data/lake",
        ],
        60 * MINUTES,
    ),
    "monitor": ([sys.executable, "main.py", "--module", "monitor"], 10 * MINUTES),
}


class StageFailed(RuntimeError):
    pass


def execute(name: str, command: list[str], timeout: int, env: dict[str, str]) -> None:
    """Run one stage, streaming its output into the Prefect log."""
    logger = get_run_logger()
    process = subprocess.Popen(
        command,
        cwd=PROJECT_DIR,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        errors="replace",
    )
    # The output loop blocks while the process is silent, so the timeout is a
    # watchdog that kills the process instead of a wait() after the loop.
    timed_out = threading.Event()

    def kill() -> None:
        timed_out.set()
        process.kill()

    watchdog = threading.Timer(timeout, kill)
    watchdog.start()
    try:
        assert process.stdout is not None
        for line in process.stdout:
            logger.info("[%s] %s", name, line.rstrip())
        code = process.wait()
    finally:
        watchdog.cancel()
        if process.poll() is None:
            process.kill()

    if timed_out.is_set():
        raise StageFailed(f"{name} timed out after {max(timeout // 60, 1)} min")
    if code != 0:
        raise StageFailed(f"{name} exited with code {code}")


def notify_task_failure(task, task_run, state) -> None:
    """Runs after the last retry has failed."""
    from modules.core.env_loader import get_optional_env
    from modules.dashboard.notifier import LarkNotifier

    LarkNotifier(get_optional_env("LARK_WEBHOOK_URL")).send_error(
        title=f"Pipeline task failed: {task_run.name}",
        message=str(state.message or state.name),
        details={"flow_run": flow_run.name, "run_id": flow_run.id},
    )


@task(
    task_run_name="{name}",
    retries=2,
    retry_delay_seconds=10 * MINUTES,
    on_failure=[notify_task_failure],
)
def run_stage(name: str) -> str:
    command, timeout = STAGES[name]
    env = {**os.environ, "PIPELINE_RUN_ID": str(flow_run.id)}
    execute(name, command, timeout, env)
    return name


@flow(name="cs-ops-etl", log_prints=True)
def cs_ops_etl() -> list[str]:
    dashboard = run_stage.submit("dashboard")
    lark = run_stage.submit("lark")
    archive = run_stage.submit("archive", wait_for=[dashboard, lark])
    load = run_stage.submit("load_postgres", wait_for=[archive])
    dbt = run_stage.submit("dbt_build", wait_for=[load])
    spark = run_stage.submit("spark_history", wait_for=[archive])
    monitor = run_stage.submit("monitor", wait_for=[dbt])

    futures = {
        "dashboard": dashboard, "lark": lark, "archive": archive,
        "load_postgres": load, "dbt_build": dbt, "spark_history": spark,
        "monitor": monitor,
    }

    # a task whose upstream failed never runs, so only the root failures matter
    failed = []
    for name, future in futures.items():
        future.wait()
        state = future.state
        if not state.is_completed():
            failed.append(f"{name} ({state.name})")

    if failed:
        raise StageFailed("not completed: " + ", ".join(failed))
    return list(futures)


def main() -> None:
    if "--once" in sys.argv:
        cs_ops_etl()
        return

    cs_ops_etl.serve(
        name="daily",
        schedule=Cron("0 7 * * *", timezone="Asia/Ho_Chi_Minh"),
        tags=["etl", "cs-ops"],
    )


if __name__ == "__main__":
    main()
