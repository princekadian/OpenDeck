"""Built-in actions, in menu order within each category."""

from __future__ import annotations

from ..base import Action


def all_builtin_actions() -> list[Action]:
    from . import (advanced, audio, display, keys, launch, navigation, soundboard, streaming, system, windows,
                   workflow)

    return [
        # Open
        launch.LaunchApplicationAction(), launch.OpenUrlAction(), launch.OpenFileAction(),
        launch.OpenFolderAction(),
        # System
        system.LockWindowsAction(), system.ShutdownAction(), system.RestartAction(), system.SleepAction(),
        system.HibernateAction(), system.SignOutAction(), system.TaskManagerAction(),
        system.OpenSettingsAction(),
        # Audio
        audio.VolumeUpAction(), audio.VolumeDownAction(), audio.SetVolumeAction(), audio.MuteToggleAction(),
        audio.MicUpAction(), audio.MicDownAction(), audio.MicMuteAction(), audio.OutputDeviceAction(),
        audio.InputDeviceAction(),
        # Media
        keys.PlayPauseAction(), keys.PreviousTrackAction(), keys.NextTrackAction(), keys.StopMediaAction(),
        audio.MediaVolumeUpAction(), audio.MediaVolumeDownAction(),
        # Sound effects
        soundboard.PlaySoundAction(), soundboard.StopSoundsAction(),
        # Keyboard
        keys.HotkeyAction(), keys.TypeTextAction(), keys.KeyPressAction(), keys.KeyComboAction(),
        # Display
        display.BrightnessUpAction(), display.BrightnessDownAction(), display.SetBrightnessAction(),
        display.ChangeDisplayAction(), display.ToggleHdrAction(),
        # Window
        windows.MinimizeAction(), windows.MaximizeAction(), windows.CloseWindowAction(),
        windows.RestoreWindowAction(), windows.SwitchApplicationAction(), windows.MoveWindowAction(),
        windows.ResizeWindowAction(),
        # Applications
        launch.AppLaunchAction(), windows.CloseApplicationAction(), windows.RestartApplicationAction(),
        windows.FocusApplicationAction(), windows.AppRunningAction(),
        # Navigation
        navigation.GoToPageAction(), navigation.GoToProfileAction(), navigation.GoBackAction(),
        launch.NavOpenFolderAction(), launch.NavOpenUrlAction(),
        # Workflow
        workflow.MultiAction(), workflow.DelayAction(), workflow.ToggleAction(), workflow.CounterAction(),
        workflow.TimerAction(),
        # Streaming (coming soon)
        streaming.ObsStartStreaming(), streaming.ObsStopStreaming(), streaming.ObsStartRecording(),
        streaming.ObsStopRecording(), streaming.ObsPauseRecording(), streaming.ObsChangeScene(),
        streaming.ObsToggleSource(), streaming.ObsToggleMicrophone(), streaming.ObsToggleCamera(),
        # Advanced
        advanced.RunPowerShellAction(), advanced.RunCommandAction(), advanced.HttpRequestAction(),
        advanced.WebSocketAction(),
    ]
