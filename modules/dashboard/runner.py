from __future__ import annotations

import json
import logging
import time
import traceback
from copy import deepcopy
from pathlib import Path
from typing import Any

from modules.core.env_loader import (
    get_optional_env,
    get_required_env,
    load_env_file,
)
from modules.dashboard.auth.dashboard_auth_manager import (
    AeolusAuthError,
    AeolusAuthManager,
)
from modules.dashboard.downloader import (
    AeolusDownloader,
    AeolusUnauthorizedError,
)
from modules.dashboard.notifier import LarkNotifier

# ============================================================
# PROJECT PATHS
# ============================================================

BASE_DIR = Path(__file__).resolve().parents[2]
ENV_FILE = BASE_DIR / ".env"
CONFIG_DIRECTORY = BASE_DIR / "configs" / "dashboard" / "sources"
DOWNLOAD_DIRECTORY = BASE_DIR / "downloads" / "dashboard"
LOG_DIRECTORY = BASE_DIR / "logs"
LOG_FILE = LOG_DIRECTORY / "dashboard_pipeline.log"

EXCLUDED_CONFIG_FILES = {
    "pipeline.json",
    "settings.json",
    "auth.json",
}

# Source lỗi vẫn tiếp tục chạy source tiếp theo.
CONTINUE_ON_ERROR = True

# Nếu server trả 401/403, refresh authentication và retry source đó một lần.
REFRESH_AUTH_ON_UNAUTHORIZED = True


# ============================================================
# LOGGING
# ============================================================


def setup_logging() -> None:
    LOG_DIRECTORY.mkdir(parents=True, exist_ok=True)

    logging.basicConfig(
        level=logging.INFO,
        format=(
            "%(asctime)s | "
            "%(levelname)s | "
            "%(name)s | "
            "%(message)s"
        ),
        handlers=[
            logging.FileHandler(LOG_FILE, encoding="utf-8"),
            logging.StreamHandler(),
        ],
        force=True,
    )


LOGGER = logging.getLogger("AeolusPipeline")


# ============================================================
# PATH / JSON HELPERS
# ============================================================


def resolve_project_path(configured_path: str) -> Path:
    path = Path(configured_path)

    if path.is_absolute():
        return path.resolve()

    return (BASE_DIR / path).resolve()


def load_json_config(file_path: Path) -> dict[str, Any]:
    try:
        with file_path.open("r", encoding="utf-8-sig") as file:
            config = json.load(file)
    except json.JSONDecodeError as error:
        raise ValueError(
            "JSON không hợp lệ | "
            f"file={file_path.name} | "
            f"line={error.lineno} | "
            f"column={error.colno} | "
            f"error={error.msg}"
        ) from error

    if not isinstance(config, dict):
        raise ValueError(
            f"Config phải là JSON object: {file_path}"
        )

    return config


def validate_source_config(
    config: dict[str, Any],
    file_path: Path,
) -> None:
    required_keys = (
        "metric_name",
        "endpoint",
        "payload",
    )

    missing_keys = [
        key
        for key in required_keys
        if key not in config
    ]

    if missing_keys:
        raise ValueError(
            "Source config thiếu key | "
            f"file={file_path.name} | "
            f"missing={missing_keys}"
        )

    metric_name = str(config.get("metric_name", "")).strip()
    endpoint = str(config.get("endpoint", "")).strip()

    if not metric_name:
        raise ValueError(
            f"metric_name đang trống | file={file_path.name}"
        )

    if not endpoint:
        raise ValueError(
            f"endpoint đang trống | file={file_path.name}"
        )

    if not isinstance(config.get("payload"), dict):
        raise ValueError(
            f"payload phải là JSON object | file={file_path.name}"
        )

    dynamic_date = config.get("dynamic_date", {})

    if isinstance(dynamic_date, dict) and dynamic_date.get("enabled", False):
        field_id = str(dynamic_date.get("field_id", "")).strip()

        if not field_id:
            raise ValueError(
                "dynamic_date.enabled=true nhưng thiếu field_id | "
                f"file={file_path.name}"
            )


def discover_source_configs() -> list[tuple[Path, dict[str, Any]]]:
    if not CONFIG_DIRECTORY.exists():
        raise FileNotFoundError(
            f"Không tìm thấy config directory: {CONFIG_DIRECTORY}"
        )

    config_files = sorted(
        file_path
        for file_path in CONFIG_DIRECTORY.glob("*.json")
        if file_path.name not in EXCLUDED_CONFIG_FILES
    )

    if not config_files:
        raise FileNotFoundError(
            f"Không tìm thấy file JSON trong {CONFIG_DIRECTORY}"
        )

    source_configs: list[tuple[Path, dict[str, Any]]] = []
    metric_names: set[str] = set()

    for file_path in config_files:
        config = load_json_config(file_path)

        if not config.get("enabled", True):
            LOGGER.info(
                "Source disabled | config=%s",
                file_path.name,
            )
            continue

        validate_source_config(config, file_path)

        metric_name = str(config["metric_name"]).strip()

        if metric_name in metric_names:
            raise ValueError(
                "Trùng metric_name | "
                f"metric={metric_name} | "
                f"file={file_path.name}"
            )

        metric_names.add(metric_name)

        output_config = config.setdefault("output", {})
        configured_directory = str(
            output_config.get("directory", "")
        ).strip()

        if not configured_directory or configured_directory == "downloads":
            output_config["directory"] = str(DOWNLOAD_DIRECTORY)
        else:
            output_config["directory"] = str(
                resolve_project_path(configured_directory)
            )

        source_configs.append((file_path, config))

    source_configs.sort(
        key=lambda item: (
            int(item[1].get("run_order", 999)),
            item[0].name.lower(),
        )
    )

    if not source_configs:
        raise RuntimeError("Không có source config nào đang enabled")

    return source_configs


# ============================================================
# ENVIRONMENT / AUTHENTICATION
# ============================================================


def load_environment() -> None:
    if not ENV_FILE.exists():
        raise FileNotFoundError(
            f"Không tìm thấy file .env: {ENV_FILE}"
        )

    load_env_file(ENV_FILE)


def create_auth_manager() -> AeolusAuthManager:
    dashboard_url = get_required_env("AEOLUS_DASHBOARD_URL")
    app_id = get_required_env("AEOLUS_APP_ID")

    chrome_driver_path = resolve_project_path(
        get_required_env("AEOLUS_CHROME_DRIVER_PATH")
    )

    lark_login_email = get_required_env("LARK_LOGIN_EMAIL")
    lark_login_password = get_required_env("LARK_LOGIN_PASSWORD")

    outlook_mail_url = (
        get_optional_env(
            "OUTLOOK_MAIL_URL",
            "https://outlook.office.com/mail/",
        )
        or "https://outlook.office.com/mail/"
    )

    outlook_email = get_required_env("OUTLOOK_EMAIL")
    outlook_password = get_required_env("OUTLOOK_PASSWORD")
    outlook_totp_secret = (
        get_optional_env("OUTLOOK_TOTP_SECRET", "")
        or ""
    )

    return AeolusAuthManager(
        dashboard_url=dashboard_url,
        app_id=app_id,
        chrome_driver_path=chrome_driver_path,
        project_root=BASE_DIR,
        lark_email=lark_login_email,
        lark_password=lark_login_password,
        outlook_mail_url=outlook_mail_url,
        outlook_email=outlook_email,
        outlook_password=outlook_password,
        outlook_totp_secret=outlook_totp_secret,
        page_timeout=90,
        element_timeout=20,
        transition_timeout=60,
        login_timeout=300,
        outlook_login_timeout=300,
        manual_mfa_timeout=300,
        otp_timeout=180,
        token_capture_timeout=120,
        headless=(get_optional_env("AEOLUS_HEADLESS", "false") or "false").lower()
        in ("1", "true", "yes"),
    )


def create_notifier() -> LarkNotifier:
    webhook_url = get_optional_env("LARK_WEBHOOK_URL", "") or ""
    return LarkNotifier(webhook_url=webhook_url)


def create_downloader(auth_context: Any) -> AeolusDownloader:
    return AeolusDownloader(
        open_api_token=auth_context.open_api_token,
        app_id=auth_context.app_id,
        cookies=auth_context.cookies,
        timeout=300,
        max_retries=2,
    )


# ============================================================
# DOWNLOAD HELPERS
# ============================================================


def download_source(
    downloader: AeolusDownloader,
    config_path: Path,
    config: dict[str, Any],
) -> Path:
    metric_name = str(config["metric_name"]).strip()

    LOGGER.info(
        "Source started | metric=%s | config=%s",
        metric_name,
        config_path.name,
    )

    started_at = time.monotonic()
    output_file = downloader.download_metric(deepcopy(config))
    elapsed = time.monotonic() - started_at

    LOGGER.info(
        "Source completed | metric=%s | output=%s | elapsed_seconds=%.2f",
        metric_name,
        output_file,
        elapsed,
    )

    return output_file


def download_source_with_auth_retry(
    auth_manager: AeolusAuthManager,
    downloader: AeolusDownloader,
    config_path: Path,
    config: dict[str, Any],
) -> Path:
    try:
        return download_source(
            downloader=downloader,
            config_path=config_path,
            config=config,
        )

    except AeolusUnauthorizedError:
        if not REFRESH_AUTH_ON_UNAUTHORIZED:
            raise

        LOGGER.warning(
            "Authentication expired | metric=%s | refreshing auth",
            config.get("metric_name"),
        )

        refreshed_context = auth_manager.refresh_auth()

        downloader.update_authentication(
            open_api_token=refreshed_context.open_api_token,
            cookies=refreshed_context.cookies,
        )

        return download_source(
            downloader=downloader,
            config_path=config_path,
            config=config,
        )


# ============================================================
# SUMMARY / NOTIFICATION
# ============================================================


def print_summary(
    completed_sources: list[dict[str, Any]],
    failed_sources: list[dict[str, Any]],
    elapsed_seconds: float,
) -> None:
    print("\n========================================")
    print("PIPELINE SUMMARY")
    print("========================================")
    print(f"Completed: {len(completed_sources)}")
    print(f"Failed: {len(failed_sources)}")
    print(f"Elapsed seconds: {elapsed_seconds:.2f}")

    if completed_sources:
        print("\nCompleted sources:")
        for result in completed_sources:
            print(
                "  [OK] "
                f"{result['metric_name']} -> "
                f"{result['output_file']} "
                f"({result['elapsed_seconds']:.2f}s)"
            )

    if failed_sources:
        print("\nFailed sources:")
        for result in failed_sources:
            print(
                "  [FAILED] "
                f"{result['metric_name']} | "
                f"{result['error_type']} | "
                f"{result['error']}"
            )

    print("========================================")


def send_summary_notification(
    notifier: LarkNotifier | None,
    completed_sources: list[dict[str, Any]],
    failed_sources: list[dict[str, Any]],
    elapsed_seconds: float,
) -> None:
    if notifier is None:
        return

    details = {
        "completed": str(len(completed_sources)),
        "failed": str(len(failed_sources)),
        "elapsed_seconds": f"{elapsed_seconds:.2f}",
    }

    if failed_sources:
        failed_names = ", ".join(
            str(item["metric_name"])
            for item in failed_sources
        )
        details["failed_sources"] = failed_names

        notifier.send_error(
            title="DashboardBatch Download Finished With Errors",
            message="Một hoặc nhiều Dashboard source download thất bại.",
            details=details,
        )
    else:
        notifier.send_info(
            title="DashboardBatch Download Completed",
            message="Tất cả Dashboard source đã được download thành công.",
            details=details,
        )


# ============================================================
# MAIN
# ============================================================


def main() -> None:
    setup_logging()

    pipeline_started_at = time.monotonic()
    auth_manager: AeolusAuthManager | None = None
    notifier: LarkNotifier | None = None

    completed_sources: list[dict[str, Any]] = []
    failed_sources: list[dict[str, Any]] = []

    try:
        # Phải load .env trước mọi lệnh get_required_env().
        load_environment()

        notifier = create_notifier()
        source_configs = discover_source_configs()

        LOGGER.info(
            "Pipeline started | enabled_sources=%s",
            len(source_configs),
        )

        print(f"[PIPELINE] Enabled sources={len(source_configs)}")

        for index, (config_path, config) in enumerate(
            source_configs,
            start=1,
        ):
            print(
                "[PIPELINE] "
                f"Source {index}/{len(source_configs)} | "
                f"{config['metric_name']} | {config_path.name}"
            )

        # Login/capture token một lần cho toàn bộ batch.
        auth_manager = create_auth_manager()
        auth_context = auth_manager.ensure_authenticated()

        LOGGER.info("Authentication completed")

        downloader = create_downloader(auth_context)

        for index, (config_path, config) in enumerate(
            source_configs,
            start=1,
        ):
            metric_name = str(config["metric_name"]).strip()
            source_started_at = time.monotonic()

            print(
                "\n[PIPELINE] "
                f"Running {index}/{len(source_configs)} | "
                f"Metric={metric_name}"
            )

            try:
                output_file = download_source_with_auth_retry(
                    auth_manager=auth_manager,
                    downloader=downloader,
                    config_path=config_path,
                    config=config,
                )

                completed_sources.append(
                    {
                        "metric_name": metric_name,
                        "config": config_path.name,
                        "output_file": str(output_file),
                        "elapsed_seconds": (
                            time.monotonic() - source_started_at
                        ),
                    }
                )

            except Exception as error:
                LOGGER.exception(
                    "Source failed | metric=%s | config=%s",
                    metric_name,
                    config_path.name,
                )

                failed_sources.append(
                    {
                        "metric_name": metric_name,
                        "config": config_path.name,
                        "error_type": type(error).__name__,
                        "error": str(error),
                        "elapsed_seconds": (
                            time.monotonic() - source_started_at
                        ),
                    }
                )

                print(
                    "[SOURCE FAILED] "
                    f"{metric_name} | "
                    f"{type(error).__name__}: {error}"
                )

                if not CONTINUE_ON_ERROR:
                    raise

        elapsed_seconds = time.monotonic() - pipeline_started_at

        print_summary(
            completed_sources=completed_sources,
            failed_sources=failed_sources,
            elapsed_seconds=elapsed_seconds,
        )

        send_summary_notification(
            notifier=notifier,
            completed_sources=completed_sources,
            failed_sources=failed_sources,
            elapsed_seconds=elapsed_seconds,
        )

        if failed_sources:
            LOGGER.error(
                "Pipeline completed with failures | completed=%s | failed=%s",
                len(completed_sources),
                len(failed_sources),
            )
        else:
            LOGGER.info(
                "Pipeline completed | completed=%s",
                len(completed_sources),
            )

    except KeyboardInterrupt:
        LOGGER.warning("Pipeline stopped manually")
        print("\n[PIPELINE STOPPED] Stopped manually by user.")

    except FileNotFoundError as error:
        LOGGER.exception("Required file was not found")

        if notifier is not None:
            notifier.send_error(
                title="Required File Not Found",
                message=str(error),
                details={"error_type": type(error).__name__},
            )

        print(f"\n[PIPELINE FAILED] {error}")

    except AeolusAuthError as error:
        LOGGER.exception("Dashboard authentication failed")

        if notifier is not None:
            notifier.send_error(
                title="Authentication Failed",
                message=str(error),
                details={"error_type": type(error).__name__},
            )

        print(f"\n[PIPELINE FAILED] Authentication error: {error}")

    except Exception as error:
        LOGGER.exception("Unhandled pipeline error")
        traceback_text = traceback.format_exc()

        if notifier is not None:
            notifier.send_error(
                title="Pipeline Failed",
                message=str(error),
                details={
                    "error_type": type(error).__name__,
                    "traceback": traceback_text[-1500:],
                },
            )

        print(
            "\n[PIPELINE FAILED] "
            f"{type(error).__name__}: {error}"
        )

    finally:
        if auth_manager is not None:
            try:
                auth_manager.close()
            except KeyboardInterrupt:
                print("[PIPELINE] Browser cleanup was interrupted")
            except Exception as cleanup_error:
                LOGGER.warning(
                    "Browser cleanup failed: %s",
                    cleanup_error,
                )

        print("[PIPELINE] Finished")


if __name__ == "__main__":
    main()
