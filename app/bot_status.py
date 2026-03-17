from __future__ import annotations

from app.domain.enums import AccountStatus, JsonRpcState, WorkerState
from app.models.runtime import AccountStateRecord, RuntimeStateRecord
from app.models.settings import AppSettings
from app.services.quiet_hours import QuietHoursError, is_within_quiet_hours


def build_bot_status(
    account_state: AccountStateRecord,
    runtime_state: RuntimeStateRecord,
    settings: AppSettings,
    runtime_eligible: bool,
) -> dict[str, str]:
    if (
        runtime_state.worker_state == WorkerState.ERROR
        or runtime_state.jsonrpc_state == JsonRpcState.ERROR
        or account_state.status == AccountStatus.ERROR
    ):
        return {"label": "Error", "class": "error"}

    if not runtime_eligible:
        return {"label": "Stopped", "class": "stopped"}

    try:
        quiet_hours_active = is_within_quiet_hours(
            settings.quiet_start_local,
            settings.quiet_end_local,
            settings.quiet_timezone,
        )
    except QuietHoursError:
        return {"label": "Error", "class": "error"}

    if quiet_hours_active:
        return {"label": "Stopped", "class": "stopped"}

    if runtime_state.worker_state == WorkerState.RUNNING and runtime_state.jsonrpc_state == JsonRpcState.CONNECTED:
        return {"label": "Running", "class": "running"}

    return {"label": "Stopped", "class": "stopped"}
