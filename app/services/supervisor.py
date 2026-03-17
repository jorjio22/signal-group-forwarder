from __future__ import annotations

from dataclasses import asdict, dataclass
from threading import Lock
from time import time
from typing import Any

from app.db import Database
from app.domain.enums import AccountStatus, LogLevel
from app.logging import LogBus


@dataclass(frozen=True)
class SupervisorSnapshot:
    runtime_eligible: bool
    account_ready: bool
    groups_ready: bool
    settings_ready: bool
    last_reconcile_at_ms: int | None
    last_reconcile_reason: str | None
    worker_action: str
    worker_lifecycle_state: str
    worker_placeholder_state: str
    last_worker_event_at_ms: int | None


class SupervisorService:
    def __init__(self, db: Database, log_bus: LogBus) -> None:
        self._db = db
        self._log_bus = log_bus
        self._lock = Lock()
        self._worker: Any = None
        self._snapshot = SupervisorSnapshot(
            runtime_eligible=False,
            account_ready=False,
            groups_ready=False,
            settings_ready=False,
            last_reconcile_at_ms=None,
            last_reconcile_reason=None,
            worker_action="idle",
            worker_lifecycle_state="stopped",
            worker_placeholder_state="stopped",
            last_worker_event_at_ms=None,
        )

    def attach_worker(self, worker: Any) -> None:
        self._worker = worker

    def reconcile(self, reason: str) -> SupervisorSnapshot:
        action_to_take = "noop"
        with self._lock:
            account_state = self._db.get_account_state()
            settings = self._db.get_settings()
            worker_state = self._snapshot.worker_lifecycle_state

            account_ready = account_state.status == AccountStatus.LINKED
            groups_ready = bool(settings.source_group_id and settings.target_group_id)
            settings_ready = (
                settings.backlog_minutes >= 0
                and settings.rate_limit_seconds >= 0
                and bool(settings.quiet_start_local)
                and bool(settings.quiet_end_local)
            )
            runtime_eligible = account_ready and groups_ready and settings_ready
            worker_action = "noop"
            if runtime_eligible and worker_state == "stopped":
                worker_action = "start_worker"
                action_to_take = "start"
            elif (not runtime_eligible) and worker_state in {"starting", "running"}:
                worker_action = "stop_worker"
                action_to_take = "stop"
            elif runtime_eligible and worker_state in {"starting", "running"}:
                worker_action = "keep_running"
            elif account_ready and settings_ready:
                worker_action = "awaiting_group_selection"
            elif settings_ready:
                worker_action = "awaiting_linked_account"

            snapshot = SupervisorSnapshot(
                runtime_eligible=runtime_eligible,
                account_ready=account_ready,
                groups_ready=groups_ready,
                settings_ready=settings_ready,
                last_reconcile_at_ms=int(time() * 1000),
                last_reconcile_reason=reason,
                worker_action=worker_action,
                worker_lifecycle_state=worker_state,
                worker_placeholder_state=worker_state,
                last_worker_event_at_ms=self._snapshot.last_worker_event_at_ms,
            )
            self._snapshot = snapshot
            self._log_bus.publish(
                f"Supervisor reconcile: {reason} -> eligible={runtime_eligible}, action={worker_action}",
                LogLevel.INFO,
            )
        if action_to_take == "start" and self._worker is not None:
            self._worker.start()
        elif action_to_take == "stop" and self._worker is not None:
            self._worker.stop(f"supervisor_reconcile:{reason}")
        return snapshot

    def get_snapshot(self) -> dict[str, object]:
        with self._lock:
            return asdict(self._snapshot)

    def stop_worker(self, reason: str) -> SupervisorSnapshot:
        if self._worker is not None:
            self._worker.stop(reason)
        with self._lock:
            now_ms = int(time() * 1000)
            self._snapshot = SupervisorSnapshot(
                runtime_eligible=self._snapshot.runtime_eligible,
                account_ready=self._snapshot.account_ready,
                groups_ready=self._snapshot.groups_ready,
                settings_ready=self._snapshot.settings_ready,
                last_reconcile_at_ms=self._snapshot.last_reconcile_at_ms,
                last_reconcile_reason=self._snapshot.last_reconcile_reason,
                worker_action="worker_stopped",
                worker_lifecycle_state="stopped",
                worker_placeholder_state="stopped",
                last_worker_event_at_ms=now_ms,
            )
            self._log_bus.publish(f"Worker stopped: {reason}", LogLevel.INFO)
            return self._snapshot

    def restart_worker(self) -> SupervisorSnapshot:
        if self._worker is not None:
            self._worker.restart()
        return self.reconcile("manual_worker_restart")

    def report_worker_lifecycle(self, lifecycle_state: str) -> None:
        with self._lock:
            now_ms = int(time() * 1000)
            self._snapshot = SupervisorSnapshot(
                runtime_eligible=self._snapshot.runtime_eligible,
                account_ready=self._snapshot.account_ready,
                groups_ready=self._snapshot.groups_ready,
                settings_ready=self._snapshot.settings_ready,
                last_reconcile_at_ms=self._snapshot.last_reconcile_at_ms,
                last_reconcile_reason=self._snapshot.last_reconcile_reason,
                worker_action=self._snapshot.worker_action,
                worker_lifecycle_state=lifecycle_state,
                worker_placeholder_state=lifecycle_state,
                last_worker_event_at_ms=now_ms,
            )
