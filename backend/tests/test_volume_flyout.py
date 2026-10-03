"""Volume changes on the default speakers show the Windows volume pop-up.

Windows only shows its pop-up for volume keys it handles itself, so the service taps
the matching key first, waits for Windows to apply it, then sets the exact level.
These tests replace the native layer with a fake "shell" that reacts to the keys.
"""

from __future__ import annotations

import asyncio

import pytest

from opendeck.native.windows import audio as native_audio
from opendeck.native.windows import keyboard
from opendeck.services.audio import AudioService


class FakeShell:
    """Default speakers plus the Windows shell's 2% volume-key steps."""

    def __init__(self, volume: float = 0.5, muted: bool = False) -> None:
        self.volume = volume
        self.muted = muted
        self.keys: list[str] = []

    def get_level(self, flow, device_id=None):
        return self.volume, self.muted

    def set_level(self, flow, level, device_id=None):
        self.volume = level
        if level > 0:
            self.muted = False
        return level

    def set_mute(self, flow, muted, device_id=None):
        self.muted = muted

    def tap(self, key: str) -> None:
        self.keys.append(key)
        if key == "VOLUME_UP":
            self.volume, self.muted = min(1.0, self.volume + 0.02), False
        elif key == "VOLUME_DOWN":
            self.volume, self.muted = max(0.0, self.volume - 0.02), False
        elif key == "VOLUME_MUTE":
            self.muted = not self.muted


@pytest.fixture
def shell(monkeypatch):
    fake = FakeShell()
    monkeypatch.setattr(native_audio, "get_level", fake.get_level)
    monkeypatch.setattr(native_audio, "set_level", fake.set_level)
    monkeypatch.setattr(native_audio, "set_mute", fake.set_mute)
    monkeypatch.setattr(keyboard, "tap_key", fake.tap)
    return fake


def run(coro):
    service = AudioService()
    try:
        return asyncio.run(coro(service))
    finally:
        service.close()


def test_volume_up_taps_the_key_and_lands_on_the_exact_level(shell) -> None:
    level = run(lambda s: s.change_volume("output", 10))
    assert shell.keys == ["VOLUME_UP"]
    assert level.volume == 60 and round(shell.volume * 100) == 60


def test_volume_down_taps_the_down_key(shell) -> None:
    level = run(lambda s: s.change_volume("output", -5))
    assert shell.keys == ["VOLUME_DOWN"] and level.volume == 45


def test_at_the_limit_still_shows_the_pop_up_without_waiting(shell) -> None:
    shell.volume = 1.0
    level = run(lambda s: s.change_volume("output", 10))
    assert shell.keys == ["VOLUME_UP"] and level.volume == 100


def test_set_volume_moves_toward_the_target(shell) -> None:
    level = run(lambda s: s.set_volume("output", 20))
    assert shell.keys == ["VOLUME_DOWN"] and level.volume == 20


def test_mute_toggle_uses_the_mute_key(shell) -> None:
    level = run(lambda s: s.set_mute("output", None))
    assert shell.keys == ["VOLUME_MUTE"] and level.muted is True
    level = run(lambda s: s.set_mute("output", None))
    assert shell.keys == ["VOLUME_MUTE", "VOLUME_MUTE"] and level.muted is False


def test_chosen_device_and_microphone_never_tap_keys(shell) -> None:
    run(lambda s: s.change_volume("output", 10, "{some-device}"))
    run(lambda s: s.change_volume("input", 10))
    run(lambda s: s.set_mute("input", None))
    assert shell.keys == []
