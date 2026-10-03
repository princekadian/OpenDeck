"""Advanced actions: PowerShell, commands, HTTP requests, WebSocket messages.

Security model: the script, command line, URL and body are written in the PC
editor (loopback only) and stored on the PC. A device only ever sends the
button id; nothing it sends is executed.
"""

from __future__ import annotations

import asyncio
import base64
import os
import subprocess
import urllib.error
import urllib.request
from typing import Annotated, Literal

from pydantic import AfterValidator, Field, field_validator

from ..base import Action, ActionConfig, ActionContext, ActionError, ActionOutcome
from ._common import CODE, FOLDER, MULTILINE, unit, windows_path
from .launch import web_url

CREATE_NO_WINDOW = 0x08000000
MAX_OUTPUT = 4000


def _optional_folder(value: str) -> str:
    return windows_path(value) if value.strip() else ""


OptionalFolder = Annotated[str, AfterValidator(_optional_folder)]


class _ProcessConfig(ActionConfig):
    wait: bool = Field(default=True, title="Wait for it to finish",
                       description="Reports failure when it exits with an error code.")
    timeout_seconds: int = Field(default=30, ge=1, le=600, title="Time limit", json_schema_extra=unit("s"))
    working_directory: OptionalFolder = Field(default="", title="Start in", max_length=1024,
                                              json_schema_extra=FOLDER)


class PowerShellConfig(_ProcessConfig):
    script: str = Field(title="Script", min_length=1, max_length=20_000, json_schema_extra=CODE)


class CommandConfig(_ProcessConfig):
    command: str = Field(title="Command line", min_length=1, max_length=8_000, json_schema_extra=CODE,
                         description="Runs with cmd.exe, without showing a window.")


async def _run_process(args: list[str], config: _ProcessConfig, encoding: str) -> ActionOutcome:
    """Runs in a worker thread: independent of which asyncio loop type the server uses."""
    cwd = config.working_directory or None
    if cwd and not os.path.isdir(cwd):
        raise ActionError("FOLDER_NOT_FOUND", "The 'Start in' folder no longer exists.")
    common = {"cwd": cwd, "stdin": subprocess.DEVNULL, "creationflags": CREATE_NO_WINDOW}
    try:
        if not config.wait:
            await asyncio.to_thread(subprocess.Popen, args, stdout=subprocess.DEVNULL,
                                    stderr=subprocess.DEVNULL, **common)
            return ActionOutcome(message="Started")
        result = await asyncio.to_thread(subprocess.run, args, capture_output=True,
                                         timeout=config.timeout_seconds, **common)
    except subprocess.TimeoutExpired as exc:
        raise ActionError("TIMEOUT", f"Still running after {config.timeout_seconds} s, so it was stopped.") from exc
    except OSError as exc:
        raise ActionError("LAUNCH_FAILED", f"Could not start: {exc.strerror or exc}.") from exc
    output = result.stdout.decode(encoding, errors="replace")[-MAX_OUTPUT:]
    if result.returncode != 0:
        detail = result.stderr.decode(encoding, errors="replace").strip().splitlines()
        hint = f": {detail[-1][:200]}" if detail else ""
        raise ActionError("EXIT_CODE", f"Exited with code {result.returncode}{hint}")
    return ActionOutcome(message="Done", data={"output": output})


class RunPowerShellAction(Action[PowerShellConfig]):
    type = "run_powershell"
    display_name = "Run PowerShell"
    description = "Run a PowerShell script you write here, hidden, on the PC."
    category = "advanced"
    icon = "terminal"
    config_model = PowerShellConfig
    trusted_only = True

    async def execute(self, config: PowerShellConfig, ctx: ActionContext) -> ActionOutcome:
        # -EncodedCommand avoids every quoting problem: the script is passed verbatim.
        # Output is forced to UTF-8 so non-English text survives.
        script = "[Console]::OutputEncoding = [Text.Encoding]::UTF8\n" + config.script
        encoded = base64.b64encode(script.encode("utf-16-le")).decode()
        return await _run_process(["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy",
                                   "Bypass", "-EncodedCommand", encoded], config, "utf-8")


class RunCommandAction(Action[CommandConfig]):
    type = "run_command"
    display_name = "Run command"
    description = "Run a command line you write here, hidden, on the PC."
    category = "advanced"
    icon = "terminal"
    config_model = CommandConfig
    trusted_only = True

    async def execute(self, config: CommandConfig, ctx: ActionContext) -> ActionOutcome:
        comspec = os.environ.get("COMSPEC", "cmd.exe")
        # cmd.exe writes in the console (OEM) code page.
        return await _run_process([comspec, "/d", "/s", "/c", config.command], config, "oem")


HttpUrl = Annotated[str, AfterValidator(web_url)]


class HttpConfig(ActionConfig):
    method: Literal["GET", "POST", "PUT", "PATCH", "DELETE"] = Field(default="GET", title="Method")
    url: HttpUrl = Field(title="URL", max_length=2048, json_schema_extra={"widget": "url"})
    headers: str = Field(default="", max_length=4000, title="Headers", json_schema_extra=MULTILINE,
                         description="One per line, for example  Authorization: Bearer abc")
    body: str = Field(default="", max_length=20_000, title="Body", json_schema_extra=MULTILINE,
                      description="Sent with POST, PUT and PATCH.")
    timeout_seconds: int = Field(default=10, ge=1, le=60, title="Time limit", json_schema_extra=unit("s"))

    @field_validator("headers")
    @classmethod
    def _headers(cls, value: str) -> str:
        for line in filter(None, (l.strip() for l in value.splitlines())):
            name, sep, _ = line.partition(":")
            if not sep or not name.strip() or any(c in name for c in " \t"):
                raise ValueError(f"'{line[:40]}' is not a header. Use  Name: value")
        return value

    def header_dict(self) -> dict[str, str]:
        pairs = (line.split(":", 1) for line in self.headers.splitlines() if ":" in line)
        return {k.strip(): v.strip() for k, v in pairs}


class _NoRedirectToOtherSchemes(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not newurl.lower().startswith(("http://", "https://")):
            raise urllib.error.HTTPError(newurl, code, "Redirect to a non-web address blocked", headers, fp)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class HttpRequestAction(Action[HttpConfig]):
    type = "http_request"
    display_name = "Send HTTP request"
    description = "Call a web API or webhook (Home Assistant, IFTTT, your own server…)."
    category = "advanced"
    icon = "http"
    config_model = HttpConfig

    async def execute(self, config: HttpConfig, ctx: ActionContext) -> ActionOutcome:
        def send() -> int:
            data = config.body.encode() if config.method in ("POST", "PUT", "PATCH") and config.body else None
            request = urllib.request.Request(config.url, data=data, method=config.method,
                                             headers={"User-Agent": "OpenDeck", **config.header_dict()})
            opener = urllib.request.build_opener(_NoRedirectToOtherSchemes())
            with opener.open(request, timeout=config.timeout_seconds) as response:
                response.read(65536)  # drain a bounded amount; the body is not needed
                return response.status

        try:
            status = await asyncio.to_thread(send)
        except urllib.error.HTTPError as exc:
            raise ActionError("HTTP_ERROR", f"The server answered {exc.code} {exc.reason}.") from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            reason = getattr(exc, "reason", exc)
            raise ActionError("HTTP_FAILED", f"Request failed: {reason}.") from exc
        return ActionOutcome(message=f"HTTP {status}", data={"status": status})


WsUrl = Annotated[str, AfterValidator(lambda v: web_url(v, ("ws", "wss")))]


class WebSocketConfig(ActionConfig):
    url: WsUrl = Field(title="WebSocket URL", max_length=2048, json_schema_extra={"widget": "url"},
                       description="ws:// or wss:// address.")
    message: str = Field(title="Message", min_length=1, max_length=20_000, json_schema_extra=MULTILINE,
                         description="Sent as text once the connection opens. JSON works too.")
    wait_for_reply: bool = Field(default=False, title="Wait for one reply")
    timeout_seconds: int = Field(default=5, ge=1, le=60, title="Time limit", json_schema_extra=unit("s"))


class WebSocketAction(Action[WebSocketConfig]):
    """Generic building block; integrations such as OBS get their own actions."""

    type = "websocket_message"
    display_name = "WebSocket action"
    description = "Connect to a WebSocket server and send a message."
    category = "advanced"
    icon = "plug"
    config_model = WebSocketConfig

    async def execute(self, config: WebSocketConfig, ctx: ActionContext) -> ActionOutcome:
        from websockets.asyncio.client import connect
        from websockets.exceptions import WebSocketException

        try:
            async with asyncio.timeout(config.timeout_seconds):
                async with connect(config.url, max_size=1_000_000, open_timeout=config.timeout_seconds) as ws:
                    await ws.send(config.message)
                    reply = await ws.recv() if config.wait_for_reply else None
        except TimeoutError as exc:
            raise ActionError("TIMEOUT", "The WebSocket server did not respond in time.") from exc
        except (OSError, WebSocketException) as exc:
            raise ActionError("WEBSOCKET_FAILED", f"WebSocket error: {exc}.") from exc
        data = {"reply": reply[:MAX_OUTPUT] if isinstance(reply, str) else None} if reply is not None else {}
        return ActionOutcome(message="Sent", data=data)
