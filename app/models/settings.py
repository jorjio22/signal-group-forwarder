from __future__ import annotations

import sqlite3
from dataclasses import dataclass


@dataclass(frozen=True)
class AppSettings:
    backlog_minutes: int
    quiet_start_local: str
    quiet_end_local: str
    quiet_timezone: str
    rate_limit_seconds: int
    source_group_id: str | None = None
    source_group_name: str | None = None
    target_group_id: str | None = None
    target_group_name: str | None = None
    updated_at_ms: int = 0

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> "AppSettings":
        return cls(
            backlog_minutes=row["backlog_minutes"],
            quiet_start_local=row["quiet_start_local"],
            quiet_end_local=row["quiet_end_local"],
            quiet_timezone=row["quiet_timezone"],
            rate_limit_seconds=row["rate_limit_seconds"],
            source_group_id=row["source_group_id"],
            source_group_name=row["source_group_name"],
            target_group_id=row["target_group_id"],
            target_group_name=row["target_group_name"],
            updated_at_ms=row["updated_at_ms"],
        )
