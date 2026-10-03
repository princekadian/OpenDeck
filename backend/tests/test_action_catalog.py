"""The action menu: exact structure, metadata, and coming-soon handling."""

from __future__ import annotations

import pytest

from opendeck.actions import ActionStatus, build_default_registry
from opendeck.services.config import ButtonInput, ConfigError

EXPECTED_MENU = {
    "Open": ["Launch application", "Open website", "Open file", "Open folder"],
    "System": ["Lock Windows", "Shutdown", "Restart", "Sleep", "Hibernate", "Sign out",
               "Open Task Manager", "Open Settings"],
    "Audio": ["Volume up", "Volume down", "Set volume", "Mute / unmute", "Increase microphone volume",
              "Decrease microphone volume", "Mute microphone", "Change audio output device",
              "Change microphone device"],
    "Media": ["Play / Pause", "Previous track", "Next track", "Stop", "Volume up", "Volume down"],
    "Keyboard": ["Hotkey", "Type text", "Key press", "Key combination"],
    "Display": ["Brightness up", "Brightness down", "Set brightness", "Change display", "Toggle HDR"],
    "Window": ["Minimize active window", "Maximize active window", "Close active window",
               "Restore window", "Switch application", "Move window", "Resize window"],
    "Applications": ["Launch application", "Close application", "Restart application",
                     "Focus application", "Check if application is running"],
    "Navigation": ["Go to page", "Go to profile", "Go back", "Open folder", "Open URL"],
    "Workflow": ["Multi Action", "Delay", "Toggle", "Counter", "Timer"],
    "Streaming": ["OBS: Start streaming", "OBS: Stop streaming", "OBS: Start recording",
                  "OBS: Stop recording", "OBS: Pause recording", "OBS: Change scene",
                  "OBS: Toggle source", "OBS: Toggle microphone", "OBS: Toggle camera"],
    "Advanced": ["Run PowerShell", "Run command", "Send HTTP request", "WebSocket action"],
}


def test_menu_matches_specification_exactly() -> None:
    catalog = build_default_registry().catalog()
    labels = {c["id"]: c["label"] for c in catalog["categories"]}
    menu: dict[str, list[str]] = {}
    for action in catalog["actions"]:
        menu.setdefault(labels[action["category"]], []).append(action["displayName"])
    assert list(menu) == list(EXPECTED_MENU)
    assert menu == EXPECTED_MENU


def test_every_action_has_unique_id_icon_and_schema() -> None:
    actions = build_default_registry().catalog()["actions"]
    assert len({a["type"] for a in actions}) == len(actions)
    for action in actions:
        assert action["icon"] and action["description"], action["type"]
        assert action["configSchema"]["type"] == "object"


def test_every_listed_action_is_available() -> None:
    assert all(a.status == ActionStatus.AVAILABLE for a in build_default_registry().all())


def test_coming_soon_actions_cannot_be_saved_or_run(services) -> None:
    """The mechanism stays for future actions: listed, but rejected on save and on run."""
    import asyncio

    from opendeck.actions import ActionError
    from opendeck.actions.base import ComingSoonAction

    class Future(ComingSoonAction):
        type = "future_thing"
        category = "advanced"
        display_name = "Future thing"
        description = "Not yet."

    services.registry.register(Future())
    page = services.pages.list_all()[0]
    with pytest.raises(ConfigError) as exc:
        services.deck_config.create_button(page.id, ButtonInput(label="x", action_type="future_thing"))
    assert exc.value.code == "NOT_AVAILABLE"
    with pytest.raises(ActionError) as run:
        asyncio.run(services.engine.execute_draft("future_thing", {}))
    assert run.value.code == "NOT_AVAILABLE"


def test_existing_action_ids_unchanged() -> None:
    """Milestone 2 buttons keep working: their stored ids still resolve to the same actions."""
    registry = build_default_registry()
    for type_ in ("launch_application", "open_url", "open_file", "open_folder", "lock_windows"):
        assert registry.get(type_) is not None


def test_shared_executors_have_their_own_ids() -> None:
    registry = build_default_registry()
    assert type(registry.get("nav_open_url")).execute is type(registry.get("open_url")).execute
    assert type(registry.get("media_volume_up")).execute is type(registry.get("volume_up")).execute
    assert registry.get("app_launch").category == "applications"
