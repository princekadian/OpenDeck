"""Configuration management: profiles, pages and buttons.

The single place that validates and mutates deck configuration. Every successful
mutation calls `on_change` so connected devices receive the new configuration.
"""

from __future__ import annotations

import logging
import re
import uuid
from collections.abc import Callable
from typing import Annotated, Any, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, ValidationError
from pydantic.alias_generators import to_camel

from ..actions import ActionRegistry, ActionStatus
from ..db import Database
from ..models import Button, Page, Profile
from ..repositories import ButtonRepository, PageRepository, ProfileRepository, SettingsRepository
from .assets import AssetStore

log = logging.getLogger(__name__)

ACTIVE_PROFILE_KEY = "active_profile_id"
_ICON_REF = re.compile(r"^(builtin:[a-z0-9-]{1,40}|asset:[0-9a-f]{64}\.png)$")


class ConfigError(Exception):
    def __init__(self, code: str, message: str, *, status: int = 400,
                 fields: dict[str, str] | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status
        self.fields = fields or {}


class _Input(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, extra="forbid")


def _clean_name(value: str) -> str:
    value = " ".join(value.split())
    if not value:
        raise ValueError("Name is required.")
    return value


Name = Annotated[str, Field(max_length=40), AfterValidator(_clean_name)]


class ProfileInput(_Input):
    name: Name
    description: str = Field(default="", max_length=200)
    icon_ref: str | None = None


class PageInput(_Input):
    name: Name
    icon_ref: str | None = None
    # Only used when creating; a page keeps its kind.
    kind: Literal["deck", "monitor"] = "deck"


class ButtonInput(_Input):
    kind: Literal["action", "folder"] = "action"
    # Only used when creating: the folder to create the button in (None = the page).
    parent_id: str | None = None
    label: str = Field(default="", max_length=40)
    description: str = Field(default="", max_length=200)
    icon_ref: str | None = None
    action_type: str = Field(default="", max_length=64)
    action_config: dict[str, Any] = Field(default_factory=dict)
    appearance: dict[str, Any] = Field(default_factory=dict)
    enabled: bool = True


class ConfigService:
    def __init__(self, db: Database, settings: SettingsRepository, profiles: ProfileRepository,
                 pages: PageRepository, buttons: ButtonRepository, registry: ActionRegistry,
                 assets: AssetStore) -> None:
        self._db = db
        self._settings = settings
        self._profiles = profiles
        self._pages = pages
        self._buttons = buttons
        self._registry = registry
        self._assets = assets
        self._listeners: list[Callable[[], None]] = []

    def subscribe(self, listener: Callable[[], None]) -> None:
        self._listeners.append(listener)

    def _changed(self) -> None:
        for listener in self._listeners:
            listener()

    # ---- reads ------------------------------------------------------------

    def active_profile_id(self) -> str | None:
        stored = self._settings.get(ACTIVE_PROFILE_KEY)
        if stored and self._profiles.get(stored):
            return stored
        profiles = self._profiles.list()
        return profiles[0].id if profiles else None

    def full_tree(self) -> dict[str, Any]:
        """Complete configuration including action settings. PC-side editor only."""
        return {
            "activeProfileId": self.active_profile_id(),
            "profiles": [p.model_dump(by_alias=True) for p in self._profiles.list()],
            "pages": [p.model_dump(by_alias=True) for p in self._pages.list_all()],
            "buttons": [b.model_dump(by_alias=True) for b in self._buttons.list_all()],
        }

    # ---- profiles ---------------------------------------------------------

    def create_profile(self, data: ProfileInput) -> Profile:
        self._check_icon(data.icon_ref)
        with self._db.transaction():
            profile = Profile(id=_new_id(), name=data.name, description=data.description,
                              icon_ref=data.icon_ref, sort_order=self._profiles.next_sort_order())
            self._profiles.create(profile)
            # A profile is always usable: give it a first page.
            self._pages.create(Page(id=_new_id(), profile_id=profile.id, name="Main"))
        log.info("Profile created: %s", profile.name)
        self._changed()
        return profile

    def update_profile(self, profile_id: str, data: ProfileInput) -> Profile:
        profile = self._require_profile(profile_id)
        self._check_icon(data.icon_ref)
        updated = profile.model_copy(update={"name": data.name, "description": data.description,
                                             "icon_ref": data.icon_ref})
        self._profiles.update(updated)
        self._changed()
        return updated

    def delete_profile(self, profile_id: str) -> None:
        self._require_profile(profile_id)
        if len(self._profiles.list()) <= 1:
            raise ConfigError("LAST_PROFILE", "Keep at least one profile.", status=409)
        self._profiles.delete(profile_id)
        log.info("Profile deleted: %s", profile_id)
        self._changed()

    def duplicate_profile(self, profile_id: str) -> Profile:
        source = self._require_profile(profile_id)
        with self._db.transaction():
            copy = source.model_copy(update={"id": _new_id(), "name": _copy_name(source.name, 40),
                                             "sort_order": source.sort_order + 1})
            self._shift_profiles_after(source.sort_order)
            self._profiles.create(copy)
            for page in self._pages.list_pages(source.id):
                self._copy_page(page, copy.id, page.name, page.sort_order)
        self._changed()
        return copy

    def reorder_profiles(self, ordered_ids: list[str]) -> None:
        _require_same_ids(ordered_ids, [p.id for p in self._profiles.list()])
        self._profiles.reorder(ordered_ids)
        self._changed()

    def set_active_profile(self, profile_id: str) -> None:
        self._require_profile(profile_id)
        self._settings.set(ACTIVE_PROFILE_KEY, profile_id)
        self._changed()

    # ---- pages ------------------------------------------------------------

    def create_page(self, profile_id: str, data: PageInput) -> Page:
        self._require_profile(profile_id)
        self._check_icon(data.icon_ref)
        page = Page(id=_new_id(), profile_id=profile_id, name=data.name, icon_ref=data.icon_ref,
                    sort_order=self._pages.next_sort_order(profile_id), kind=data.kind)
        self._pages.create(page)
        self._changed()
        return page

    def update_page(self, page_id: str, data: PageInput) -> Page:
        page = self._require_page(page_id)
        self._check_icon(data.icon_ref)
        updated = page.model_copy(update={"name": data.name, "icon_ref": data.icon_ref})
        self._pages.update(updated)
        self._changed()
        return updated

    def delete_page(self, page_id: str) -> None:
        page = self._require_page(page_id)
        if len(self._pages.list_pages(page.profile_id)) <= 1:
            raise ConfigError("LAST_PAGE", "A profile needs at least one page.", status=409)
        self._pages.delete(page_id)
        self._changed()

    def duplicate_page(self, page_id: str) -> Page:
        source = self._require_page(page_id)
        with self._db.transaction():
            siblings = self._pages.list_pages(source.profile_id)
            copy = self._copy_page(source, source.profile_id, _copy_name(source.name, 40),
                                   source.sort_order + 1)
            order = [p.id for p in siblings]
            order.insert(order.index(source.id) + 1, copy.id)
            self._pages.reorder(order)
        self._changed()
        return copy

    def reorder_pages(self, profile_id: str, ordered_ids: list[str]) -> None:
        self._require_profile(profile_id)
        _require_same_ids(ordered_ids, [p.id for p in self._pages.list_pages(profile_id)])
        self._pages.reorder(ordered_ids)
        self._changed()

    # ---- buttons ----------------------------------------------------------

    def create_button(self, page_id: str, data: ButtonInput) -> Button:
        if self._require_page(page_id).kind != "deck":
            raise ConfigError("NOT_A_DECK_PAGE", "This page shows System Monitoring and has no buttons.", status=409)
        parent_id = data.parent_id or None
        if parent_id is not None:
            self._require_folder(parent_id, page_id)
        config = self._validate_button(data)
        button = Button(
            id=_new_id(), page_id=page_id, parent_id=parent_id, kind=data.kind,
            sort_order=self._buttons.next_sort_order(page_id, parent_id),
            label=data.label, description=data.description, icon_ref=data.icon_ref,
            action_type=data.action_type if data.kind == "action" else "", action_config=config,
            appearance=data.appearance, enabled=data.enabled,
        )
        self._buttons.create(button)
        log.info("%s created: %s", "Folder" if button.kind == "folder" else "Button", button.label)
        self._changed()
        return button

    def update_button(self, button_id: str, data: ButtonInput) -> Button:
        button = self._require_button(button_id)
        if button.kind == "folder" and data.kind == "action" and self._buttons.descendants(button_id):
            raise ConfigError("FOLDER_NOT_EMPTY", "Move or delete the buttons inside this folder first.",
                              status=409)
        config = self._validate_button(data)
        updated = button.model_copy(update={
            "kind": data.kind, "label": data.label, "description": data.description,
            "icon_ref": data.icon_ref, "action_type": data.action_type if data.kind == "action" else "",
            "action_config": config, "appearance": data.appearance, "enabled": data.enabled,
        })
        self._buttons.update(updated)
        self._changed()
        return updated

    def set_button_enabled(self, button_id: str, enabled: bool) -> Button:
        button = self._require_button(button_id)
        updated = button.model_copy(update={"enabled": enabled})
        self._buttons.update(updated)
        self._changed()
        return updated

    def delete_button(self, button_id: str) -> None:
        self._require_button(button_id)
        self._buttons.delete(button_id)
        self._changed()

    def duplicate_button(self, button_id: str) -> Button:
        """Copy a button next to the original. A folder is copied with everything inside it."""
        source = self._require_button(button_id)
        with self._db.transaction():
            copy_id = self._copy_tree(source, source.page_id, source.parent_id,
                                      label=_copy_name(source.label, 40))
            order = [b.id for b in self._buttons.list_children(source.page_id, source.parent_id)
                     if b.id != copy_id]
            order.insert(order.index(source.id) + 1, copy_id)
            self._buttons.reorder(order)
        self._changed()
        return self._buttons.get(copy_id)  # type: ignore[return-value]

    def reorder_buttons(self, page_id: str, ordered_ids: list[str], parent_id: str | None = None) -> None:
        self._require_page(page_id)
        if parent_id:
            self._require_folder(parent_id, page_id)
        _require_same_ids(ordered_ids, [b.id for b in self._buttons.list_children(page_id, parent_id or None)])
        self._buttons.reorder(ordered_ids)
        self._changed()

    def move_button(self, button_id: str, target_page_id: str, target_parent_id: str | None = None) -> Button:
        """Move into another page or folder (appended at the end). Folders move with their contents."""
        button = self._require_button(button_id)
        if self._require_page(target_page_id).kind != "deck":
            raise ConfigError("NOT_A_DECK_PAGE", "This page shows System Monitoring and has no buttons.", status=409)
        target_parent_id = target_parent_id or None
        if target_parent_id is not None:
            if target_parent_id == button_id or target_parent_id in {d.id for d in self._buttons.descendants(button_id)}:
                raise ConfigError("CIRCULAR_FOLDER", "A folder can't be moved into itself.", status=409)
            self._require_folder(target_parent_id, target_page_id)
        if (button.page_id, button.parent_id) == (target_page_id, target_parent_id):
            return button
        with self._db.transaction():
            moved = button.model_copy(update={"page_id": target_page_id, "parent_id": target_parent_id})
            self._buttons.update(moved)
            if button.page_id != target_page_id:
                self._buttons.set_page([d.id for d in self._buttons.descendants(button_id)], target_page_id)
            self._buttons.normalize_order(button.page_id, button.parent_id)
            order = [b.id for b in self._buttons.list_children(target_page_id, target_parent_id) if b.id != button_id]
            self._buttons.reorder([*order, button_id])
        self._changed()
        return self._buttons.get(button_id)  # type: ignore[return-value]

    def _copy_tree(self, source: Button, page_id: str, parent_id: str | None, *, label: str | None = None) -> str:
        """Copy a button (and, for a folder, its whole subtree) with new ids; returns the new id."""
        new_id = _new_id()
        self._buttons.create(source.model_copy(update={
            "id": new_id, "page_id": page_id, "parent_id": parent_id,
            **({"label": label} if label is not None else {}),
        }))
        if source.kind == "folder":
            for child in self._buttons.list_children(source.page_id, source.id):
                self._copy_tree(child, page_id, new_id)
        return new_id

    def _require_folder(self, folder_id: str, page_id: str) -> Button:
        folder = self._buttons.get(folder_id)
        if folder is None or folder.kind != "folder":
            raise ConfigError("NOT_FOUND", "Folder not found.", status=404)
        if folder.page_id != page_id:
            raise ConfigError("WRONG_PAGE", "That folder belongs to another page.", status=409)
        return folder

    # ---- helpers ----------------------------------------------------------

    def _validate_button(self, data: ButtonInput) -> dict[str, Any]:
        self._check_icon(data.icon_ref)
        if data.kind == "folder":
            if not data.label.strip():
                raise ConfigError("INVALID_INPUT", "Give the folder a name.", fields={"label": "Enter a name."})
            return {}  # a folder has no action and no settings
        action = self._registry.get(data.action_type)
        if action is None:
            raise ConfigError("UNKNOWN_ACTION", f"Unknown action type '{data.action_type}'.")
        if action.status != ActionStatus.AVAILABLE:
            raise ConfigError("NOT_AVAILABLE", f"{action.display_name} is coming soon and can't be used yet.")
        try:
            parsed = action.parse_config(data.action_config)
        except ValidationError as exc:
            # Keyed by top-level setting so the editor can show the message under that field.
            fields: dict[str, str] = {}
            for err in exc.errors():
                fields.setdefault(str(err["loc"][0]) if err["loc"] else "config", _friendly(err))
            raise ConfigError("INVALID_CONFIG", "Check the highlighted fields.",
                              fields=fields) from exc
        return parsed.model_dump(mode="json", by_alias=True, exclude_none=True)

    def _check_icon(self, icon_ref: str | None) -> None:
        if icon_ref is None:
            return
        if not _ICON_REF.match(icon_ref):
            raise ConfigError("INVALID_ICON", "Unknown icon.")
        if icon_ref.startswith("asset:") and not self._assets.exists(icon_ref.removeprefix("asset:")):
            raise ConfigError("INVALID_ICON", "The selected icon file is missing.")

    def _copy_page(self, source: Page, profile_id: str, name: str, sort_order: int) -> Page:
        copy = Page(id=_new_id(), profile_id=profile_id, name=name, icon_ref=source.icon_ref,
                    sort_order=sort_order, kind=source.kind)
        self._pages.create(copy)
        for button in self._buttons.list_for_page(source.id):
            self._copy_tree(button, copy.id, None)
        return copy

    def _shift_profiles_after(self, sort_order: int) -> None:
        self._db.execute("UPDATE profiles SET sort_order = sort_order + 1 WHERE sort_order > ?",
                         (sort_order,))

    def _require_profile(self, profile_id: str) -> Profile:
        profile = self._profiles.get(profile_id)
        if profile is None:
            raise ConfigError("NOT_FOUND", "Profile not found.", status=404)
        return profile

    def _require_page(self, page_id: str) -> Page:
        page = self._pages.get(page_id)
        if page is None:
            raise ConfigError("NOT_FOUND", "Page not found.", status=404)
        return page

    def _require_button(self, button_id: str) -> Button:
        button = self._buttons.get(button_id)
        if button is None:
            raise ConfigError("NOT_FOUND", "Button not found.", status=404)
        return button


def _new_id() -> str:
    return str(uuid.uuid4())


def _copy_name(name: str, limit: int) -> str:
    suffix = " copy"
    return (name[: limit - len(suffix)] + suffix) if name else ""


def _require_same_ids(given: list[str], existing: list[str]) -> None:
    if len(given) != len(existing) or set(given) != set(existing):
        raise ConfigError("STALE_ORDER", "The list changed. Reload and try again.", status=409)


def _friendly(error: dict[str, Any]) -> str:
    message = str(error.get("msg", "Invalid value."))
    return message.removeprefix("Value error, ")
