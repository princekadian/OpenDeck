"""Domain models shared by repositories, services and the API."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel


class DomainModel(BaseModel):
    """Serialises to camelCase JSON for the frontend."""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class Profile(DomainModel):
    id: str
    name: str
    description: str = ""
    icon_ref: str | None = None
    sort_order: int = 0


class Page(DomainModel):
    id: str
    profile_id: str
    name: str
    icon_ref: str | None = None
    sort_order: int = 0
    # "deck" holds buttons; "monitor" shows the live System Monitoring dashboard.
    kind: Literal["deck", "monitor"] = "deck"


class Button(DomainModel):
    id: str
    page_id: str
    # Containing folder button; None = directly on the page.
    parent_id: str | None = None
    # "action" runs a registered action; "folder" contains other buttons (never runs anything).
    kind: Literal["action", "folder"] = "action"
    sort_order: int = 0
    label: str = ""
    description: str = ""
    icon_ref: str | None = None
    action_type: str
    action_config: dict[str, Any] = Field(default_factory=dict)
    appearance: dict[str, Any] = Field(default_factory=dict)
    state_config: dict[str, Any] = Field(default_factory=dict)
    enabled: bool = True


class Device(DomainModel):
    id: str
    name: str
    paired_at: str
    last_seen_at: str | None = None
    revoked: bool = False
