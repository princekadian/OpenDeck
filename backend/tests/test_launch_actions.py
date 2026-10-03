"""Open/launch actions with the Windows shell call replaced by a recorder."""

from __future__ import annotations

import asyncio

import pytest

from opendeck.actions import ActionContext, ActionError
from opendeck.actions.builtin import launch
from opendeck.native.windows import shell

CTX = ActionContext(button_id="b", device_id="d")


@pytest.fixture
def opened(monkeypatch):
    calls: list[tuple] = []
    monkeypatch.setattr(shell, "shell_open",
                        lambda target, **kw: calls.append((target, kw)))
    return calls


def run(action, raw):
    return asyncio.run(action.execute(action.parse_config(raw), CTX))


def test_launch_application_uses_app_folder_and_arguments(tmp_path, opened) -> None:
    exe = tmp_path / "App.exe"
    exe.write_bytes(b"MZ")
    run(launch.LaunchApplicationAction(), {"path": str(exe), "arguments": "--new-window"})
    assert opened == [(str(exe), {"parameters": "--new-window", "directory": str(tmp_path)})]


def test_launch_missing_application(tmp_path, opened) -> None:
    with pytest.raises(ActionError) as exc:
        run(launch.LaunchApplicationAction(), {"path": str(tmp_path / "Gone.exe")})
    assert exc.value.code == "FILE_NOT_FOUND"
    assert opened == []


def test_open_url_normalises_scheme(opened) -> None:
    run(launch.OpenUrlAction(), {"url": "youtube.com"})
    assert opened[0][0] == "https://youtube.com"


def test_open_file_and_folder(tmp_path, opened) -> None:
    doc = tmp_path / "Project.xlsx"
    doc.write_bytes(b"x")
    run(launch.OpenFileAction(), {"path": str(doc)})
    run(launch.OpenFolderAction(), {"path": str(tmp_path)})
    assert [c[0] for c in opened] == [str(doc), str(tmp_path)]


def test_deleted_file_and_folder_report_clear_errors(tmp_path, opened) -> None:
    with pytest.raises(ActionError) as exc:
        run(launch.OpenFileAction(), {"path": str(tmp_path / "missing.txt")})
    assert exc.value.code == "FILE_NOT_FOUND"
    with pytest.raises(ActionError) as exc:
        run(launch.OpenFolderAction(), {"path": str(tmp_path / "missing")})
    assert exc.value.code == "FOLDER_NOT_FOUND"


def test_shell_failure_becomes_structured_error(tmp_path, monkeypatch) -> None:
    def deny(target, **kw):
        raise shell.ShellError("PERMISSION_DENIED", "Windows denied access.")

    monkeypatch.setattr(shell, "shell_open", deny)
    with pytest.raises(ActionError) as exc:
        run(launch.OpenFolderAction(), {"path": str(tmp_path)})
    assert (exc.value.code, exc.value.message) == ("PERMISSION_DENIED", "Windows denied access.")


def test_schemas_carry_editor_widgets() -> None:
    schema = launch.LaunchApplicationAction().describe()["configSchema"]
    assert schema["properties"]["path"]["widget"] == "exe"
    assert schema["required"] == ["path"]
