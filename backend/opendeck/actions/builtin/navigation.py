"""Navigation actions: change what the pressing device shows.

The server tells only the device session that pressed the key (NAVIGATE message);
other devices keep their own view.
"""

from __future__ import annotations

from pydantic import Field

from ..base import Action, ActionConfig, ActionContext, ActionError, ActionOutcome, EmptyConfig
from ._common import PAGE, PROFILE, runtime


class PageConfig(ActionConfig):
    page_id: str = Field(title="Page", min_length=1, max_length=64, json_schema_extra=PAGE)


class ProfileConfig(ActionConfig):
    profile_id: str = Field(title="Profile", min_length=1, max_length=64, json_schema_extra=PROFILE)


async def _navigate(ctx: ActionContext, command: dict) -> ActionOutcome:
    if ctx.session_id is None:
        raise ActionError("DEVICE_ONLY", "Navigation changes a device's view. Press it on the iPad to try it.")
    if not await runtime(ctx).navigate(ctx.session_id, command):
        raise ActionError("DEVICE_GONE", "The device disconnected.")
    return ActionOutcome(message="", data=command)


class GoToPageAction(Action[PageConfig]):
    type = "go_to_page"
    display_name = "Go to page"
    description = "Show another page on this device."
    category = "navigation"
    icon = "page"
    config_model = PageConfig

    async def execute(self, config: PageConfig, ctx: ActionContext) -> ActionOutcome:
        return await _navigate(ctx, {"pageId": config.page_id})


class GoToProfileAction(Action[ProfileConfig]):
    type = "go_to_profile"
    display_name = "Go to profile"
    description = "Switch this device to another profile."
    category = "navigation"
    icon = "profile"
    config_model = ProfileConfig

    async def execute(self, config: ProfileConfig, ctx: ActionContext) -> ActionOutcome:
        return await _navigate(ctx, {"profileId": config.profile_id})


class GoBackAction(Action[EmptyConfig]):
    type = "go_back"
    display_name = "Go back"
    description = "Return to the page this device showed before."
    category = "navigation"
    icon = "back"

    async def execute(self, config: EmptyConfig, ctx: ActionContext) -> ActionOutcome:
        return await _navigate(ctx, {"back": True})
