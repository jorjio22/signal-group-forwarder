from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from time import time
from typing import Iterator

from app.config import MIGRATIONS_DIR
from app.domain.enums import AccountStatus, JsonRpcState, WorkerState
from app.models.groups import KnownGroupRecord, SignalGroupRecord
from app.models.runtime import AccountStateRecord, RuntimeStateRecord
from app.models.settings import AppSettings


class Database:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def initialize(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self.connection() as conn:
            user_version = conn.execute("PRAGMA user_version").fetchone()[0]
            if user_version == 0:
                schema_sql = (MIGRATIONS_DIR / "0001_initial.sql").read_text(encoding="utf-8")
                conn.executescript(schema_sql)
                conn.execute("PRAGMA user_version = 1")

    def ensure_seed_data(self, settings: AppSettings) -> None:
        with self.connection() as conn:
            conn.execute(
                """
                INSERT OR IGNORE INTO app_settings (
                    id, backlog_minutes, quiet_start_local, quiet_end_local,
                    quiet_timezone, rate_limit_seconds, updated_at_ms
                ) VALUES (1, ?, ?, ?, ?, ?, ?)
                """,
                (
                    settings.backlog_minutes,
                    settings.quiet_start_local,
                    settings.quiet_end_local,
                    settings.quiet_timezone,
                    settings.rate_limit_seconds,
                    settings.updated_at_ms,
                ),
            )
            conn.execute(
                """
                INSERT OR IGNORE INTO account_state (
                    id, status, updated_at_ms
                ) VALUES (1, ?, ?)
                """,
                (AccountStatus.UNLINKED.value, settings.updated_at_ms),
            )
            conn.execute(
                """
                INSERT OR IGNORE INTO runtime_state (
                    id, worker_state, jsonrpc_state, updated_at_ms
                ) VALUES (1, ?, ?, ?)
                """,
                (
                    WorkerState.STOPPED.value,
                    JsonRpcState.STOPPED.value,
                    settings.updated_at_ms,
                ),
            )

    def get_settings(self) -> AppSettings:
        with self.connection() as conn:
            row = conn.execute("SELECT * FROM app_settings WHERE id = 1").fetchone()
        if row is None:
            raise RuntimeError("app_settings row is missing")
        return AppSettings.from_row(row)

    def get_account_state(self) -> AccountStateRecord:
        with self.connection() as conn:
            row = conn.execute("SELECT * FROM account_state WHERE id = 1").fetchone()
        if row is None:
            raise RuntimeError("account_state row is missing")
        return AccountStateRecord.from_row(row)

    def get_runtime_state(self) -> RuntimeStateRecord:
        with self.connection() as conn:
            row = conn.execute("SELECT * FROM runtime_state WHERE id = 1").fetchone()
        if row is None:
            raise RuntimeError("runtime_state row is missing")
        return RuntimeStateRecord.from_row(row)

    def set_account_state(
        self,
        *,
        status: AccountStatus,
        signal_account: str | None = None,
        phone_number: str | None = None,
        device_id: int | None = None,
        linked_at_ms: int | None = None,
        last_error: str | None = None,
    ) -> None:
        updated_at_ms = int(time() * 1000)
        with self.connection() as conn:
            conn.execute(
                """
                UPDATE account_state
                SET status = ?, signal_account = ?, phone_number = ?, device_id = ?,
                    linked_at_ms = ?, last_error = ?, updated_at_ms = ?
                WHERE id = 1
                """,
                (
                    status.value,
                    signal_account,
                    phone_number,
                    device_id,
                    linked_at_ms,
                    last_error,
                    updated_at_ms,
                ),
            )

    def set_runtime_link_session(self, link_session_id: str | None) -> None:
        updated_at_ms = int(time() * 1000)
        with self.connection() as conn:
            conn.execute(
                """
                UPDATE runtime_state
                SET link_session_id = ?, updated_at_ms = ?
                WHERE id = 1
                """,
                (link_session_id, updated_at_ms),
            )

    def get_known_groups(self) -> list[KnownGroupRecord]:
        with self.connection() as conn:
            rows = conn.execute(
                "SELECT * FROM known_groups ORDER BY lower(group_name), group_id"
            ).fetchall()
        return [KnownGroupRecord.from_row(row) for row in rows]

    def replace_known_groups(self, groups: list[SignalGroupRecord], last_seen_at_ms: int) -> None:
        with self.connection() as conn:
            conn.execute("DELETE FROM known_groups")
            conn.executemany(
                """
                INSERT INTO known_groups (
                    group_id, group_name, is_active, is_blocked, last_seen_at_ms
                ) VALUES (?, ?, ?, ?, ?)
                """,
                [
                    (
                        group.group_id,
                        group.group_name,
                        int(group.is_active),
                        int(group.is_blocked),
                        last_seen_at_ms,
                    )
                    for group in groups
                ],
            )

    def save_group_selection(
        self,
        *,
        source_group_id: str,
        source_group_name: str,
        target_group_id: str,
        target_group_name: str,
    ) -> None:
        updated_at_ms = int(time() * 1000)
        with self.connection() as conn:
            conn.execute(
                """
                UPDATE app_settings
                SET source_group_id = ?, source_group_name = ?,
                    target_group_id = ?, target_group_name = ?,
                    updated_at_ms = ?
                WHERE id = 1
                """,
                (
                    source_group_id,
                    source_group_name,
                    target_group_id,
                    target_group_name,
                    updated_at_ms,
                ),
            )

    def update_runtime_settings(
        self,
        *,
        backlog_minutes: int,
        quiet_start_local: str,
        quiet_end_local: str,
        rate_limit_seconds: int,
    ) -> None:
        updated_at_ms = int(time() * 1000)
        with self.connection() as conn:
            conn.execute(
                """
                UPDATE app_settings
                SET backlog_minutes = ?, quiet_start_local = ?, quiet_end_local = ?,
                    rate_limit_seconds = ?, updated_at_ms = ?
                WHERE id = 1
                """,
                (
                    backlog_minutes,
                    quiet_start_local,
                    quiet_end_local,
                    rate_limit_seconds,
                    updated_at_ms,
                ),
            )

    def clear_logout_state(self) -> None:
        updated_at_ms = int(time() * 1000)
        with self.connection() as conn:
            conn.execute(
                """
                UPDATE account_state
                SET status = ?, signal_account = NULL, phone_number = NULL, device_id = NULL,
                    linked_at_ms = NULL, last_error = NULL, updated_at_ms = ?
                WHERE id = 1
                """,
                (AccountStatus.UNLINKED.value, updated_at_ms),
            )
            conn.execute(
                """
                UPDATE app_settings
                SET source_group_id = NULL, source_group_name = NULL,
                    target_group_id = NULL, target_group_name = NULL,
                    updated_at_ms = ?
                WHERE id = 1
                """,
                (updated_at_ms,),
            )
            conn.execute(
                """
                UPDATE runtime_state
                SET worker_state = ?, jsonrpc_state = ?, link_session_id = NULL,
                    last_reconnect_at_ms = NULL, last_quiet_exit_at_ms = NULL,
                    last_forward_confirmed_at_ms = NULL, updated_at_ms = ?
                WHERE id = 1
                """,
                (
                    WorkerState.STOPPED.value,
                    JsonRpcState.STOPPED.value,
                    updated_at_ms,
                ),
            )
            conn.execute("DELETE FROM forwarded_messages")
            conn.execute("DELETE FROM known_groups")

    def message_already_forwarded(self, message_key: str) -> bool:
        with self.connection() as conn:
            row = conn.execute(
                "SELECT 1 FROM forwarded_messages WHERE message_key = ?",
                (message_key,),
            ).fetchone()
        return row is not None

    def add_forwarded_message(self, *, message_key: str, source_group_id: str, message_ts_ms: int) -> None:
        forwarded_at_ms = int(time() * 1000)
        with self.connection() as conn:
            conn.execute(
                """
                INSERT OR IGNORE INTO forwarded_messages (
                    message_key, source_group_id, message_ts_ms, forwarded_at_ms
                ) VALUES (?, ?, ?, ?)
                """,
                (message_key, source_group_id, message_ts_ms, forwarded_at_ms),
            )

    def update_runtime_status(
        self,
        *,
        worker_state: WorkerState | None = None,
        jsonrpc_state: JsonRpcState | None = None,
        last_reconnect_at_ms: int | None = None,
        last_quiet_exit_at_ms: int | None = None,
        last_forward_confirmed_at_ms: int | None = None,
    ) -> None:
        updates: list[str] = []
        values: list[object] = []
        if worker_state is not None:
            updates.append("worker_state = ?")
            values.append(worker_state.value)
        if jsonrpc_state is not None:
            updates.append("jsonrpc_state = ?")
            values.append(jsonrpc_state.value)
        if last_reconnect_at_ms is not None:
            updates.append("last_reconnect_at_ms = ?")
            values.append(last_reconnect_at_ms)
        if last_quiet_exit_at_ms is not None:
            updates.append("last_quiet_exit_at_ms = ?")
            values.append(last_quiet_exit_at_ms)
        if last_forward_confirmed_at_ms is not None:
            updates.append("last_forward_confirmed_at_ms = ?")
            values.append(last_forward_confirmed_at_ms)
        if not updates:
            return

        updates.append("updated_at_ms = ?")
        values.append(int(time() * 1000))
        values.append(1)

        with self.connection() as conn:
            conn.execute(
                f"UPDATE runtime_state SET {', '.join(updates)} WHERE id = ?",
                values,
            )
