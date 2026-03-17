from __future__ import annotations

from contextlib import asynccontextmanager
from time import time

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.config import STATIC_DIR, load_config
from app.db import Database
from app.domain.enums import LogLevel
from app.logging import LogBus
from app.models.settings import AppSettings
from app.services.auth import AuthService
from app.services.forwarder import ForwardingWorker
from app.services.groups import GroupsService
from app.services.settings import SettingsService
from app.services.supervisor import SupervisorService
from app.services.signal_cli import SignalCliAdapter
from app.web.routes_actions import router as actions_router
from app.web.routes_pages import router as pages_router
from app.web.routes_ws import router as ws_router


CONFIG = load_config()


@asynccontextmanager
async def lifespan(app: FastAPI):
    config = CONFIG
    db = Database(config.db_path)
    log_bus = LogBus(tail_size=config.live_log_tail_size)
    signal_cli = SignalCliAdapter(config)
    supervisor_service = SupervisorService(db, log_bus)
    forwarding_worker = ForwardingWorker(db, log_bus, signal_cli)
    forwarding_worker.attach_supervisor(supervisor_service)
    supervisor_service.attach_worker(forwarding_worker)
    auth_service = AuthService(db, log_bus, signal_cli, supervisor_service)
    groups_service = GroupsService(db, log_bus, signal_cli, supervisor_service)
    settings_service = SettingsService(db, log_bus, supervisor_service)

    db.initialize()
    db.ensure_seed_data(
        AppSettings(
            backlog_minutes=config.backlog_minutes_default,
            quiet_start_local=config.quiet_start_default,
            quiet_end_local=config.quiet_end_default,
            quiet_timezone=config.quiet_timezone,
            rate_limit_seconds=config.rate_limit_seconds_default,
            updated_at_ms=int(time() * 1000),
        )
    )

    app.state.config = config
    app.state.db = db
    app.state.log_bus = log_bus
    app.state.signal_cli = signal_cli
    app.state.auth_service = auth_service
    app.state.groups_service = groups_service
    app.state.supervisor_service = supervisor_service
    app.state.settings_service = settings_service
    app.state.forwarding_worker = forwarding_worker

    log_bus.publish("Phase 1 foundation initialized", LogLevel.INFO)
    auth_service.reconcile_account_state()
    supervisor_service.reconcile("startup")
    try:
        yield
    finally:
        log_bus.publish("Application shutdown requested", LogLevel.INFO)
        try:
            supervisor_service.stop_worker("application_shutdown")
        except Exception as exc:
            log_bus.publish(f"Application shutdown worker stop failed: {exc}", LogLevel.ERROR)
        log_bus.publish("Application shutdown complete", LogLevel.INFO)
def create_app() -> FastAPI:
    app = FastAPI(title=CONFIG.app_name, lifespan=lifespan)
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    app.include_router(pages_router)
    app.include_router(actions_router)
    app.include_router(ws_router)
    return app


app = create_app()
