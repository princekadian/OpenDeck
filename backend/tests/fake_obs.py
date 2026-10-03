"""A small obs-websocket v5 server for tests: real handshake (with challenge auth),
requests, responses and events, plus enough OBS state to exercise every action."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
from typing import Any

from websockets.asyncio.server import serve


class FakeObs:
    def __init__(self, password: str = "secret") -> None:
        self.password = password
        self.salt, self.challenge = "c2FsdA==", "Y2hhbGxlbmdl"
        self.streaming = False
        self.recording = False
        self.paused = False
        self.scene = "Gameplay"
        self.scenes = ["Starting", "Gameplay", "BRB"]
        self.items = {("Gameplay", "Webcam"): (7, True), ("Gameplay", "Overlay"): (8, True), ("BRB", "Webcam"): (3, False)}
        self.inputs = [("Mic/Aux", "wasapi_input_capture"), ("Desktop Audio", "wasapi_output_capture"),
                       ("Webcam", "dshow_input"), ("Overlay", "browser_source")]
        self.muted = {"Mic/Aux": False, "Desktop Audio": False}
        self.requests: list[str] = []
        self.clients: set = set()
        self._server = None
        self.port = 0

    async def start(self) -> "FakeObs":
        self._server = await serve(self._handle, "127.0.0.1", self.port)
        self.port = self._server.sockets[0].getsockname()[1]
        return self

    async def stop(self) -> None:
        self._server.close()
        for ws in list(self.clients):
            await ws.close()
        await self._server.wait_closed()

    def _expected_auth(self) -> str:
        secret = base64.b64encode(hashlib.sha256((self.password + self.salt).encode()).digest()).decode()
        return base64.b64encode(hashlib.sha256((secret + self.challenge).encode()).digest()).decode()

    async def _handle(self, ws) -> None:
        hello: dict[str, Any] = {"obsWebSocketVersion": "5.5.0", "rpcVersion": 1}
        if self.password:
            hello["authentication"] = {"challenge": self.challenge, "salt": self.salt}
        await ws.send(json.dumps({"op": 0, "d": hello}))
        identify = json.loads(await ws.recv())
        if self.password and identify["d"].get("authentication") != self._expected_auth():
            await ws.close(4009, "Authentication failed.")
            return
        await ws.send(json.dumps({"op": 2, "d": {"negotiatedRpcVersion": 1}}))
        self.clients.add(ws)
        try:
            async for raw in ws:
                message = json.loads(raw)
                if message["op"] == 6:
                    await self._request(ws, message["d"])
        finally:
            self.clients.discard(ws)

    async def emit(self, event: str, data: dict[str, Any]) -> None:
        for ws in list(self.clients):
            await ws.send(json.dumps({"op": 5, "d": {"eventType": event, "eventIntent": 1, "eventData": data}}))

    async def _request(self, ws, d: dict[str, Any]) -> None:
        kind, data = d["requestType"], d.get("requestData", {})
        self.requests.append(kind)
        ok, code, response = True, 100, {}
        events: list[tuple[str, dict]] = []
        if kind == "GetVersion":
            response = {"obsVersion": "32.1.2", "obsWebSocketVersion": "5.5.0"}
        elif kind == "GetStreamStatus":
            response = {"outputActive": self.streaming}
        elif kind == "GetRecordStatus":
            response = {"outputActive": self.recording, "outputPaused": self.paused}
        elif kind == "GetCurrentProgramScene":
            response = {"sceneName": self.scene, "currentProgramSceneName": self.scene}
        elif kind == "StartStream":
            if self.streaming:
                ok, code = False, 500
            else:
                self.streaming = True
                events.append(("StreamStateChanged", {"outputActive": True, "outputState": "OBS_WEBSOCKET_OUTPUT_STARTED"}))
        elif kind == "StopStream":
            if not self.streaming:
                ok, code = False, 501
            else:
                self.streaming = False
                events.append(("StreamStateChanged", {"outputActive": False, "outputState": "OBS_WEBSOCKET_OUTPUT_STOPPED"}))
        elif kind == "StartRecord":
            self.recording = True
            events.append(("RecordStateChanged", {"outputActive": True, "outputState": "OBS_WEBSOCKET_OUTPUT_STARTED"}))
        elif kind == "StopRecord":
            self.recording, self.paused = False, False
            response = {"outputPath": "C:\\Videos\\rec.mkv"}
            events.append(("RecordStateChanged", {"outputActive": False, "outputState": "OBS_WEBSOCKET_OUTPUT_STOPPED"}))
        elif kind == "ToggleRecordPause":
            self.paused = not self.paused
            state = "OBS_WEBSOCKET_OUTPUT_PAUSED" if self.paused else "OBS_WEBSOCKET_OUTPUT_RESUMED"
            events.append(("RecordStateChanged", {"outputActive": True, "outputState": state}))
        elif kind == "GetSceneList":
            response = {"scenes": [{"sceneName": n} for n in reversed(self.scenes)]}
        elif kind == "SetCurrentProgramScene":
            if data["sceneName"] not in self.scenes:
                ok, code = False, 600
            else:
                self.scene = data["sceneName"]
                events.append(("CurrentProgramSceneChanged", {"sceneName": self.scene}))
        elif kind == "GetSceneItemId":
            item = self.items.get((data["sceneName"], data["sourceName"]))
            ok, code, response = (True, 100, {"sceneItemId": item[0]}) if item else (False, 600, {})
        elif kind in ("GetSceneItemEnabled", "SetSceneItemEnabled"):
            key = next(k for k, v in self.items.items() if k[0] == data["sceneName"] and v[0] == data["sceneItemId"])
            if kind == "SetSceneItemEnabled":
                self.items[key] = (self.items[key][0], data["sceneItemEnabled"])
                events.append(("SceneItemEnableStateChanged", {"sceneName": key[0], "sceneItemId": self.items[key][0],
                                                                "sceneItemEnabled": data["sceneItemEnabled"]}))
            response = {"sceneItemEnabled": self.items[key][1]}
        elif kind == "GetSceneItemList":
            response = {"sceneItems": [{"sourceName": s, "sceneItemId": v[0]} for (sc, s), v in self.items.items()
                                       if sc == data["sceneName"]]}
        elif kind == "GetInputList":
            response = {"inputs": [{"inputName": n, "inputKind": k} for n, k in self.inputs]}
        elif kind == "GetInputMute":
            response = {"inputMuted": self.muted[data["inputName"]]}
        elif kind == "ToggleInputMute":
            name = data["inputName"]
            if name not in self.muted:
                ok, code = False, 600
            else:
                self.muted[name] = not self.muted[name]
                response = {"inputMuted": self.muted[name]}
                events.append(("InputMuteStateChanged", {"inputName": name, "inputMuted": self.muted[name]}))
        else:
            ok, code = False, 204
        await ws.send(json.dumps({"op": 7, "d": {
            "requestType": kind, "requestId": d["requestId"],
            "requestStatus": {"result": ok, "code": code, **({} if ok else {"comment": "fake failure"})},
            **({"responseData": response} if response else {})}}))
        for event, payload in events:
            await self.emit(event, payload)
