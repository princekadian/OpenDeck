from __future__ import annotations

import asyncio
import uuid

import pytest

from opendeck.actions import ActionError, build_default_registry
from opendeck.models import Button


def _first_button(services) -> Button:
    return services.buttons.list_for_profile(services.deck_config.active_profile_id())[0]


def test_engine_executes_stored_action(services, lock_action) -> None:
    button = _first_button(services)
    outcome = asyncio.run(services.engine.execute_button(button.id, "dev-1"))
    assert outcome.message == "Windows locked"
    assert lock_action.calls[0].button_id == button.id


def test_unknown_button_rejected(services) -> None:
    with pytest.raises(ActionError) as exc:
        asyncio.run(services.engine.execute_button("nope", None))
    assert exc.value.code == "UNKNOWN_BUTTON"


def test_unknown_action_type_rejected(services) -> None:
    page_id = _first_button(services).page_id
    bad = Button(id=str(uuid.uuid4()), page_id=page_id, sort_order=1, action_type="format_c")
    services.buttons.create(bad)
    with pytest.raises(ActionError) as exc:
        asyncio.run(services.engine.execute_button(bad.id, None))
    assert exc.value.code == "UNKNOWN_ACTION"


def test_invalid_config_rejected(services) -> None:
    page_id = _first_button(services).page_id
    bad = Button(id=str(uuid.uuid4()), page_id=page_id, sort_order=2,
                 action_type="lock_windows", action_config={"unexpected": True})
    services.buttons.create(bad)
    with pytest.raises(ActionError) as exc:
        asyncio.run(services.engine.execute_button(bad.id, None))
    assert exc.value.code == "INVALID_CONFIG"


def test_default_registry_describes_lock() -> None:
    described = {a["type"]: a for a in (x.describe() for x in build_default_registry().all())}
    assert described["lock_windows"]["category"] == "system"
    assert "configSchema" in described["lock_windows"]


def test_disabled_button_is_not_executed(services, lock_action) -> None:
    button = _first_button(services)
    services.deck_config.set_button_enabled(button.id, False)
    with pytest.raises(ActionError) as exc:
        asyncio.run(services.engine.execute_button(button.id, None))
    assert exc.value.code == "BUTTON_DISABLED"
    assert lock_action.calls == []
