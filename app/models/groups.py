from __future__ import annotations

import sqlite3
from dataclasses import dataclass


@dataclass(frozen=True)
class KnownGroupRecord:
    group_id: str
    group_name: str
    is_active: bool
    is_blocked: bool
    last_seen_at_ms: int

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> "KnownGroupRecord":
        return cls(
            group_id=row["group_id"],
            group_name=row["group_name"],
            is_active=bool(row["is_active"]),
            is_blocked=bool(row["is_blocked"]),
            last_seen_at_ms=row["last_seen_at_ms"],
        )


@dataclass(frozen=True)
class SignalGroupRecord:
    group_id: str
    group_name: str
    is_active: bool
    is_blocked: bool
