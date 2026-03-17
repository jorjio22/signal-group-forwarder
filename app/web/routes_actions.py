from __future__ import annotations

from urllib.parse import quote

from fastapi import APIRouter, Depends, Form
from fastapi.responses import JSONResponse, RedirectResponse

from app.deps import (
    get_auth_service,
    get_groups_service,
    get_log_bus,
    get_settings_service,
    get_supervisor_service,
)
from app.domain.enums import LogLevel
from app.logging import LogBus
from app.services.auth import AuthService
from app.services.groups import GroupsService
from app.services.settings import SettingsService, SettingsUpdate
from app.services.supervisor import SupervisorService


router = APIRouter(prefix="/actions")


@router.post("/link/start")
def start_link(auth_service: AuthService = Depends(get_auth_service)) -> JSONResponse:
    session = auth_service.start_link()
    return JSONResponse(
        {
            "ok": True,
            "link": {
                "session_id": session.session_id,
                "status": session.status,
                "qr_uri": session.qr_uri,
                "started_at_ms": session.started_at_ms,
                "last_error": session.last_error,
            },
        }
    )


@router.post("/link/cancel")
def cancel_link(auth_service: AuthService = Depends(get_auth_service)) -> JSONResponse:
    auth_service.cancel_link()
    return JSONResponse({"ok": True})


@router.get("/link/status")
def link_status(auth_service: AuthService = Depends(get_auth_service)) -> JSONResponse:
    return JSONResponse({"ok": True, **auth_service.get_link_status()})


@router.post("/groups/refresh")
def refresh_groups(groups_service: GroupsService = Depends(get_groups_service)) -> RedirectResponse:
    try:
        groups_service.refresh_groups()
        return RedirectResponse(url="/groups?refreshed=1", status_code=303)
    except RuntimeError as exc:
        return RedirectResponse(url=f"/groups?error={quote(str(exc))}", status_code=303)


@router.post("/groups/save")
def save_groups(
    source_group_id: str = Form(...),
    target_group_id: str = Form(...),
    groups_service: GroupsService = Depends(get_groups_service),
) -> RedirectResponse:
    try:
        groups_service.save_selection(source_group_id, target_group_id)
        return RedirectResponse(url="/groups?saved=1", status_code=303)
    except RuntimeError as exc:
        return RedirectResponse(url=f"/groups?error={quote(str(exc))}", status_code=303)


@router.post("/settings/save")
def save_settings(
    backlog_minutes: int = Form(...),
    quiet_start_local: str = Form(...),
    quiet_end_local: str = Form(...),
    rate_limit_seconds: int = Form(...),
    settings_service: SettingsService = Depends(get_settings_service),
) -> RedirectResponse:
    try:
        settings_service.save(
            SettingsUpdate(
                backlog_minutes=backlog_minutes,
                quiet_start_local=quiet_start_local,
                quiet_end_local=quiet_end_local,
                rate_limit_seconds=rate_limit_seconds,
            )
        )
        return RedirectResponse(url="/settings?saved=1&applied=1", status_code=303)
    except RuntimeError as exc:
        return RedirectResponse(url=f"/settings?error={quote(str(exc))}", status_code=303)


@router.post("/logout")
def logout(
    auth_service: AuthService = Depends(get_auth_service),
    log_bus: LogBus = Depends(get_log_bus),
) -> RedirectResponse:
    log_bus.publish("HTTP POST /actions/logout invoked", LogLevel.INFO)
    try:
        auth_service.logout()
        log_bus.publish("HTTP POST /actions/logout completed successfully", LogLevel.INFO)
        return RedirectResponse(url="/login?logged_out=1", status_code=303)
    except RuntimeError as exc:
        log_bus.publish(f"HTTP POST /actions/logout failed: {exc}", LogLevel.ERROR)
        return RedirectResponse(url=f"/login?error={quote(str(exc))}", status_code=303)
    except Exception as exc:
        log_bus.publish(f"HTTP POST /actions/logout hit unexpected error: {exc}", LogLevel.ERROR)
        return RedirectResponse(url="/login?error=Unexpected%20logout%20failure", status_code=303)


@router.post("/worker/restart")
def restart_worker(supervisor_service: SupervisorService = Depends(get_supervisor_service)) -> RedirectResponse:
    supervisor_service.restart_worker()
    return RedirectResponse(url="/status?worker_restarted=1", status_code=303)
