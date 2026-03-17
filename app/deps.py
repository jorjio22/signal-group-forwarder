from __future__ import annotations

from starlette.requests import HTTPConnection

from app.config import AppConfig
from app.db import Database
from app.logging import LogBus
from app.services.auth import AuthService
from app.services.groups import GroupsService
from app.services.settings import SettingsService
from app.services.supervisor import SupervisorService


def get_config(connection: HTTPConnection) -> AppConfig:
    return connection.app.state.config


def get_db(connection: HTTPConnection) -> Database:
    return connection.app.state.db


def get_log_bus(connection: HTTPConnection) -> LogBus:
    return connection.app.state.log_bus


def get_auth_service(connection: HTTPConnection) -> AuthService:
    return connection.app.state.auth_service


def get_groups_service(connection: HTTPConnection) -> GroupsService:
    return connection.app.state.groups_service


def get_settings_service(connection: HTTPConnection) -> SettingsService:
    return connection.app.state.settings_service


def get_supervisor_service(connection: HTTPConnection) -> SupervisorService:
    return connection.app.state.supervisor_service
