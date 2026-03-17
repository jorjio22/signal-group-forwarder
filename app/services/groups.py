from __future__ import annotations

from time import time

from app.db import Database
from app.domain.enums import AccountStatus, LogLevel
from app.logging import LogBus
from app.models.groups import KnownGroupRecord
from app.services.signal_cli import SignalCliAdapter, SignalCliError
from app.services.supervisor import SupervisorService


class GroupsService:
    def __init__(
        self,
        db: Database,
        log_bus: LogBus,
        signal_cli: SignalCliAdapter,
        supervisor: SupervisorService,
    ) -> None:
        self._db = db
        self._log_bus = log_bus
        self._signal_cli = signal_cli
        self._supervisor = supervisor

    def get_known_groups(self) -> list[KnownGroupRecord]:
        return self._db.get_known_groups()

    def refresh_groups(self) -> None:
        account_state = self._db.get_account_state()
        if account_state.status != AccountStatus.LINKED or not account_state.signal_account:
            raise RuntimeError("Link a Signal account before refreshing groups")

        try:
            groups = self._signal_cli.list_groups(account_state.signal_account)
        except SignalCliError as exc:
            self._log_bus.publish(f"Group refresh failed: {exc}", LogLevel.ERROR)
            raise RuntimeError(str(exc)) from exc

        self._db.replace_known_groups(groups, int(time() * 1000))
        self._log_bus.publish(f"Loaded {len(groups)} Signal groups", LogLevel.INFO)

    def save_selection(self, source_group_id: str, target_group_id: str) -> None:
        if not source_group_id or not target_group_id:
            raise RuntimeError("Both source and target groups are required")
        if source_group_id == target_group_id:
            raise RuntimeError("Source and target groups must be different")

        groups = {group.group_id: group for group in self._db.get_known_groups()}
        source = groups.get(source_group_id)
        target = groups.get(target_group_id)
        if source is None or target is None:
            raise RuntimeError("Refresh groups and select valid Signal groups before saving")

        self._db.save_group_selection(
            source_group_id=source.group_id,
            source_group_name=source.group_name,
            target_group_id=target.group_id,
            target_group_name=target.group_name,
        )
        self._supervisor.reconcile("groups_saved")
        self._log_bus.publish(
            f"Saved forwarding groups: {source.group_name} -> {target.group_name}",
            LogLevel.INFO,
        )
