"""First-run default content so a fresh install shows a usable deck."""

from __future__ import annotations

import logging
import uuid

from ..models import Button, Page, Profile
from ..repositories import ButtonRepository, PageRepository, ProfileRepository, SettingsRepository

log = logging.getLogger(__name__)

SEEDED_KEY = "seeded_v1"
MONITOR_SEEDED_KEY = "seeded_monitor_v1"


def seed_defaults(settings: SettingsRepository, profiles: ProfileRepository,
                  pages: PageRepository, buttons: ButtonRepository) -> None:
    if settings.get(SEEDED_KEY) == "1":
        return
    profile = Profile(id=str(uuid.uuid4()), name="Main")
    profiles.create(profile)
    page = Page(id=str(uuid.uuid4()), profile_id=profile.id, name="Home")
    pages.create(page)
    buttons.create(Button(id=str(uuid.uuid4()), page_id=page.id, label="Lock PC",
                          icon_ref="builtin:lock", action_type="lock_windows"))
    settings.set("active_profile_id", profile.id)
    settings.set(SEEDED_KEY, "1")
    log.info("Seeded default profile and page")


def seed_monitor_page(settings: SettingsRepository, pages: PageRepository) -> None:
    """Once: add a System Monitoring page to the profile devices open first."""
    if settings.get(MONITOR_SEEDED_KEY) == "1":
        return
    profile_id = settings.get("active_profile_id")
    all_pages = pages.list_all()
    if not any(p.profile_id == profile_id for p in all_pages):
        profile_id = all_pages[0].profile_id if all_pages else None
    if profile_id and not any(p.kind == "monitor" for p in all_pages):
        pages.create(Page(id=str(uuid.uuid4()), profile_id=profile_id, name="System Monitoring",
                          icon_ref="builtin:activity", sort_order=pages.next_sort_order(profile_id),
                          kind="monitor"))
        log.info("Added the System Monitoring page")
    settings.set(MONITOR_SEEDED_KEY, "1")
