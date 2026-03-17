from __future__ import annotations

from collections import deque

from app.services.forwarder import ForwardingWorker, ParsedIncomingMessage


def test_parse_receive_notification_data_message(configured_db, log_bus, dummy_signal_cli):
    worker = ForwardingWorker(configured_db, log_bus, dummy_signal_cli)
    payload = {
        "method": "receive",
        "params": {
            "envelope": {
                "timestamp": 1000,
                "sourceServiceId": "sender-1",
                "dataMessage": {
                    "timestamp": 1000,
                    "message": "hello",
                    "groupInfo": {"groupId": "source-group"},
                },
            }
        },
    }

    parsed = worker._parse_receive_notification(payload)

    assert parsed is not None
    assert parsed.event_kind == "dataMessage"
    assert parsed.group_id == "source-group"
    assert parsed.text == "hello"
    assert parsed.sender_id == "sender-1"


def test_parse_receive_notification_sync_sent_message(configured_db, log_bus, dummy_signal_cli):
    worker = ForwardingWorker(configured_db, log_bus, dummy_signal_cli)
    payload = {
        "method": "receive",
        "params": {
            "envelope": {
                "timestamp": 2000,
                "syncMessage": {
                    "sentMessage": {
                        "timestamp": 2000,
                        "message": "self-msg",
                        "groupInfo": {"groupId": "source-group"},
                    }
                },
            }
        },
    }

    parsed = worker._parse_receive_notification(payload)

    assert parsed is not None
    assert parsed.event_kind == "syncMessage.sentMessage"
    assert parsed.group_id == "source-group"
    assert parsed.text == "self-msg"
    assert parsed.sender_id == "self"


def test_backlog_cutoff_uses_max_of_recent_reconnect_and_quiet_exit(
    configured_db, log_bus, dummy_signal_cli, monkeypatch
):
    worker = ForwardingWorker(configured_db, log_bus, dummy_signal_cli)
    configured_db.update_runtime_status(last_reconnect_at_ms=150_000, last_quiet_exit_at_ms=160_000)
    monkeypatch.setattr("app.services.forwarder.time.time", lambda: 200.0)

    old_message = ParsedIncomingMessage(
        event_kind="dataMessage",
        group_id="source-group",
        text="too-old",
        message_ts_ms=159_999,
        sender_id="sender",
        message_key=worker._make_message_key(
            event_kind="dataMessage",
            group_id="source-group",
            sender_id="sender",
            message_ts_ms=159_999,
            text="too-old",
        ),
    )
    accepted_at_cutoff = ParsedIncomingMessage(
        event_kind="dataMessage",
        group_id="source-group",
        text="accepted",
        message_ts_ms=160_000,
        sender_id="sender",
        message_key=worker._make_message_key(
            event_kind="dataMessage",
            group_id="source-group",
            sender_id="sender",
            message_ts_ms=160_000,
            text="accepted",
        ),
    )

    reserved_keys: set[str] = set()
    outbound_queue: deque[ParsedIncomingMessage] = deque()
    worker._handle_incoming_message(old_message, "source-group", False, reserved_keys, outbound_queue)
    worker._handle_incoming_message(accepted_at_cutoff, "source-group", False, reserved_keys, outbound_queue)

    assert [message.text for message in outbound_queue] == ["accepted"]


def test_dedupe_uses_event_kind_and_db_state(configured_db, log_bus, dummy_signal_cli, monkeypatch):
    worker = ForwardingWorker(configured_db, log_bus, dummy_signal_cli)
    monkeypatch.setattr("app.services.forwarder.time.time", lambda: 200.0)

    data_key = worker._make_message_key(
        event_kind="dataMessage",
        group_id="source-group",
        sender_id="sender",
        message_ts_ms=200_000,
        text="same",
    )
    sync_key = worker._make_message_key(
        event_kind="syncMessage.sentMessage",
        group_id="source-group",
        sender_id="self",
        message_ts_ms=200_000,
        text="same",
    )
    assert data_key != sync_key

    configured_db.add_forwarded_message(
        message_key=data_key,
        source_group_id="source-group",
        message_ts_ms=200_000,
    )
    duplicate = ParsedIncomingMessage(
        event_kind="dataMessage",
        group_id="source-group",
        text="same",
        message_ts_ms=200_000,
        sender_id="sender",
        message_key=data_key,
    )
    fresh = ParsedIncomingMessage(
        event_kind="syncMessage.sentMessage",
        group_id="source-group",
        text="same",
        message_ts_ms=200_000,
        sender_id="self",
        message_key=sync_key,
    )

    reserved_keys: set[str] = set()
    outbound_queue: deque[ParsedIncomingMessage] = deque()
    worker._handle_incoming_message(duplicate, "source-group", False, reserved_keys, outbound_queue)
    worker._handle_incoming_message(fresh, "source-group", False, reserved_keys, outbound_queue)

    assert [message.event_kind for message in outbound_queue] == ["syncMessage.sentMessage"]
