from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from opendeck.actions import Action, ActionContext, ActionError, ActionOutcome, ActionRegistry
from opendeck.actions.base import EmptyConfig
from opendeck.app import Services, build_services
from opendeck.config import AppConfig
from opendeck.server.http import create_app


class RecordingLockAction(Action[EmptyConfig]):
    """Stands in for lock_windows so tests never lock the developer's PC."""

    type = "lock_windows"
    category = "system"
    display_name = "Lock Windows (test)"
    description = "Records calls instead of locking."

    def __init__(self) -> None:
        super().__init__()
        self.calls: list[ActionContext] = []
        self.fail_with: ActionError | None = None

    async def execute(self, config: EmptyConfig, ctx: ActionContext) -> ActionOutcome:
        self.calls.append(ctx)
        if self.fail_with:
            raise self.fail_with
        return ActionOutcome(message="Windows locked")


@pytest.fixture
def lock_action() -> RecordingLockAction:
    return RecordingLockAction()


def make_registry(lock_action: "RecordingLockAction") -> ActionRegistry:
    """The real built-in registry, with Lock replaced so tests never lock the PC."""
    from opendeck.actions.builtin import all_builtin_actions

    registry = ActionRegistry()
    for action in all_builtin_actions():
        registry.register(lock_action if action.type == "lock_windows" else action)
    return registry


@pytest.fixture
def services(tmp_path: Path, lock_action: RecordingLockAction) -> Iterator[Services]:
    svc = build_services(AppConfig(data_dir=tmp_path, port=0), registry=make_registry(lock_action))
    yield svc
    svc.audio.close()
    svc.db.close()


@pytest.fixture
def client(services: Services) -> TestClient:
    return TestClient(create_app(services))


@pytest.fixture
def paired_token(client: TestClient, services: Services) -> str:
    code, _ = services.pairing.current_code()
    response = client.post("/api/pair", json={"code": code, "deviceName": "Test iPad"})
    assert response.status_code == 200
    return response.json()["token"]


def hello(token: str, version: int = 2) -> dict:
    return {"version": version, "type": "HELLO", "payload": {"token": token}}
