from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from app.bot_status import build_bot_status
from app.config import TEMPLATES_DIR
from app.db import Database
from app.deps import get_auth_service, get_db, get_log_bus, get_supervisor_service
from app.logging import LogBus
from app.services.auth import AuthService
from app.services.supervisor import SupervisorService


templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
router = APIRouter()


def build_context(
    request: Request,
    db: Database,
    log_bus: LogBus,
    supervisor_service: SupervisorService,
    auth_service: AuthService | None = None,
) -> dict:
    account_state = db.get_account_state()
    runtime_state = db.get_runtime_state()
    settings = db.get_settings()
    supervisor_snapshot = supervisor_service.get_snapshot()
    return {
        "request": request,
        "settings": settings,
        "account_state": account_state,
        "runtime_state": runtime_state,
        "bot_status": build_bot_status(
            account_state,
            runtime_state,
            settings,
            bool(supervisor_snapshot["runtime_eligible"]),
        ),
        "supervisor": supervisor_snapshot,
        "known_groups": db.get_known_groups(),
        "log_tail": log_bus.snapshot(),
        "link_session": auth_service.get_active_link_session() if auth_service else None,
        "refreshed": request.query_params.get("refreshed"),
        "saved": request.query_params.get("saved"),
        "applied": request.query_params.get("applied"),
        "logged_out": request.query_params.get("logged_out"),
        "worker_restarted": request.query_params.get("worker_restarted"),
        "error": request.query_params.get("error"),
    }


@router.get("/", response_class=HTMLResponse)
def dashboard(
    request: Request,
    db: Database = Depends(get_db),
    log_bus: LogBus = Depends(get_log_bus),
    supervisor_service: SupervisorService = Depends(get_supervisor_service),
):
    return templates.TemplateResponse("dashboard.html", build_context(request, db, log_bus, supervisor_service))


@router.get("/login", response_class=HTMLResponse)
def login(
    request: Request,
    db: Database = Depends(get_db),
    log_bus: LogBus = Depends(get_log_bus),
    supervisor_service: SupervisorService = Depends(get_supervisor_service),
    auth_service: AuthService = Depends(get_auth_service),
):
    return templates.TemplateResponse("login.html", build_context(request, db, log_bus, supervisor_service, auth_service))


@router.get("/status", response_class=HTMLResponse)
def status(
    request: Request,
    db: Database = Depends(get_db),
    log_bus: LogBus = Depends(get_log_bus),
    supervisor_service: SupervisorService = Depends(get_supervisor_service),
):
    return templates.TemplateResponse("status.html", build_context(request, db, log_bus, supervisor_service))


@router.get("/groups", response_class=HTMLResponse)
def groups(
    request: Request,
    db: Database = Depends(get_db),
    log_bus: LogBus = Depends(get_log_bus),
    supervisor_service: SupervisorService = Depends(get_supervisor_service),
):
    return templates.TemplateResponse("groups.html", build_context(request, db, log_bus, supervisor_service))


@router.get("/settings", response_class=HTMLResponse)
def settings(
    request: Request,
    db: Database = Depends(get_db),
    log_bus: LogBus = Depends(get_log_bus),
    supervisor_service: SupervisorService = Depends(get_supervisor_service),
):
    return templates.TemplateResponse("settings.html", build_context(request, db, log_bus, supervisor_service))
