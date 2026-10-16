"""Sound effects: settings validation, press behaviour, and real decoding on Windows."""

from __future__ import annotations

import asyncio
import wave
from pathlib import Path

import pytest
from pydantic import ValidationError

from opendeck.actions import ActionContext, ActionError
from opendeck.actions.builtin import soundboard
from opendeck.native.windows import sound


class FakePlayback:
    """Plays nothing; stays 'playing' until stopped."""

    started: list["FakePlayback"] = []

    def __init__(self, pcm, device=None) -> None:
        self.device, self.done = device, False
        FakePlayback.started.append(self)

    def stop(self) -> None:
        self.done = True

    def wait(self) -> None:
        while not self.done:
            import time
            time.sleep(0.005)


@pytest.fixture
def fake_audio(monkeypatch, tmp_path: Path) -> Path:
    FakePlayback.started = []
    monkeypatch.setattr(soundboard, "player", soundboard.SoundPlayer())
    monkeypatch.setattr(sound, "Playback", FakePlayback)
    monkeypatch.setattr(sound, "decode", lambda path: sound.Pcm(b"\x00\x10" * 4800, 1, 48000))
    path = tmp_path / "airhorn.mp3"
    path.write_bytes(b"not decoded in these tests")
    return path


def run(config: dict, button: str = "b1"):
    action = soundboard.PlaySoundAction()
    ctx = ActionContext(button_id=button, device_id=None)
    return asyncio.run(action.execute(action.parse_config(config), ctx))


def test_settings_accept_audio_files_only() -> None:
    action = soundboard.PlaySoundAction()
    config = action.parse_config({"path": '"C:\\Sounds\\Horn.OGG"'})
    assert config.path == "C:\\Sounds\\Horn.OGG" and config.volume == 100 and config.when_playing == "stop"
    for bad in ("C:\\Sounds\\notes.txt", "Horn.mp3", ""):
        with pytest.raises(ValidationError):
            action.parse_config({"path": bad})
    with pytest.raises(ValidationError):
        action.parse_config({"path": "C:\\a.mp3", "volume": 101})


def test_press_plays_on_each_chosen_device_once(fake_audio: Path) -> None:
    outcome = run({"path": str(fake_audio), "deviceId": "speakers", "alsoDeviceId": "cable"})
    assert outcome.message == "Playing"
    assert [p.device for p in FakePlayback.started] == ["speakers", "cable"]
    FakePlayback.started = []
    run({"path": str(fake_audio), "deviceId": "same", "alsoDeviceId": "same", "whenPlaying": "overlap"}, "b2")
    assert [p.device for p in FakePlayback.started] == ["same"]  # not doubled on one device


@pytest.mark.parametrize(("mode", "message", "playing_after"), [
    ("stop", "Stopped", 0), ("restart", "Playing", 1), ("overlap", "Playing", 2)])
def test_second_press_while_playing(fake_audio: Path, mode: str, message: str, playing_after: int) -> None:
    config = {"path": str(fake_audio), "whenPlaying": mode}
    run(config)
    assert run(config).message == message
    assert sum(not p.done for p in FakePlayback.started) == playing_after


def test_stop_all_and_missing_file(fake_audio: Path) -> None:
    run({"path": str(fake_audio), "whenPlaying": "overlap"}, "a")
    run({"path": str(fake_audio)}, "b")
    stop = soundboard.StopSoundsAction()
    ctx = ActionContext(button_id="s", device_id=None)
    assert asyncio.run(stop.execute(stop.config_model(), ctx)).message == "Stopped"
    assert all(p.done for p in FakePlayback.started)
    assert asyncio.run(stop.execute(stop.config_model(), ctx)).message == "Nothing playing"
    with pytest.raises(ActionError) as exc:
        run({"path": str(fake_audio.with_name("gone.mp3"))})
    assert exc.value.code == "FILE_NOT_FOUND"


def test_ogg_without_vorbis_or_opus_is_refused() -> None:
    with pytest.raises(sound.SoundError):
        sound.ogg_to_webm(b"OggS" + bytes(23))


def _has_media_foundation() -> bool:
    try:
        import ctypes
        ctypes.WinDLL("mfplat")
        return True
    except (OSError, AttributeError):  # not Windows, or a Windows Server without Media Foundation
        return False


@pytest.mark.skipif(not _has_media_foundation(), reason="needs Windows Media Foundation")
def test_real_wav_decodes_and_scales(tmp_path: Path) -> None:
    path = tmp_path / "beep.wav"
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(22050)
        w.writeframes((1000).to_bytes(2, "little", signed=True) * 22050)
    pcm = sound.decode(str(path))
    assert (pcm.channels, pcm.rate, round(pcm.seconds, 2)) == (1, 22050, 1.0)
    assert sound.scaled(pcm, 50).data[:2] == (500).to_bytes(2, "little", signed=True)
