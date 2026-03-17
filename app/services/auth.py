from __future__ import annotations

import secrets
import subprocess
import threading
from dataclasses import dataclass
from time import sleep, time

from app.bot_status import build_bot_status
from app.db import Database
from app.domain.enums import AccountStatus, LogLevel
from app.logging import LogBus
from app.services.qr import make_qr_data_uri
from app.services.signal_cli import SignalAccount, SignalCliAdapter, SignalCliError
from app.services.supervisor import SupervisorService


@dataclass
class LinkSession:
    session_id: str
    process: subprocess.Popen[str]
    status: str
    qr_uri: str | None
    started_at_ms: int
    last_error: str | None = None
    canceled: bool = False
    completion_handled: bool = False


class AuthService:
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
        self._lock = threading.Lock()
        self._logout_in_progress = False
        self._link_session: LinkSession | None = None

    def reconcile_account_state(self) -> None:
        with self._lock:
            self._reconcile_account_state_locked()

    def start_link(self) -> LinkSession:
        with self._lock:
            self._reconcile_link_session_locked()
            if self._link_session and self._link_session.status in {"starting", "waiting_for_scan"}:
                return self._link_session

            process = self._signal_cli.start_link_process()
            session = LinkSession(
                session_id=secrets.token_hex(8),
                process=process,
                status="starting",
                qr_uri=None,
                started_at_ms=int(time() * 1000),
            )
            self._link_session = session
            self._db.set_account_state(status=AccountStatus.LINKING, last_error=None)
            self._db.set_runtime_link_session(session.session_id)
            self._supervisor.reconcile("link_started")
            self._log_bus.publish("Started Signal link session", LogLevel.INFO)
            threading.Thread(target=self._capture_link_output, args=(session,), daemon=True).start()
            threading.Thread(target=self._capture_link_error, args=(session,), daemon=True).start()
            return session

    def cancel_link(self) -> None:
        with self._lock:
            if not self._link_session:
                self._db.set_account_state(status=AccountStatus.UNLINKED, last_error=None)
                self._db.set_runtime_link_session(None)
                return

            session = self._link_session
            session.canceled = True
            session.status = "canceled"
            if session.process.poll() is None:
                session.process.terminate()
            self._clear_link_session_locked()
            self._db.set_account_state(status=AccountStatus.UNLINKED, last_error=None)
            self._supervisor.reconcile("link_canceled")
            self._log_bus.publish("Canceled Signal link session", LogLevel.WARNING)

    def get_link_status(self) -> dict[str, object]:
        with self._lock:
            self._reconcile_link_session_locked()
            account_state = self._db.get_account_state()
            runtime_state = self._db.get_runtime_state()
            settings = self._db.get_settings()
            supervisor_snapshot = self._supervisor.get_snapshot()
            return {
                "account_status": account_state.status.value,
                "worker_state": runtime_state.worker_state.value,
                "jsonrpc_state": runtime_state.jsonrpc_state.value,
                "bot_status": build_bot_status(
                    account_state,
                    runtime_state,
                    settings,
                    bool(supervisor_snapshot["runtime_eligible"]),
                ),
                "link_session_id": runtime_state.link_session_id,
                "signal_account": account_state.signal_account,
                "phone_number": account_state.phone_number,
                "device_id": account_state.device_id,
                "last_error": account_state.last_error,
                "supervisor": supervisor_snapshot,
                "link": self._serialize_link_session_locked(),
            }

    def get_active_link_session(self) -> dict[str, object] | None:
        with self._lock:
            self._reconcile_link_session_locked()
            return self._serialize_link_session_locked()

    def _capture_link_output(self, session: LinkSession) -> None:
        assert session.process.stdout is not None
        for raw_line in session.process.stdout:
            line = raw_line.strip()
            if not line:
                continue
            with self._lock:
                if self._link_session is not session:
                    return
                if "sgnl://linkdevice" in line:
                    session.qr_uri = self._extract_qr_uri(line)
                    session.status = "waiting_for_scan"
                    self._log_bus.publish("Received Signal link QR URI", LogLevel.INFO)
        with self._lock:
            self._reconcile_link_session_locked()

    def _capture_link_error(self, session: LinkSession) -> None:
        assert session.process.stderr is not None
        for raw_line in session.process.stderr:
            line = raw_line.strip()
            if not line:
                continue
            with self._lock:
                if self._link_session is not session:
                    return
                session.last_error = line
                self._log_bus.publish(f"signal-cli link: {line}", LogLevel.WARNING)

    def _extract_qr_uri(self, line: str) -> str:
        marker = "sgnl://linkdevice"
        start = line.index(marker)
        return line[start:].strip()

    def _serialize_link_session_locked(self) -> dict[str, object] | None:
        if not self._link_session:
            return None
        return {
            "session_id": self._link_session.session_id,
            "status": self._link_session.status,
            "qr_uri": self._link_session.qr_uri,
            "qr_image": make_qr_data_uri(self._link_session.qr_uri) if self._link_session.qr_uri else None,
            "started_at_ms": self._link_session.started_at_ms,
            "last_error": self._link_session.last_error,
        }

    def _reconcile_link_session_locked(self) -> None:
        if not self._link_session:
            return
        session = self._link_session
        return_code = session.process.poll()
        if return_code is None or session.completion_handled:
            return

        session.completion_handled = True
        if session.canceled:
            self._clear_link_session_locked()
            return

        if return_code == 0:
            self._reconcile_account_state_locked()
            if self._db.get_account_state().status == AccountStatus.LINKED:
                self._log_bus.publish("Signal link completed successfully", LogLevel.INFO)
            else:
                self._db.set_account_state(
                    status=AccountStatus.ERROR,
                    last_error="Link command completed but no single linked account was detected",
                )
                self._log_bus.publish(
                    "Link completed without a usable linked account",
                    LogLevel.ERROR,
                )
        else:
            self._db.set_account_state(
                status=AccountStatus.ERROR,
                last_error=session.last_error or f"Link process exited with code {return_code}",
            )
            self._log_bus.publish("Signal link failed", LogLevel.ERROR)
        self._clear_link_session_locked()

    def _reconcile_account_state_locked(self) -> None:
        try:
            accounts = self._signal_cli.list_accounts()
        except SignalCliError as exc:
            self._db.set_account_state(status=AccountStatus.ERROR, last_error=str(exc))
            self._log_bus.publish(f"Account check failed: {exc}", LogLevel.ERROR)
            return

        if len(accounts) == 0:
            self._db.set_account_state(status=AccountStatus.UNLINKED, last_error=None)
            self._supervisor.reconcile("account_unlinked")
            return

        if len(accounts) > 1:
            self._db.set_account_state(
                status=AccountStatus.ERROR,
                last_error="Multiple Signal accounts detected; only one is supported",
            )
            self._supervisor.reconcile("multiple_accounts_detected")
            self._log_bus.publish("Multiple Signal accounts detected", LogLevel.ERROR)
            return

        account = accounts[0]
        linked_at_ms = int(time() * 1000)
        self._db.set_account_state(
            status=AccountStatus.LINKED,
            signal_account=account.number or account.uuid,
            phone_number=account.number,
            device_id=self._parse_device_id(account),
            linked_at_ms=linked_at_ms,
            last_error=None,
        )
        self._supervisor.reconcile("account_linked")

    def _parse_device_id(self, account: SignalAccount) -> int | None:
        if not account.path:
            return None
        try:
            return int(account.path)
        except ValueError:
            return None

    def _clear_link_session_locked(self) -> None:
        self._link_session = None
        self._db.set_runtime_link_session(None)

    def logout(self) -> None:
        self._log_bus.publish("Logout request entered", LogLevel.INFO)
        with self._lock:
            if self._logout_in_progress:
                self._log_bus.publish("Logout request rejected: logout already in progress", LogLevel.WARNING)
                raise RuntimeError("Logout is already in progress")
            self._logout_in_progress = True
        self._log_bus.publish("Logout lock acquired", LogLevel.INFO)
        try:
            self._log_bus.publish("Logout requested", LogLevel.INFO)
            with self._lock:
                self._cancel_link_session_for_logout_locked()

            self._log_bus.publish("Stopping worker before logout", LogLevel.INFO)
            self._supervisor.stop_worker("logout_requested")
            self._log_bus.publish("Worker stop finished for logout", LogLevel.INFO)
            self._log_bus.publish("Waiting briefly after worker stop before account detection", LogLevel.INFO)
            sleep(0.25)

            self._log_bus.publish("Detecting linked Signal accounts for logout", LogLevel.INFO)
            try:
                self._log_bus.publish("listAccounts start for logout", LogLevel.INFO)
                accounts = self._signal_cli.list_accounts(
                    log=lambda message: self._log_bus.publish(f"logout listAccounts: {message}", LogLevel.INFO)
                )
                self._log_bus.publish(f"listAccounts end for logout: found {len(accounts)} account(s)", LogLevel.INFO)
            except SignalCliError as exc:
                self._forced_local_reset_for_logout(
                    reason=(
                        "Logout account detection failed; forcing local reset. "
                        f"Server-side unlink could not be confirmed: {exc}"
                    )
                )
                return

            if len(accounts) > 1:
                self._db.set_account_state(
                    status=AccountStatus.ERROR,
                    last_error="Multiple Signal accounts detected; logout is ambiguous",
                )
                self._supervisor.reconcile("logout_failed_multiple_accounts")
                self._log_bus.publish("Logout failed: multiple Signal accounts detected", LogLevel.ERROR)
                raise RuntimeError("Multiple Signal accounts detected; logout is ambiguous")

            if len(accounts) == 1:
                account = accounts[0]
                account_ref = account.number or account.uuid
                if not account_ref:
                    self._db.set_account_state(
                        status=AccountStatus.ERROR,
                        last_error="Linked account is missing a usable identifier",
                    )
                    self._supervisor.reconcile("logout_failed_missing_identifier")
                    self._log_bus.publish("Logout failed: linked account is missing a usable identifier", LogLevel.ERROR)
                    raise RuntimeError("Linked account is missing a usable identifier")

                unregister_error: str | None = None
                try:
                    self._log_bus.publish(f"Unregister start for {account_ref}", LogLevel.INFO)
                    self._signal_cli.unregister_account(account_ref)
                    self._log_bus.publish(f"Unregister end for {account_ref}", LogLevel.INFO)
                except SignalCliError as exc:
                    unregister_error = str(exc)
                    self._log_bus.publish(
                        f"Signal unregister failed; continuing with local cleanup path: {exc}",
                        LogLevel.WARNING,
                    )

                try:
                    self._log_bus.publish(f"deleteLocalAccountData start for {account_ref}", LogLevel.INFO)
                    self._signal_cli.delete_local_account_data(account_ref)
                    self._log_bus.publish(f"deleteLocalAccountData end for {account_ref}", LogLevel.INFO)
                except SignalCliError as exc:
                    self._log_bus.publish(
                        f"Normal local account cleanup failed; trying guarded fallback: {exc}",
                        LogLevel.WARNING,
                    )
                    try:
                        self._log_bus.publish(
                            f"deleteLocalAccountData --ignore-registered start for {account_ref}",
                            LogLevel.WARNING,
                        )
                        self._signal_cli.delete_local_account_data(account_ref, ignore_registered=True)
                        self._log_bus.publish(
                            f"deleteLocalAccountData --ignore-registered end for {account_ref}",
                            LogLevel.WARNING,
                        )
                    except SignalCliError as fallback_exc:
                        self._db.set_account_state(
                            status=AccountStatus.ERROR,
                            last_error=f"Logout cleanup failed: {fallback_exc}",
                        )
                        self._supervisor.reconcile("logout_cleanup_failed")
                        self._log_bus.publish(f"Logout cleanup failed: {fallback_exc}", LogLevel.ERROR)
                        raise RuntimeError(f"Logout cleanup failed: {fallback_exc}") from fallback_exc

                if unregister_error:
                    self._log_bus.publish(
                        "Local unlink completed with unregister warning; primary device may still need cleanup",
                        LogLevel.WARNING,
                    )
            else:
                self._log_bus.publish("No linked Signal account found locally; clearing app state", LogLevel.INFO)

            self._log_bus.publish("DB cleanup start for logout", LogLevel.INFO)
            self._db.clear_logout_state()
            self._log_bus.publish("DB cleanup end for logout", LogLevel.INFO)
            self._supervisor.reconcile("logout_completed")
            final_account_state = self._db.get_account_state()
            self._log_bus.publish(
                f"Signal device logged out locally; final account state={final_account_state.status.value}",
                LogLevel.INFO,
            )
        finally:
            with self._lock:
                self._logout_in_progress = False
            self._log_bus.publish("Logout lock released", LogLevel.INFO)

    def _forced_local_reset_for_logout(self, *, reason: str) -> None:
        existing_account_state = self._db.get_account_state()
        self._log_bus.publish(reason, LogLevel.WARNING)
        if existing_account_state.signal_account or existing_account_state.phone_number:
            self._log_bus.publish(
                "Forced local reset fallback using previously known local account metadata: "
                f"signal_account={existing_account_state.signal_account!r}, "
                f"phone_number={existing_account_state.phone_number!r}, "
                f"device_id={existing_account_state.device_id!r}",
                LogLevel.WARNING,
            )
        self._log_bus.publish("DB cleanup start for forced local reset logout", LogLevel.INFO)
        self._db.clear_logout_state()
        self._log_bus.publish("DB cleanup end for forced local reset logout", LogLevel.INFO)
        self._supervisor.reconcile("logout_forced_local_reset")
        final_account_state = self._db.get_account_state()
        self._log_bus.publish(
            "Forced local reset completed; server-side unlink not confirmed; "
            f"final account state={final_account_state.status.value}",
            LogLevel.WARNING,
        )

    def _cancel_link_session_for_logout_locked(self) -> None:
        if not self._link_session:
            self._db.set_runtime_link_session(None)
            return
        session = self._link_session
        session.canceled = True
        session.status = "canceled"
        if session.process.poll() is None:
            session.process.terminate()
        self._clear_link_session_locked()
