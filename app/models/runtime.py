from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from app.domain.enums import AccountStatus, JsonRpcState, WorkerState


@dataclass(frozen=True)
class AccountStateRecord:
    status: AccountStatus
    signal_account: str | None
    phone_number: str | None
    device_id: int | None
    linked_at_ms: int | None
    last_error: str | None
    updated_at_ms: int

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> "AccountStateRecord":
        return cls(
            status=AccountStatus(row["status"]),
            signal_account=row["signal_account"],
            phone_number=row["phone_number"],
            device_id=row["device_id"],
            linked_at_ms=row["linked_at_ms"],
            last_error=row["last_error"],
            updated_at_ms=row["updated_at_ms"],
        )


@dataclass(frozen=True)
class RuntimeStateRecord:
    worker_state: WorkerState
    jsonrpc_state: JsonRpcState
    link_session_id: str | None
    last_reconnect_at_ms: int | None
    last_quiet_exit_at_ms: int | None
    last_forward_confirmed_at_ms: int | None
    updated_at_ms: int

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> "RuntimeStateRecord":
        return cls(
            worker_state=WorkerState(row["worker_state"]),
            jsonrpc_state=JsonRpcState(row["jsonrpc_state"]),
            link_session_id=row["link_session_id"],
            last_reconnect_at_ms=row["last_reconnect_at_ms"],
            last_quiet_exit_at_ms=row["last_quiet_exit_at_ms"],
            last_forward_confirmed_at_ms=row["last_forward_confirmed_at_ms"],
            updated_at_ms=row["updated_at_ms"],
        )
