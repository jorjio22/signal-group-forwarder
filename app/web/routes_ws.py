from __future__ import annotations

from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect

from app.deps import get_log_bus
from app.logging import LogBus


router = APIRouter()


@router.websocket("/ws/logs")
async def logs_ws(websocket: WebSocket, log_bus: LogBus = Depends(get_log_bus)) -> None:
    await websocket.accept()

    for event in log_bus.snapshot():
        await websocket.send_json(event)

    try:
        async for queue in log_bus.subscribe():
            while True:
                event = await queue.get()
                await websocket.send_json(
                    {"ts": event.ts, "level": event.level, "message": event.message}
                )
    except WebSocketDisconnect:
        return
