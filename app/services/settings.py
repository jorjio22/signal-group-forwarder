from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from app.db import Database
from app.domain.enums import LogLevel
from app.logging import LogBus
from app.services.supervisor import SupervisorService


@dataclass(frozen=True)
class SettingsUpdate:
    backlog_minutes: int
    quiet_start_local: str
    quiet_end_local: str
    rate_limit_seconds: int


class SettingsService:
    def __init__(self, db: Database, log_bus: LogBus, supervisor: SupervisorService) -> None:
        self._db = db
        self._log_bus = log_bus
        self._supervisor = supervisor

    def save(self, update: SettingsUpdate) -> None:
        self._validate(update)
        self._db.update_runtime_settings(
            backlog_minutes=update.backlog_minutes,
            quiet_start_local=update.quiet_start_local,
            quiet_end_local=update.quiet_end_local,
            rate_limit_seconds=update.rate_limit_seconds,
        )
        self._log_bus.publish("Saved runtime settings", LogLevel.INFO)
        self._supervisor.reconcile("settings_saved")

    def _validate(self, update: SettingsUpdate) -> None:
        if update.backlog_minutes < 0:
            raise RuntimeError("Backlog minutes must be greater than or equal to 0")
        if update.rate_limit_seconds < 0:
            raise RuntimeError("Rate limit seconds must be greater than or equal to 0")
        self._validate_hhmm(update.quiet_start_local, "Quiet start")
        self._validate_hhmm(update.quiet_end_local, "Quiet end")

    def _validate_hhmm(self, value: str, label: str) -> None:
        try:
            datetime.strptime(value, "%H:%M")
        except ValueError as exc:
            raise RuntimeError(f"{label} must be a valid HH:MM value") from exc
