from __future__ import annotations

import argparse
from pathlib import Path

from modules.core.env_loader import load_env_file

BASE_DIR = Path(__file__).resolve().parent
ENV_FILE = BASE_DIR / ".env"


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Dashboard, Lark, and PostgreSQL data pipeline"
    )

    parser.add_argument(
        "--module",
        choices=(
            "dashboard",
            "lark",
            "archive",
            "database",
            "backfill",
            "monitor",
            "all",
        ),
        default="all",
        help=(
            "Module to run: dashboard, lark, archive, database, backfill, monitor, or all. "
            "The all option runs dashboard, lark, archive (quality check + "
            "Parquet), then database load."
        ),
    )

    parser.add_argument(
        "--source",
        default=None,
        help=(
            "Run one source only. Examples: ticket_details, "
            "ProductivityDataReportRaw, or ConvertRoster."
        ),
    )

    parser.add_argument(
        "--type",
        dest="source_type",
        default=None,
        help=(
            "Filter Lark sources by type. "
            "Examples: sheet_raw, base, transform."
        ),
    )

    parser.add_argument(
        "--action",
        choices=(
            "init",
            "load",
        ),
        default="load",
        help=(
            "Database action. init creates missing tables once. "
            "load validates existing tables and replaces their data."
        ),
    )

    parser.add_argument(
        "--from",
        dest="date_from",
        default=None,
        help="Backfill start date, YYYY-MM-DD (inclusive).",
    )
    parser.add_argument(
        "--to",
        dest="date_to",
        default=None,
        help="Backfill end date, YYYY-MM-DD (inclusive).",
    )
    parser.add_argument(
        "--chunk",
        choices=("day", "week", "month"),
        default="month",
        help="Backfill chunk size. Chunks that hit the export row limit are split.",
    )
    parser.add_argument(
        "--no-archive",
        action="store_true",
        help="Backfill: skip writing Parquet.",
    )
    parser.add_argument(
        "--keep-files",
        action="store_true",
        help="Backfill: keep downloaded chunk CSVs under downloads/backfill.",
    )

    return parser.parse_args()


def run_dashboard_module() -> bool:
    try:
        from modules.dashboard.runner import main as run_dashboard

        print()
        print("[PIPELINE] Starting dashboard module...")

        result = run_dashboard()

        # runner.main() reports problems in its return value instead of raising
        if result.get("fatal") or result.get("failed"):
            print(
                "[PIPELINE FAILED] Dashboard | "
                "failed sources={} | fatal={}".format(
                    len(result.get("failed", [])),
                    result.get("fatal"),
                )
            )

            return False

        print("[PIPELINE] Dashboard module completed.")
        return True

    except Exception as error:
        print(
            "[PIPELINE FAILED] Dashboard | "
            "{}: {}".format(
                type(error).__name__,
                error,
            )
        )

        return False


def run_lark_module(
    source_type: str | None,
    source_name: str | None,
) -> bool:
    try:
        from modules.lark.module_runner import LarkModuleRunner

        print()
        print("[PIPELINE] Starting Lark module...")

        result = LarkModuleRunner(
            BASE_DIR
        ).run(
            source_type=source_type,
            source_name=source_name,
        )

        failed = result.get(
            "failed",
            [],
        )

        if failed:
            print(
                "[PIPELINE FAILED] Lark | "
                "failed sources={}".format(
                    len(failed)
                )
            )

            return False

        print("[PIPELINE] Lark module completed.")
        return True

    except Exception as error:
        print(
            "[PIPELINE FAILED] Lark | "
            "{}: {}".format(
                type(error).__name__,
                error,
            )
        )

        return False


def run_archive_module(
    source_name: str | None,
) -> bool:
    try:
        from modules.storage.runner import ArchiveRunner

        print()
        print("[PIPELINE] Starting archive module...")

        result = ArchiveRunner(
            BASE_DIR
        ).run(
            source_name=source_name,
        )

        if result.get("failed"):
            print(
                "[PIPELINE FAILED] Archive | "
                "failed sources={}".format(
                    len(result["failed"])
                )
            )

            return False

        print("[PIPELINE] Archive module completed.")
        return True

    except Exception as error:
        print(
            "[PIPELINE FAILED] Archive | "
            "{}: {}".format(
                type(error).__name__,
                error,
            )
        )

        return False


def run_backfill_module(
    arguments: argparse.Namespace,
) -> bool:
    try:
        from datetime import date

        from modules.dashboard.backfill_runner import run as run_backfill

        if not arguments.date_from or not arguments.date_to:
            raise ValueError("backfill needs --from and --to (YYYY-MM-DD)")

        print()
        print("[PIPELINE] Starting backfill...")

        result = run_backfill(
            BASE_DIR,
            date.fromisoformat(arguments.date_from),
            date.fromisoformat(arguments.date_to),
            chunk=arguments.chunk,
            source=arguments.source,
            archive=not arguments.no_archive,
            keep_files=arguments.keep_files,
        )

        print(
            "[BACKFILL] completed windows={} failed={}".format(
                len(result["completed"]),
                len(result["failed"]),
            )
        )

        return not result["failed"]

    except Exception as error:
        print(
            "[PIPELINE FAILED] Backfill | "
            "{}: {}".format(
                type(error).__name__,
                error,
            )
        )

        return False


def run_monitor_module() -> bool:
    try:
        from modules.monitoring.runner import run as run_monitor

        print()
        print("[PIPELINE] Starting monitor...")

        issues = run_monitor(BASE_DIR)

        return not issues

    except Exception as error:
        print(
            "[PIPELINE FAILED] Monitor | "
            "{}: {}".format(
                type(error).__name__,
                error,
            )
        )

        return False


def run_database_module(
    action: str,
    source_name: str | None,
) -> bool:
    try:
        from modules.database.runner import DatabaseRunner

        print()
        print(
            "[PIPELINE] Starting database module | "
            "action={}...".format(action)
        )

        result = DatabaseRunner(
            BASE_DIR
        ).run(
            action=action,
            source_name=source_name,
        )

        failed = result.get(
            "failed",
            [],
        )

        if failed:
            print(
                "[PIPELINE FAILED] Database | "
                "failed sources={}".format(
                    len(failed)
                )
            )

            return False

        print("[PIPELINE] Database module completed.")
        return True

    except Exception as error:
        print(
            "[PIPELINE FAILED] Database | "
            "{}: {}".format(
                type(error).__name__,
                error,
            )
        )

        return False


def print_pipeline_header(
    arguments: argparse.Namespace,
) -> None:
    print("========================================")
    print("DATA PIPELINE")
    print("========================================")
    print("Project root: {}".format(BASE_DIR))
    print("Module: {}".format(arguments.module))

    if arguments.source:
        print(
            "Source: {}".format(
                arguments.source
            )
        )

    if arguments.source_type:
        print(
            "Source type: {}".format(
                arguments.source_type
            )
        )

    if arguments.module == "database":
        print(
            "Database action: {}".format(
                arguments.action
            )
        )

    print("========================================")


def print_pipeline_result(
    has_failure: bool,
) -> None:
    print()
    print("========================================")
    print("PIPELINE RESULT")
    print("========================================")

    if has_failure:
        print("Status: FAILED")
    else:
        print("Status: COMPLETED")

    print("========================================")


def main() -> None:
    arguments = parse_arguments()

    if not ENV_FILE.exists():
        raise FileNotFoundError(
            "Environment file not found: {}".format(
                ENV_FILE
            )
        )

    load_env_file(
        ENV_FILE
    )

    has_failure = False

    print_pipeline_header(
        arguments
    )

    if arguments.module == "dashboard":
        dashboard_ok = run_dashboard_module()
        has_failure = not dashboard_ok

    elif arguments.module == "lark":
        lark_ok = run_lark_module(
            source_type=arguments.source_type,
            source_name=arguments.source,
        )

        has_failure = not lark_ok

    elif arguments.module == "archive":
        archive_ok = run_archive_module(
            source_name=arguments.source,
        )

        has_failure = not archive_ok

    elif arguments.module == "monitor":
        has_failure = not run_monitor_module()

    elif arguments.module == "backfill":
        has_failure = not run_backfill_module(arguments)

    elif arguments.module == "database":
        database_ok = run_database_module(
            action=arguments.action,
            source_name=arguments.source,
        )

        has_failure = not database_ok

    elif arguments.module == "all":
        dashboard_ok = run_dashboard_module()

        if not dashboard_ok:
            has_failure = True

        lark_ok = run_lark_module(
            source_type=arguments.source_type,
            source_name=None,
        )

        if not lark_ok:
            has_failure = True

        archive_ok = False

        if dashboard_ok and lark_ok:
            archive_ok = run_archive_module(
                source_name=None,
            )

            if not archive_ok:
                has_failure = True

        if dashboard_ok and lark_ok and archive_ok:
            database_ok = run_database_module(
                action="load",
                source_name=None,
            )

            if not database_ok:
                has_failure = True

        else:
            print()
            print(
                "[PIPELINE SKIPPED] Database load was skipped "
                "because dashboard, Lark or archive failed."
            )

            has_failure = True

    print_pipeline_result(
        has_failure
    )

    if has_failure:
        raise SystemExit(1)


if __name__ == "__main__":
    main()