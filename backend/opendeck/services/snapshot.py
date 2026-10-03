"""Builds the complete dashboard state sent to clients on connect and on change."""

from __future__ import annotations

from typing import Any

from ..actions import ActionRegistry
from ..models import Button
from ..repositories import ButtonRepository, PageRepository, ProfileRepository
from .config import ConfigService
from .state import StateManager


class SnapshotService:
    def __init__(self, config: ConfigService, profiles: ProfileRepository, pages: PageRepository,
                 buttons: ButtonRepository, states: StateManager, registry: ActionRegistry) -> None:
        self._config = config
        self._profiles = profiles
        self._pages = pages
        self._buttons = buttons
        self._states = states
        self._registry = registry

    def build(self) -> dict[str, Any]:
        return {
            "activeProfileId": self._config.active_profile_id(),
            "profiles": [p.model_dump(by_alias=True, include={"id", "name", "icon_ref", "sort_order"})
                         for p in self._profiles.list()],
            "pages": [p.model_dump(by_alias=True) for p in self._pages.list_all()],
            "buttons": [self._client_button(b) for b in self._buttons.list_all()],
            "states": self._states.snapshot(),
        }

    def _client_button(self, button: Button) -> dict[str, Any]:
        """What a device needs to draw and press a key. Action settings (paths, URLs,
        scripts) are never included."""
        action = self._registry.get(button.action_type)
        confirm = False
        if action is not None:
            try:
                confirm = action.requires_confirmation(action.parse_config(button.action_config))
            except Exception:
                confirm = False
        if button.kind == "folder":
            action, icon = None, button.icon_ref or "builtin:folder"
        else:
            icon = button.icon_ref or (f"builtin:{action.icon}" if action else None)
        return {
            "id": button.id,
            "pageId": button.page_id,
            "parentId": button.parent_id,
            "kind": button.kind,
            "sortOrder": button.sort_order,
            "label": button.label,
            "iconRef": icon,
            "actionType": button.action_type,
            "appearance": button.appearance,
            "enabled": button.enabled,
            "confirm": confirm,
        }
