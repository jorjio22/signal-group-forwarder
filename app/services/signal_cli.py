from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from app.config import BASE_DIR, AppConfig
from app.models.groups import SignalGroupRecord


@dataclass(frozen=True)
class SignalAccount:
    number: str | None
    uuid: str | None
    path: str | None


class SignalCliError(RuntimeError):
    pass


class SignalCliAdapter:
    def __init__(self, config: AppConfig) -> None:
        self._config = config

    def _base_command(self) -> list[str]:
        return [
            self._config.signal_cli_executable,
            "--config",
            str(self._config.signal_config_dir),
        ]

    def _one_shot_command(self) -> list[str]:
        return self._base_command()

    def _one_shot_env(self) -> dict[str, str]:
        return os.environ.copy()

    def _run_one_shot(
        self,
        *,
        command: list[str],
        timeout_seconds: int | None,
        label: str,
        log: Callable[[str], None] | None = None,
    ) -> subprocess.CompletedProcess[str]:
        def emit(message: str) -> None:
            if log is not None:
                log(message)

        emit(f"{label}: start timeout={timeout_seconds}s implementation=Popen.communicate.wait shell=False")

        process = subprocess.Popen(
            command,
            cwd=str(BASE_DIR),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            stdin=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            env=self._one_shot_env(),
            shell=False,
        )
        emit(f"{label}: parent_pid={process.pid}")
        try:
            stdout, stderr = process.communicate(timeout=timeout_seconds)
            emit(f"{label}: completed code={process.returncode}")
        except subprocess.TimeoutExpired as exc:
            emit(f"{label}: timeout handler entered")
            emit(f"{label}: executable={command[0]}")
            emit(f"{label}: argv={command}")
            emit(f"{label}: cwd={BASE_DIR}")
            stdout = (exc.stdout or "").strip()
            stderr = (exc.stderr or "").strip()
            emit(f"{label}: partial stdout on timeout={stdout!r}")
            emit(f"{label}: partial stderr on timeout={stderr!r}")
            parent_alive_before_kill = process.poll() is None
            emit(f"{label}: parent_alive_before_kill={parent_alive_before_kill}")
            if parent_alive_before_kill:
                process.kill()
                emit(f"{label}: parent kill issued")
            try:
                process.wait(timeout=2)
                emit(f"{label}: parent exited after kill with code={process.returncode}")
            except subprocess.TimeoutExpired:
                emit(f"{label}: parent did not exit within 2s after kill")
            emit(
                f"{label}: child_process_state={'unknown' if os.name == 'nt' else 'not_expected'}"
            )
            raise SignalCliError(
                f"signal-cli {label} timed out after {timeout_seconds}s"
            ) from exc

        if process.returncode is None:
            process.wait()
            emit(f"{label}: wait completed with code={process.returncode}")
        if process.returncode != 0:
            emit(f"{label}: executable={command[0]}")
            emit(f"{label}: argv={command}")
            emit(f"{label}: cwd={BASE_DIR}")
            emit(f"{label}: stdout={stdout.strip()!r}")
            emit(f"{label}: stderr={stderr.strip()!r}")
        return subprocess.CompletedProcess(command, process.returncode or 0, stdout, stderr)

    def list_accounts(self, log: Callable[[str], None] | None = None) -> list[SignalAccount]:
        command = [*self._one_shot_command(), "--output", "json", "listAccounts"]
        result = self._run_one_shot(
            command=command,
            timeout_seconds=self._config.signal_cli_logout_timeout_seconds,
            label="listAccounts",
            log=log,
        )
        if result.returncode != 0:
            raise SignalCliError(result.stderr.strip() or "signal-cli listAccounts failed")

        payload = json.loads(result.stdout or "[]")
        accounts: list[SignalAccount] = []
        for item in payload:
            accounts.append(
                SignalAccount(
                    number=item.get("number"),
                    uuid=item.get("uuid"),
                    path=item.get("path"),
                )
            )
        return accounts

    def list_groups(self, account: str) -> list[SignalGroupRecord]:
        command = [*self._one_shot_command(), "--output", "json", "--account", account, "listGroups"]
        result = self._run_one_shot(
            command=command,
            timeout_seconds=self._config.signal_cli_logout_timeout_seconds,
            label="listGroups",
        )
        if result.returncode != 0:
            raise SignalCliError(result.stderr.strip() or "signal-cli listGroups failed")

        payload = json.loads(result.stdout or "[]")
        groups: list[SignalGroupRecord] = []
        for item in payload:
            group_id = item.get("id") or item.get("groupId")
            if not group_id:
                continue
            groups.append(
                SignalGroupRecord(
                    group_id=group_id,
                    group_name=item.get("name") or "Unnamed group",
                    is_active=bool(item.get("isActive", item.get("active", True))),
                    is_blocked=bool(item.get("isBlocked", item.get("blocked", False))),
                )
            )
        return groups

    def start_link_process(self) -> subprocess.Popen[str]:
        command = [*self._base_command(), "link", "--name", self._config.link_device_name]
        return subprocess.Popen(
            command,
            cwd=str(BASE_DIR),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            stdin=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
        )

    def start_jsonrpc_process(self, account: str) -> subprocess.Popen[str]:
        command = [
            *self._base_command(),
            "--output",
            "json",
            "--account",
            account,
            "jsonRpc",
            "--receive-mode",
            "on-connection",
            "--ignore-attachments",
            "--ignore-stories",
        ]
        return subprocess.Popen(
            command,
            cwd=str(BASE_DIR),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            stdin=subprocess.PIPE,
            text=True,
            encoding="utf-8",
        )

    def send_jsonrpc(self, process: subprocess.Popen[str], payload: dict[str, Any]) -> None:
        if process.stdin is None:
            raise SignalCliError("signal-cli jsonRpc stdin is unavailable")
        try:
            process.stdin.write(json.dumps(payload, ensure_ascii=False) + "\n")
            process.stdin.flush()
        except OSError as exc:
            raise SignalCliError(f"Failed to write to signal-cli jsonRpc stdin: {exc}") from exc

    def unregister_account(self, account: str) -> None:
        command = [*self._one_shot_command(), "--account", account, "unregister"]
        result = self._run_one_shot(
            command=command,
            timeout_seconds=self._config.signal_cli_logout_timeout_seconds,
            label="unregister",
        )
        if result.returncode != 0:
            raise SignalCliError(result.stderr.strip() or "signal-cli unregister failed")

    def delete_local_account_data(self, account: str, *, ignore_registered: bool = False) -> None:
        command = [*self._one_shot_command(), "--account", account, "deleteLocalAccountData"]
        if ignore_registered:
            command.append("--ignore-registered")
        result = self._run_one_shot(
            command=command,
            timeout_seconds=self._config.signal_cli_logout_timeout_seconds,
            label="deleteLocalAccountData",
        )
        if result.returncode != 0:
            raise SignalCliError(result.stderr.strip() or "signal-cli deleteLocalAccountData failed")
