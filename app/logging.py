from __future__ import annotations

import asyncio
from collections import deque
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import AsyncIterator

from app.domain.enums import LogLevel


@dataclass(frozen=True)
class LogEvent:
    ts: str
    level: str
    message: str


class LogBus:
    def __init__(self, tail_size: int = 100) -> None:
        self._tail: deque[LogEvent] = deque(maxlen=tail_size)
        self._subscribers: set[asyncio.Queue[LogEvent]] = set()

    def publish(self, message: str, level: LogLevel = LogLevel.INFO) -> None:
        event = LogEvent(
            ts=datetime.now(timezone.utc).isoformat(),
            level=level.value,
            message=message,
        )
        self._tail.append(event)
        for queue in list(self._subscribers):
            queue.put_nowait(event)

    def snapshot(self) -> list[dict[str, str]]:
        return [asdict(item) for item in self._tail]

    async def subscribe(self) -> AsyncIterator[asyncio.Queue[LogEvent]]:
        queue: asyncio.Queue[LogEvent] = asyncio.Queue()
        self._subscribers.add(queue)
        try:
            yield queue
        finally:
            self._subscribers.discard(queue)
