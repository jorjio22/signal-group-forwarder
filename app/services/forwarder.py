from __future__ import annotations

import hashlib
import itertools
import json
import queue
import subprocess
import threading
import time
from collections import deque
from dataclasses import dataclass
from typing import Any

from app.db import Database
from app.domain.enums import JsonRpcState, LogLevel, WorkerState
from app.logging import LogBus
from app.services.quiet_hours import QuietHoursError, is_within_quiet_hours
from app.services.signal_cli import SignalCliAdapter, SignalCliError


@dataclass(frozen=True)
class ParsedIncomingMessage:
    event_kind: str
    group_id: str
    text: str
    message_ts_ms: int
    sender_id: str
    message_key: str


@dataclass
class PendingSend:
    request_id: int
    message: ParsedIncomingMessage


class ForwardingWorker:
    def __init__(self, db: Database, log_bus: LogBus, signal_cli: SignalCliAdapter) -> None:
        self._db = db
        self._log_bus = log_bus
        self._signal_cli = signal_cli
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._lock = threading.Lock()
        self._process: subprocess.Popen[str] | None = None
        self._worker_state = "stopped"
        self._request_ids = itertools.count(1)
        self._supervisor: Any = None

    def attach_supervisor(self, supervisor: Any) -> None:
        self._supervisor = supervisor

    def start(self) -> None:
        with self._lock:
            if self._thread and self._thread.is_alive():
                return
            self._stop_event.clear()
            self._thread = threading.Thread(target=self._run, name="forwarding-worker", daemon=True)
            self._thread.start()

    def stop(self, reason: str) -> None:
        with self._lock:
            self._stop_event.set()
            process = self._process
            thread = self._thread
        self._log_bus.publish(f"Worker stop requested: {reason}", LogLevel.INFO)
        self._set_worker_state("stopping")
        stop_timeout = self._signal_cli._config.worker_stop_timeout_seconds
        if process is not None and process.poll() is None:
            self._log_bus.publish("Stopping JSON-RPC process", LogLevel.INFO)
            process.terminate()
            try:
                process.wait(timeout=stop_timeout)
            except subprocess.TimeoutExpired:
                self._log_bus.publish(
                    f"JSON-RPC process did not exit after terminate within {stop_timeout}s; killing it",
                    LogLevel.WARNING,
                )
                process.kill()
                try:
                    process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    self._log_bus.publish("JSON-RPC process did not exit promptly after kill", LogLevel.ERROR)
        if thread and thread.is_alive():
            self._log_bus.publish(f"Waiting for worker thread to stop (timeout {stop_timeout}s)", LogLevel.INFO)
            thread.join(timeout=stop_timeout)
            if thread.is_alive():
                self._log_bus.publish("Worker thread did not stop before timeout; continuing shutdown", LogLevel.ERROR)
        with self._lock:
            self._process = None
            if self._thread is thread and thread is not None and not thread.is_alive():
                self._thread = None
        self._db.update_runtime_status(worker_state=WorkerState.STOPPED, jsonrpc_state=JsonRpcState.STOPPED)
        self._set_worker_state("stopped")

    def restart(self) -> None:
        self.stop("manual_restart")
        if self._supervisor is not None and self._supervisor.get_snapshot()["runtime_eligible"]:
            self.start()

    def get_lifecycle_state(self) -> str:
        with self._lock:
            return self._worker_state

    def _run(self) -> None:
        self._set_worker_state("starting")
        self._db.update_runtime_status(worker_state=WorkerState.STARTING, jsonrpc_state=JsonRpcState.STOPPED)
        self._log_bus.publish("Worker starting", LogLevel.INFO)

        reserved_keys: set[str] = set()
        outbound_queue: deque[ParsedIncomingMessage] = deque()
        inflight_send: PendingSend | None = None
        previous_quiet_state: bool | None = None
        last_send_started_at = 0.0
        quiet_hours_failed = False

        while not self._stop_event.is_set():
            account_state = self._db.get_account_state()
            settings = self._db.get_settings()
            if not account_state.signal_account or not settings.source_group_id or not settings.target_group_id:
                self._log_bus.publish("Worker stopping because runtime is not configured", LogLevel.WARNING)
                break

            session_queue: queue.Queue[dict[str, Any]] = queue.Queue()
            try:
                self._db.update_runtime_status(jsonrpc_state=JsonRpcState.CONNECTING)
                self._set_worker_state("starting")
                process = self._signal_cli.start_jsonrpc_process(account_state.signal_account)
                with self._lock:
                    self._process = process
                reconnect_at_ms = int(time.time() * 1000)
                self._db.update_runtime_status(
                    worker_state=WorkerState.RUNNING,
                    jsonrpc_state=JsonRpcState.CONNECTED,
                    last_reconnect_at_ms=reconnect_at_ms,
                )
                self._set_worker_state("running")
                self._log_bus.publish("JSON-RPC session started", LogLevel.INFO)

                threading.Thread(
                    target=self._read_jsonrpc_stdout,
                    args=(process, session_queue),
                    daemon=True,
                ).start()
                threading.Thread(
                    target=self._read_jsonrpc_stderr,
                    args=(process, session_queue),
                    daemon=True,
                ).start()

                while not self._stop_event.is_set():
                    current_settings = self._db.get_settings()
                    try:
                        quiet_now = is_within_quiet_hours(
                            current_settings.quiet_start_local,
                            current_settings.quiet_end_local,
                            current_settings.quiet_timezone,
                        )
                    except QuietHoursError as exc:
                        if not quiet_hours_failed:
                            self._log_bus.publish(
                                "Quiet-hours timezone initialization failed for "
                                f"{current_settings.quiet_timezone}: {exc}. "
                                "Worker will stay running and reject messages until timezone data is available.",
                                LogLevel.ERROR,
                            )
                            quiet_hours_failed = True
                        quiet_now = True
                    else:
                        if quiet_hours_failed:
                            self._log_bus.publish(
                                f"Quiet-hours timezone recovered for {current_settings.quiet_timezone}",
                                LogLevel.INFO,
                            )
                            quiet_hours_failed = False
                    if previous_quiet_state is True and quiet_now is False:
                        quiet_exit_at_ms = int(time.time() * 1000)
                        self._db.update_runtime_status(last_quiet_exit_at_ms=quiet_exit_at_ms)
                        self._log_bus.publish("Quiet hours ended; effective cutoff advanced", LogLevel.INFO)
                    elif previous_quiet_state is False and quiet_now is True:
                        self._log_bus.publish("Quiet hours started", LogLevel.INFO)
                    previous_quiet_state = quiet_now

                    try:
                        item = session_queue.get(timeout=1.0)
                    except queue.Empty:
                        item = {"kind": "tick"}

                    if item["kind"] == "json":
                        payload = item["payload"]
                        if payload.get("method") == "receive":
                            parsed = self._parse_receive_notification(payload)
                            if parsed is not None:
                                self._handle_incoming_message(
                                    parsed,
                                    current_settings.source_group_id,
                                    quiet_now,
                                    reserved_keys,
                                    outbound_queue,
                                )
                        elif "id" in payload:
                            inflight_send = self._handle_send_response(payload, inflight_send, reserved_keys)
                    elif item["kind"] == "stderr":
                        self._log_bus.publish(
                            f"signal-cli jsonRpc: {item['line']}",
                            self._classify_process_line(item["line"], default_level=LogLevel.INFO),
                        )
                    elif item["kind"] == "stdout_non_json":
                        self._log_bus.publish(
                            f"signal-cli jsonRpc non-JSON output: {item['line']}",
                            self._classify_process_line(item["line"], default_level=LogLevel.INFO),
                        )

                    if inflight_send is None:
                        inflight_send, last_send_started_at = self._maybe_send_next(
                            process=process,
                            account=account_state.signal_account,
                            target_group_id=current_settings.target_group_id,
                            outbound_queue=outbound_queue,
                            last_send_started_at=last_send_started_at,
                            rate_limit_seconds=current_settings.rate_limit_seconds,
                        )

                    if process.poll() is not None and session_queue.empty():
                        if self._stop_event.is_set():
                            break
                        raise SignalCliError(f"signal-cli jsonRpc exited with code {process.poll()}")

            except (SignalCliError, OSError) as exc:
                if self._stop_event.is_set():
                    break
                self._log_bus.publish(f"Worker session error: {exc}", LogLevel.ERROR)
                self._db.update_runtime_status(jsonrpc_state=JsonRpcState.ERROR)
                time.sleep(5)
            finally:
                with self._lock:
                    process = self._process
                    self._process = None
                if process is not None and process.poll() is None:
                    self._log_bus.publish("Terminating JSON-RPC session process", LogLevel.INFO)
                    process.terminate()
                outbound_queue.clear()
                reserved_keys.clear()
                inflight_send = None
                self._db.update_runtime_status(jsonrpc_state=JsonRpcState.STOPPED)
                self._log_bus.publish("JSON-RPC session stopped", LogLevel.INFO)

                if self._stop_event.is_set():
                    break
                if self._supervisor is not None and not self._supervisor.get_snapshot()["runtime_eligible"]:
                    break

        self._db.update_runtime_status(worker_state=WorkerState.STOPPED, jsonrpc_state=JsonRpcState.STOPPED)
        self._set_worker_state("stopped")
        self._log_bus.publish("Worker stopped", LogLevel.INFO)

    def _read_jsonrpc_stdout(
        self,
        process: subprocess.Popen[str],
        session_queue: queue.Queue[dict[str, Any]],
    ) -> None:
        assert process.stdout is not None
        for raw_line in process.stdout:
            line = raw_line.strip()
            if not line:
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                session_queue.put({"kind": "stdout_non_json", "line": line})
                continue
            session_queue.put({"kind": "json", "payload": payload})

    def _read_jsonrpc_stderr(
        self,
        process: subprocess.Popen[str],
        session_queue: queue.Queue[dict[str, Any]],
    ) -> None:
        assert process.stderr is not None
        for raw_line in process.stderr:
            line = raw_line.strip()
            if line:
                session_queue.put({"kind": "stderr", "line": line})

    def _parse_receive_notification(self, payload: dict[str, Any]) -> ParsedIncomingMessage | None:
        envelope = ((payload.get("params") or {}).get("envelope")) or {}

        data_message = envelope.get("dataMessage")
        if isinstance(data_message, dict):
            return self._build_parsed_message(
                event_kind="dataMessage",
                group_id=((data_message.get("groupInfo") or {}).get("groupId")) or envelope.get("sourceGroupId"),
                text=data_message.get("message"),
                message_ts_ms=data_message.get("timestamp") or envelope.get("timestamp"),
                sender_id=(
                    envelope.get("sourceServiceId")
                    or envelope.get("sourceUuid")
                    or envelope.get("sourceNumber")
                    or "unknown"
                ),
            )

        sync_message = envelope.get("syncMessage")
        if isinstance(sync_message, dict):
            sent_message = sync_message.get("sentMessage")
            if isinstance(sent_message, dict):
                return self._build_parsed_message(
                    event_kind="syncMessage.sentMessage",
                    group_id=(sent_message.get("groupInfo") or {}).get("groupId"),
                    text=sent_message.get("message"),
                    message_ts_ms=sent_message.get("timestamp") or envelope.get("timestamp"),
                    sender_id="self",
                )
        return None

    def _build_parsed_message(
        self,
        *,
        event_kind: str,
        group_id: Any,
        text: Any,
        message_ts_ms: Any,
        sender_id: str,
    ) -> ParsedIncomingMessage | None:
        if not isinstance(group_id, str) or not group_id:
            self._log_bus.publish("Rejected message: missing group id", LogLevel.INFO)
            return None
        if not isinstance(text, str) or not text:
            self._log_bus.publish("Rejected message: not plain text", LogLevel.INFO)
            return None
        if not isinstance(message_ts_ms, int):
            self._log_bus.publish("Rejected message: missing timestamp", LogLevel.INFO)
            return None
        return ParsedIncomingMessage(
            event_kind=event_kind,
            group_id=group_id,
            text=text,
            message_ts_ms=message_ts_ms,
            sender_id=sender_id,
            message_key=self._make_message_key(
                event_kind=event_kind,
                group_id=group_id,
                sender_id=sender_id,
                message_ts_ms=message_ts_ms,
                text=text,
            ),
        )

    def _handle_incoming_message(
        self,
        parsed: ParsedIncomingMessage,
        source_group_id: str | None,
        quiet_now: bool,
        reserved_keys: set[str],
        outbound_queue: deque[ParsedIncomingMessage],
    ) -> None:
        settings = self._db.get_settings()
        runtime_state = self._db.get_runtime_state()
        now_ms = int(time.time() * 1000)
        effective_cutoff_ms = max(
            now_ms - settings.backlog_minutes * 60_000,
            runtime_state.last_reconnect_at_ms or 0,
            runtime_state.last_quiet_exit_at_ms or 0,
        )

        if parsed.group_id != source_group_id:
            self._log_bus.publish(f"Rejected message: wrong source group [{parsed.event_kind}]", LogLevel.INFO)
            return
        if quiet_now:
            self._log_bus.publish(f"Rejected message: quiet hours [{parsed.event_kind}]", LogLevel.INFO)
            return
        if parsed.message_ts_ms < effective_cutoff_ms:
            self._log_bus.publish(f"Rejected message: older than cutoff [{parsed.event_kind}]", LogLevel.INFO)
            return
        if parsed.message_key in reserved_keys or self._db.message_already_forwarded(parsed.message_key):
            self._log_bus.publish(f"Rejected message: duplicate [{parsed.event_kind}]", LogLevel.INFO)
            return

        outbound_queue.append(parsed)
        reserved_keys.add(parsed.message_key)
        self._log_bus.publish(
            f"Accepted message for forwarding [{parsed.event_kind}] ts={parsed.message_ts_ms}",
            LogLevel.INFO,
        )

    def _maybe_send_next(
        self,
        *,
        process: subprocess.Popen[str],
        account: str,
        target_group_id: str | None,
        outbound_queue: deque[ParsedIncomingMessage],
        last_send_started_at: float,
        rate_limit_seconds: int,
    ) -> tuple[PendingSend | None, float]:
        if target_group_id is None or not outbound_queue:
            return None, last_send_started_at
        elapsed = time.monotonic() - last_send_started_at
        if last_send_started_at and elapsed < rate_limit_seconds:
            return None, last_send_started_at

        message = outbound_queue.popleft()
        request_id = next(self._request_ids)
        payload = {
            "jsonrpc": "2.0",
            "method": "send",
            "params": {
                "account": account,
                "message": message.text,
                "groupId": target_group_id,
            },
            "id": request_id,
        }
        self._signal_cli.send_jsonrpc(process, payload)
        self._log_bus.publish(f"Sending message [{message.event_kind}] request_id={request_id}", LogLevel.INFO)
        return PendingSend(request_id=request_id, message=message), time.monotonic()

    def _handle_send_response(
        self,
        payload: dict[str, Any],
        inflight_send: PendingSend | None,
        reserved_keys: set[str],
    ) -> PendingSend | None:
        if inflight_send is None or payload.get("id") != inflight_send.request_id:
            return inflight_send

        message = inflight_send.message
        if payload.get("error"):
            reserved_keys.discard(message.message_key)
            self._log_bus.publish(
                f"Send failed [{message.event_kind}] request_id={inflight_send.request_id}: {payload['error']}",
                LogLevel.ERROR,
            )
            return None

        self._db.add_forwarded_message(
            message_key=message.message_key,
            source_group_id=message.group_id,
            message_ts_ms=message.message_ts_ms,
        )
        self._db.update_runtime_status(last_forward_confirmed_at_ms=message.message_ts_ms)
        reserved_keys.discard(message.message_key)
        self._log_bus.publish(
            f"Send succeeded [{message.event_kind}] request_id={inflight_send.request_id}",
            LogLevel.INFO,
        )
        return None

    def _make_message_key(
        self,
        *,
        event_kind: str,
        group_id: str,
        sender_id: str,
        message_ts_ms: int,
        text: str,
    ) -> str:
        payload = f"{event_kind}|{group_id}|{sender_id}|{message_ts_ms}|{text}".encode("utf-8")
        return hashlib.sha256(payload).hexdigest()

    def _set_worker_state(self, lifecycle_state: str) -> None:
        with self._lock:
            self._worker_state = lifecycle_state
        if self._supervisor is not None:
            self._supervisor.report_worker_lifecycle(lifecycle_state)

    def _classify_process_line(self, line: str, *, default_level: LogLevel) -> LogLevel:
        normalized = line.strip()
        upper = normalized.upper()
        if normalized.startswith("Picked up JAVA_TOOL_OPTIONS"):
            return LogLevel.INFO
        if " ERROR " in upper or upper.startswith("ERROR ") or upper.startswith("ERROR:"):
            return LogLevel.ERROR
        if " WARN " in upper or " WARNING " in upper or upper.startswith("WARN ") or upper.startswith("WARNING "):
            return LogLevel.WARNING
        if " INFO " in upper or upper.startswith("INFO ") or upper.startswith("INFO:"):
            return LogLevel.INFO
        return default_level
