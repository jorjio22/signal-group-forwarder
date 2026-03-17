from __future__ import annotations

from enum import Enum


class AccountStatus(str, Enum):
    UNLINKED = "UNLINKED"
    LINKING = "LINKING"
    LINKED = "LINKED"
    ERROR = "ERROR"


class WorkerState(str, Enum):
    STOPPED = "STOPPED"
    STARTING = "STARTING"
    RUNNING = "RUNNING"
    ERROR = "ERROR"


class JsonRpcState(str, Enum):
    STOPPED = "STOPPED"
    CONNECTING = "CONNECTING"
    CONNECTED = "CONNECTED"
    ERROR = "ERROR"


class LogLevel(str, Enum):
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
