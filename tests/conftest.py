from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from app.db import Database
from app.logging import LogBus
from app.models.groups import SignalGroupRecord
from app.models.settings import AppSettings


class DummySignalCli:
    def __init__(self) -> None:
        self._config = SimpleNamespace(worker_stop_timeout_seconds=1)


@pytest.fixture()
def db(tmp_path: Path) -> Database:
    database = Database(tmp_path / "app.sqlite")
    database.initialize()
    database.ensure_seed_data(
        AppSettings(
            backlog_minutes=1,
            quiet_start_local="20:00",
            quiet_end_local="07:00",
            quiet_timezone="Europe/Kyiv",
            rate_limit_seconds=30,
            updated_at_ms=1,
        )
    )
    return database


@pytest.fixture()
def configured_db(db: Database) -> Database:
    db.save_group_selection(
        source_group_id="source-group",
        source_group_name="Source",
        target_group_id="target-group",
        target_group_name="Target",
    )
    return db


@pytest.fixture()
def log_bus() -> LogBus:
    return LogBus(tail_size=100)


@pytest.fixture()
def dummy_signal_cli() -> DummySignalCli:
    return DummySignalCli()


def seed_known_group(db: Database, group_id: str, group_name: str) -> None:
    db.replace_known_groups(
        [SignalGroupRecord(group_id=group_id, group_name=group_name, is_active=True, is_blocked=False)],
        last_seen_at_ms=1,
    )
