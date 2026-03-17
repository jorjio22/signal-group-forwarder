from __future__ import annotations

from datetime import datetime

from app.services import quiet_hours


def test_quiet_hours_window_crossing_midnight(monkeypatch):
    monkeypatch.setattr(quiet_hours, "_now_in_timezone", lambda _: datetime(2026, 3, 17, 21, 30))
    assert quiet_hours.is_within_quiet_hours("20:00", "07:00", "Europe/Kyiv") is True


def test_quiet_hours_window_before_end(monkeypatch):
    monkeypatch.setattr(quiet_hours, "_now_in_timezone", lambda _: datetime(2026, 3, 17, 6, 30))
    assert quiet_hours.is_within_quiet_hours("20:00", "07:00", "Europe/Kyiv") is True


def test_quiet_hours_outside_window(monkeypatch):
    monkeypatch.setattr(quiet_hours, "_now_in_timezone", lambda _: datetime(2026, 3, 17, 12, 0))
    assert quiet_hours.is_within_quiet_hours("20:00", "07:00", "Europe/Kyiv") is False


def test_equal_quiet_hours_boundaries_disable_pause(monkeypatch):
    monkeypatch.setattr(quiet_hours, "_now_in_timezone", lambda _: datetime(2026, 3, 17, 12, 0))
    assert quiet_hours.is_within_quiet_hours("20:00", "20:00", "Europe/Kyiv") is False
