from __future__ import annotations

from types import SimpleNamespace

from app.domain.enums import AccountStatus
from app.models.groups import SignalGroupRecord
from app.services.auth import AuthService
from app.services.signal_cli import SignalCliError


class FakeSupervisor:
    def __init__(self) -> None:
        self.stop_calls: list[str] = []
        self.reconcile_calls: list[str] = []

    def stop_worker(self, reason: str) -> None:
        self.stop_calls.append(reason)

    def reconcile(self, reason: str) -> dict[str, object]:
        self.reconcile_calls.append(reason)
        return {"runtime_eligible": False}

    def get_snapshot(self) -> dict[str, object]:
        return {"runtime_eligible": False}


class FailingSignalCli:
    def __init__(self) -> None:
        self._config = SimpleNamespace(worker_stop_timeout_seconds=1)

    def list_accounts(self, log=None):
        raise SignalCliError("timeout during listAccounts")


def test_logout_forced_local_reset_clears_account_linked_state(db, log_bus, monkeypatch):
    db.set_account_state(
        status=AccountStatus.LINKED,
        signal_account="+380000000000",
        phone_number="+380000000000",
        device_id=7,
        linked_at_ms=123,
        last_error="old error",
    )
    db.save_group_selection(
        source_group_id="source-group",
        source_group_name="Source",
        target_group_id="target-group",
        target_group_name="Target",
    )
    db.replace_known_groups(
        [SignalGroupRecord(group_id="source-group", group_name="Source", is_active=True, is_blocked=False)],
        last_seen_at_ms=1,
    )
    db.set_runtime_link_session("link-session")
    db.update_runtime_status(last_reconnect_at_ms=2, last_quiet_exit_at_ms=3, last_forward_confirmed_at_ms=4)
    db.add_forwarded_message(message_key="dedupe-key", source_group_id="source-group", message_ts_ms=10)

    supervisor = FakeSupervisor()
    auth = AuthService(db, log_bus, FailingSignalCli(), supervisor)
    monkeypatch.setattr("app.services.auth.sleep", lambda _: None)

    auth.logout()

    account_state = db.get_account_state()
    settings = db.get_settings()
    runtime_state = db.get_runtime_state()

    assert supervisor.stop_calls == ["logout_requested"]
    assert "logout_forced_local_reset" in supervisor.reconcile_calls
    assert account_state.status == AccountStatus.UNLINKED
    assert account_state.signal_account is None
    assert account_state.phone_number is None
    assert settings.source_group_id is None
    assert settings.target_group_id is None
    assert db.get_known_groups() == []
    assert runtime_state.link_session_id is None
    assert runtime_state.last_reconnect_at_ms is None
    assert runtime_state.last_quiet_exit_at_ms is None
    assert runtime_state.last_forward_confirmed_at_ms is None
    assert db.message_already_forwarded("dedupe-key") is False
