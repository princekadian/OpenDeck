from __future__ import annotations

import pytest

from opendeck.services.config import (
    ButtonInput, ConfigError, PageInput, ProfileInput,
)


@pytest.fixture
def cfg(services):
    return services.deck_config


def _page_buttons(services, page_id):
    return [b.label for b in services.buttons.list_for_page(page_id)]


def _url_button(label: str, url: str = "https://example.com") -> ButtonInput:
    return ButtonInput(label=label, action_type="open_url", action_config={"url": url})


def test_create_profile_gets_a_first_page(cfg, services) -> None:
    profile = cfg.create_profile(ProfileInput(name="  Editing   suite "))
    assert profile.name == "Editing suite"
    assert [p.name for p in services.pages.list_pages(profile.id)] == ["Main"]
    assert [p.name for p in services.profiles.list()][-1] == "Editing suite"


def test_profile_rename_reorder_delete(cfg, services) -> None:
    a = cfg.create_profile(ProfileInput(name="Gaming"))
    b = cfg.create_profile(ProfileInput(name="Work"))
    cfg.update_profile(a.id, ProfileInput(name="Games", description="Evenings"))
    first = services.profiles.list()[0].id
    cfg.reorder_profiles([b.id, a.id, first])
    assert [p.name for p in services.profiles.list()] == ["Work", "Games", "Main"]
    cfg.delete_profile(b.id)
    assert [p.sort_order for p in services.profiles.list()] == [0, 1]


def test_cannot_delete_last_profile(cfg, services) -> None:
    only = services.profiles.list()[0]
    with pytest.raises(ConfigError) as exc:
        cfg.delete_profile(only.id)
    assert exc.value.code == "LAST_PROFILE"


def test_deleting_active_profile_falls_back(cfg, services) -> None:
    extra = cfg.create_profile(ProfileInput(name="Extra"))
    cfg.set_active_profile(extra.id)
    cfg.delete_profile(extra.id)
    assert cfg.active_profile_id() == services.profiles.list()[0].id


def _drop_monitor_pages(services) -> None:
    """These tests are about deck pages; set aside the seeded System Monitoring page."""
    for page in services.pages.list_all():
        if page.kind == "monitor":
            services.pages.delete(page.id)


def test_duplicate_profile_deep_copies(cfg, services) -> None:
    _drop_monitor_pages(services)
    source = services.profiles.list()[0]
    page = services.pages.list_pages(source.id)[0]
    cfg.create_button(page.id, _url_button("YouTube", "youtube.com"))
    copy = cfg.duplicate_profile(source.id)
    assert copy.name == "Main copy"
    copy_pages = services.pages.list_pages(copy.id)
    assert [p.name for p in copy_pages] == ["Home"]
    assert _page_buttons(services, copy_pages[0].id) == ["Lock PC", "YouTube"]
    # Copies are independent.
    cfg.delete_button(services.buttons.list_for_page(copy_pages[0].id)[0].id)
    assert _page_buttons(services, page.id) == ["Lock PC", "YouTube"]


def test_page_crud_reorder_and_duplicate(cfg, services) -> None:
    _drop_monitor_pages(services)
    profile = services.profiles.list()[0]
    home = services.pages.list_pages(profile.id)[0]
    editing = cfg.create_page(profile.id, PageInput(name="Editing"))
    cfg.update_page(editing.id, PageInput(name="Premiere"))
    dup = cfg.duplicate_page(home.id)
    assert [p.name for p in services.pages.list_pages(profile.id)] == ["Home", "Home copy", "Premiere"]
    cfg.reorder_pages(profile.id, [editing.id, home.id, dup.id])
    assert [p.name for p in services.pages.list_pages(profile.id)] == ["Premiere", "Home", "Home copy"]
    cfg.delete_page(dup.id)
    assert [p.sort_order for p in services.pages.list_pages(profile.id)] == [0, 1]


def test_cannot_delete_last_page(cfg, services) -> None:
    _drop_monitor_pages(services)
    profile = services.profiles.list()[0]
    with pytest.raises(ConfigError) as exc:
        cfg.delete_page(services.pages.list_pages(profile.id)[0].id)
    assert exc.value.code == "LAST_PAGE"


def test_button_create_edit_reorder_duplicate_move_delete(cfg, services) -> None:
    profile = services.profiles.list()[0]
    home = services.pages.list_pages(profile.id)[0]
    other = cfg.create_page(profile.id, PageInput(name="Other"))
    chrome = cfg.create_button(home.id, ButtonInput(
        label="Chrome", action_type="launch_application",
        action_config={"path": "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe"}))
    youtube = cfg.create_button(home.id, _url_button("YouTube", "youtube.com"))
    assert youtube.action_config == {"url": "https://youtube.com"}
    assert _page_buttons(services, home.id) == ["Lock PC", "Chrome", "YouTube"]

    cfg.update_button(chrome.id, ButtonInput(label="Browser", action_type="launch_application",
                                             action_config={"path": "C:\\b.exe", "arguments": "--x"}))
    ids = [b.id for b in services.buttons.list_for_page(home.id)]
    cfg.reorder_buttons(home.id, [ids[2], ids[0], ids[1]])
    assert _page_buttons(services, home.id) == ["YouTube", "Lock PC", "Browser"]

    dup = cfg.duplicate_button(youtube.id)
    assert dup.sort_order == 1
    assert _page_buttons(services, home.id) == ["YouTube", "YouTube copy", "Lock PC", "Browser"]

    cfg.move_button(chrome.id, other.id)
    assert _page_buttons(services, home.id) == ["YouTube", "YouTube copy", "Lock PC"]
    assert _page_buttons(services, other.id) == ["Browser"]

    cfg.delete_button(dup.id)
    assert [b.sort_order for b in services.buttons.list_for_page(home.id)] == [0, 1]


@pytest.mark.parametrize("action_type, config, field", [
    ("open_url", {"url": "javascript:alert(1)"}, "url"),
    ("open_url", {"url": "file:///C:/Windows"}, "url"),
    ("launch_application", {"path": "chrome.exe"}, "path"),
    ("launch_application", {"path": "C:\\notes.txt"}, "path"),
    ("open_folder", {"path": ""}, "path"),
    ("open_file", {"path": "C:\\a.txt", "command": "del"}, "command"),
])
def test_invalid_action_config_is_rejected_with_field_errors(cfg, services, action_type, config,
                                                             field) -> None:
    page = services.pages.list_all()[0]
    with pytest.raises(ConfigError) as exc:
        cfg.create_button(page.id, ButtonInput(label="x", action_type=action_type,
                                               action_config=config))
    assert exc.value.code == "INVALID_CONFIG"
    assert field in exc.value.fields


def test_unknown_action_and_bad_icon_rejected(cfg, services) -> None:
    page = services.pages.list_all()[0]
    with pytest.raises(ConfigError) as exc:
        cfg.create_button(page.id, ButtonInput(label="x", action_type="run_shell"))
    assert exc.value.code == "UNKNOWN_ACTION"
    with pytest.raises(ConfigError) as exc:
        cfg.create_button(page.id, ButtonInput(label="x", action_type="lock_windows",
                                               icon_ref="asset:" + "0" * 64 + ".png"))
    assert exc.value.code == "INVALID_ICON"
    with pytest.raises(ConfigError):
        cfg.create_button(page.id, ButtonInput(label="x", action_type="lock_windows",
                                               icon_ref="../../etc/passwd"))


def test_stale_reorder_rejected(cfg, services) -> None:
    page = services.pages.list_all()[0]
    with pytest.raises(ConfigError) as exc:
        cfg.reorder_buttons(page.id, ["not-a-button"])
    assert exc.value.code == "STALE_ORDER"


def test_changes_notify_listeners(cfg, services) -> None:
    calls = []
    cfg.subscribe(lambda: calls.append(1))
    cfg.create_profile(ProfileInput(name="X"))
    assert calls == [1]


def test_configuration_survives_restart(tmp_path, lock_action) -> None:
    from opendeck.app import build_services
    from opendeck.config import AppConfig

    first = build_services(AppConfig(data_dir=tmp_path, port=0))
    profile = first.deck_config.create_profile(ProfileInput(name="Streaming"))
    page = first.pages.list_pages(profile.id)[0]
    first.deck_config.create_button(page.id, _url_button("Twitch", "twitch.tv"))
    first.db.close()

    second = build_services(AppConfig(data_dir=tmp_path, port=0))
    names = [p.name for p in second.profiles.list()]
    assert names == ["Main", "Streaming"]
    restored = second.buttons.list_for_page(page.id)
    assert [(b.label, b.action_config) for b in restored] == [("Twitch", {"url": "https://twitch.tv"})]
    second.db.close()
