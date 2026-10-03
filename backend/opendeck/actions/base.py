"""Action contract. Built-in actions and future plugins implement this.

An action is one registry entry: identity + menu placement (category, name, icon),
a Pydantic configuration model (which also drives the editor form), an executor,
and optionally a state reader for two-way button state.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING, Any, ClassVar, Generic, TypeVar

from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel

if TYPE_CHECKING:
    from ..services.state import ButtonState
    from .runtime import ActionRuntime


class ActionConfig(BaseModel):
    """Base for action settings: camelCase JSON, unknown fields rejected."""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, extra="forbid")


class EmptyConfig(ActionConfig):
    pass


ConfigT = TypeVar("ConfigT", bound=BaseModel)


class ActionStatus(StrEnum):
    AVAILABLE = "available"
    COMING_SOON = "coming_soon"


@dataclass(frozen=True)
class ActionContext:
    button_id: str
    device_id: str | None
    session_id: str | None = None
    runtime: "ActionRuntime | None" = None
    # Nesting level for Multi Action / Toggle, to stop runaway recursion.
    depth: int = 0


@dataclass(frozen=True)
class ActionOutcome:
    message: str = ""
    data: dict[str, Any] = field(default_factory=dict)


class ActionError(Exception):
    """Expected, user-presentable failure (bad path, missing device, Win32 error)."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class Action(ABC, Generic[ConfigT]):
    type: ClassVar[str]
    display_name: ClassVar[str]
    description: ClassVar[str]
    category: ClassVar[str] = "advanced"
    icon: ClassVar[str] = "key"
    config_model: ClassVar[type[BaseModel]] = EmptyConfig
    status: ClassVar[ActionStatus] = ActionStatus.AVAILABLE
    # Runs commands the user wrote (PowerShell, shell): the editor shows a warning.
    trusted_only: ClassVar[bool] = False
    # Ends the session or closes work (shut down, sign out, close app): the editor's
    # Test button asks before running it.
    destructive: ClassVar[bool] = False
    # Button state: read_state() is called after presses and on config changes;
    # actions that reflect outside changes (volume, running apps) are also polled.
    stateful: ClassVar[bool] = False
    polled: ClassVar[bool] = False
    # Hidden from the top-level menu but usable as a Multi Action step (none yet).
    step_only: ClassVar[bool] = False

    def bind(self, registry: Any) -> None:
        """Called once at registration; composite actions keep the registry."""

    def parse_config(self, raw: dict[str, Any]) -> ConfigT:
        return self.config_model.model_validate(raw)  # type: ignore[return-value]

    def requires_confirmation(self, config: ConfigT) -> bool:
        """True when a device must tap twice (destructive actions such as Shut down)."""
        return False

    @abstractmethod
    async def execute(self, config: ConfigT, ctx: ActionContext) -> ActionOutcome: ...

    async def read_state(self, config: ConfigT, ctx: ActionContext) -> "ButtonState | None":
        return None

    def describe(self) -> dict[str, Any]:
        """Registry entry for the editor: menu placement and configuration form."""
        return {
            "type": self.type,
            "displayName": self.display_name,
            "description": self.description,
            "category": self.category,
            "icon": self.icon,
            "status": self.status.value,
            "trustedOnly": self.trusted_only,
            "destructive": self.destructive,
            "stateful": self.stateful,
            "configSchema": self.config_model.model_json_schema(by_alias=True),
        }


class ComingSoonAction(Action[EmptyConfig]):
    """Listed in the menu so the plan is visible, but cannot be saved or run yet."""

    status = ActionStatus.COMING_SOON

    async def execute(self, config: EmptyConfig, ctx: ActionContext) -> ActionOutcome:
        raise ActionError("NOT_AVAILABLE", f"{self.display_name} is not available yet.")
