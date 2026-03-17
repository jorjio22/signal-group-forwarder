from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
MIGRATIONS_DIR = BASE_DIR / "migrations"
TEMPLATES_DIR = BASE_DIR / "app" / "web" / "templates"
STATIC_DIR = BASE_DIR / "app" / "web" / "static"


@dataclass(frozen=True)
class AppConfig:
    app_name: str
    debug: bool
    db_path: Path
    signal_config_dir: Path
    quiet_timezone: str
    backlog_minutes_default: int
    quiet_start_default: str
    quiet_end_default: str
    rate_limit_seconds_default: int
    live_log_tail_size: int
    link_device_name: str
    signal_cli_executable: str
    signal_cli_logout_timeout_seconds: int
    worker_stop_timeout_seconds: int


def load_config() -> AppConfig:
    DATA_DIR.mkdir(exist_ok=True)
    signal_config_dir = DATA_DIR / "signal-cli"
    signal_config_dir.mkdir(exist_ok=True)

    return AppConfig(
        app_name=os.getenv("APP_NAME", "Signal Forwarder"),
        debug=os.getenv("APP_DEBUG", "").lower() in {"1", "true", "yes"},
        db_path=Path(os.getenv("APP_DB_PATH", DATA_DIR / "app.sqlite")),
        signal_config_dir=Path(os.getenv("SIGNAL_CONFIG_DIR", signal_config_dir)),
        quiet_timezone=os.getenv("QUIET_TIMEZONE", "Europe/Kyiv"),
        backlog_minutes_default=int(os.getenv("BACKLOG_MINUTES_DEFAULT", "1")),
        quiet_start_default=os.getenv("QUIET_START_DEFAULT", "20:00"),
        quiet_end_default=os.getenv("QUIET_END_DEFAULT", "07:00"),
        rate_limit_seconds_default=int(os.getenv("RATE_LIMIT_SECONDS_DEFAULT", "30")),
        live_log_tail_size=int(os.getenv("LIVE_LOG_TAIL_SIZE", "100")),
        link_device_name=os.getenv("LINK_DEVICE_NAME", "TrueNAS Forwarder"),
        signal_cli_executable=os.getenv("SIGNAL_CLI_EXECUTABLE", "signal-cli"),
        signal_cli_logout_timeout_seconds=int(os.getenv("SIGNAL_CLI_LOGOUT_TIMEOUT_SECONDS", "20")),
        worker_stop_timeout_seconds=int(os.getenv("WORKER_STOP_TIMEOUT_SECONDS", "5")),
    )
