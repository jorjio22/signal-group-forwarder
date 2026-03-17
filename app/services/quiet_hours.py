from __future__ import annotations

from datetime import datetime
from functools import lru_cache

try:
    from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
except ImportError:  # pragma: no cover
    ZoneInfo = None  # type: ignore[assignment]
    ZoneInfoNotFoundError = Exception  # type: ignore[assignment]


class QuietHoursError(RuntimeError):
    pass


def is_within_quiet_hours(start_local: str, end_local: str, timezone_name: str) -> bool:
    now = _now_in_timezone(timezone_name)
    current_minutes = now.hour * 60 + now.minute
    start_minutes = _parse_hhmm(start_local)
    end_minutes = _parse_hhmm(end_local)

    if start_minutes == end_minutes:
        return False
    if start_minutes < end_minutes:
        return start_minutes <= current_minutes < end_minutes
    return current_minutes >= start_minutes or current_minutes < end_minutes


def _parse_hhmm(value: str) -> int:
    dt = datetime.strptime(value, "%H:%M")
    return dt.hour * 60 + dt.minute


def _now_in_timezone(timezone_name: str) -> datetime:
    return datetime.now(_get_timezone(timezone_name))


@lru_cache(maxsize=8)
def _get_timezone(timezone_name: str) -> ZoneInfo:
    if ZoneInfo is None:  # pragma: no cover
        raise QuietHoursError("zoneinfo is unavailable in this Python runtime")
    try:
        return ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError as exc:
        raise QuietHoursError(
            f"Timezone data for {timezone_name} is unavailable. Install tzdata or provide system zoneinfo."
        ) from exc
