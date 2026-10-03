from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from opendeck.actions import ActionError
from opendeck.protocol import CloseCode

from .conftest import hello


def _connect(client: TestClient, token: str):
    ws = client.websocket_connect("/ws")
    session = ws.__enter__()
    session.send_json(hello(token))
    welcome = session.receive_json()
    snapshot = session.receive_json()
    return ws, session, welcome, snapshot


def test_full_action_round_trip(client, paired_token, lock_action) -> None:
    ws, session, welcome, snapshot = _connect(client, paired_token)
    try:
        assert welcome["type"] == "WELCOME" and welcome["payload"]["protocolVersion"] == 2
        assert snapshot["type"] == "SNAPSHOT"
        button = snapshot["payload"]["buttons"][0]
        assert "actionConfig" not in button  # config never leaves the PC

        session.send_json({"version": 2, "type": "ACTION_EXECUTE", "requestId": "r1",
                           "payload": {"buttonId": button["id"]}})
        result = session.receive_json()
        assert result == {
            "version": 2, "type": "ACTION_RESULT", "requestId": "r1", "success": True,
            "payload": {"buttonId": button["id"], "message": "Windows locked", "data": {}},
        }
        assert len(lock_action.calls) == 1
    finally:
        ws.__exit__(None, None, None)


def test_action_failure_reported(client, paired_token, lock_action) -> None:
    lock_action.fail_with = ActionError("PLATFORM_ERROR", "LockWorkStation failed")
    ws, session, _, snapshot = _connect(client, paired_token)
    try:
        button_id = snapshot["payload"]["buttons"][0]["id"]
        session.send_json({"version": 2, "type": "ACTION_EXECUTE", "requestId": "r2",
                           "payload": {"buttonId": button_id}})
        result = session.receive_json()
        assert result["success"] is False
        assert result["error"] == {"code": "PLATFORM_ERROR", "message": "LockWorkStation failed"}
    finally:
        ws.__exit__(None, None, None)


def test_ping_and_unknown_type(client, paired_token) -> None:
    ws, session, _, _ = _connect(client, paired_token)
    try:
        session.send_json({"version": 2, "type": "PING", "requestId": "p"})
        assert session.receive_json()["type"] == "PONG"
        session.send_json({"version": 2, "type": "RUN_SHELL", "payload": {"cmd": "calc"}})
        error = session.receive_json()
        assert error["type"] == "ERROR" and error["error"]["code"] == "unknown_type"
        session.send_text("not json")
        assert session.receive_json()["error"]["code"] == "bad_message"
    finally:
        ws.__exit__(None, None, None)


def test_bad_token_rejected(client) -> None:
    with client.websocket_connect("/ws") as session:
        session.send_json(hello("x" * 43))
        assert session.receive_json()["error"]["code"] == "auth_failed"
        with pytest.raises(WebSocketDisconnect) as exc:
            session.receive_json()
        assert exc.value.code == CloseCode.AUTH_FAILED


def test_action_before_hello_rejected(client, lock_action) -> None:
    with client.websocket_connect("/ws") as session:
        session.send_json({"version": 2, "type": "ACTION_EXECUTE", "payload": {"buttonId": "x"}})
        with pytest.raises(WebSocketDisconnect) as exc:
            session.receive_json()
        assert exc.value.code == CloseCode.AUTH_REQUIRED
    assert lock_action.calls == []


def test_unsupported_version_rejected(client, paired_token) -> None:
    with client.websocket_connect("/ws") as session:
        session.send_json(hello(paired_token, version=1))
        assert session.receive_json()["error"]["code"] == "unsupported_version"
        with pytest.raises(WebSocketDisconnect) as exc:
            session.receive_json()
        assert exc.value.code == CloseCode.UNSUPPORTED_VERSION
