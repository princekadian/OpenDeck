# WebSocket protocol (v2)

Endpoint: `ws://<pc>:<port>/ws`. Frames are UTF-8 JSON text, max 64 KiB.
Source of truth: `backend/opendeck/protocol.py`; TypeScript mirror: `frontend/src/protocol/messages.ts`.

## Envelope

```json
{
  "version": 2,
  "type": "ACTION_EXECUTE",
  "requestId": "4b1c…",
  "success": true,
  "error": { "code": "platform_error", "message": "…" },
  "payload": {}
}
```

| Field | Required | Notes |
|---|---|---|
| `version` | yes | Protocol major version. Server rejects other versions with close code 4002. |
| `type` | yes | Message type (below). |
| `requestId` | for requests | Client-generated (≤ 64 chars); echoed in the reply. |
| `success` | replies only | `true`/`false` on `ACTION_RESULT` and `ERROR`. |
| `error` | on failure | `{code, message}`; `message` is safe to show to the user. |
| `payload` | yes | Type-specific object (may be `{}`). |

Unknown fields are ignored, so new optional fields can be added without a version bump.
Removing or changing the meaning of a field requires `version: 2`.

## Connection lifecycle

1. Client connects to `/ws`.
2. Client sends `HELLO` within 5 s, otherwise the server closes with 4001.
3. Server validates the device token. Invalid or revoked: `ERROR{auth_failed}` + close 4003.
4. Server sends `WELCOME`, then a full `SNAPSHOT`.
5. Normal operation. Client sends `PING` every 10 s; a link with no inbound traffic for 25 s is
   treated as dead and reconnected.
6. After any reconnect the server sends a fresh `SNAPSHOT`, so clients never need to replay missed events.

## Client → server

| Type | Payload | Reply |
|---|---|---|
| `HELLO` | `{token: string, clientVersion?: string}` | `WELCOME` + `SNAPSHOT`, or close |
| `ACTION_EXECUTE` | `{buttonId: string, confirmed?: boolean}` | `ACTION_RESULT` with same `requestId` |
| `MONITOR_SUBSCRIBE` | `{active: boolean}` | none; `SYSTEM_MONITOR` follows while active |
| `PING` | `{}` | `PONG` with same `requestId` |

The client only names a button. The action type and configuration are loaded from the PC's
database. No command text, path or script is accepted from the network; unknown payload
fields are ignored. `confirmed: true` is the second tap on a key whose snapshot entry has
`confirm: true` (Shutdown, Restart…); without it the server answers `CONFIRMATION_REQUIRED`.

`MONITOR_SUBSCRIBE` `{active: boolean}`: sent when a System Monitoring page appears or
disappears on the device (and again after reconnecting). The PC samples only while at least
one device is subscribed.

## Server → client

| Type | Payload |
|---|---|
| `WELCOME` | `{deviceId, deviceName, serverName, protocolVersion}` |
| `SNAPSHOT` | `{activeProfileId, profiles: Profile[], pages: Page[], buttons: Button[], states: {[buttonId]: {state, detail}}}` — every profile, so devices can switch locally |
| `ACTION_RESULT` | `{buttonId, message?, data?}` plus `success`/`error` |
| `BUTTON_STATE` | `{buttonId, state, detail}` — only sent when the state changes; `state: null` clears it |
| `NAVIGATE` | `{pageId}` \| `{profileId}` \| `{back: true}` — only to the session that pressed a navigation key |
| `CONFIG_CHANGED` | reserved; configuration edits are pushed as a new `SNAPSHOT` (bursts within 50 ms coalesce into one) |
| `DEVICE_CONNECTED` / `DEVICE_DISCONNECTED` | `{deviceId, deviceName}` — to other clients |
| `SYSTEM_MONITOR` | `{timestamp, intervalMs, tiles: MetricId[], metrics}` — only to subscribed devices, only when values change, at least every 5 s while subscribed |
| `PONG` | `{}` |
| `ERROR` | `{}` plus `error` — e.g. `unknown_type`, `bad_message`, `bad_payload` |

Shapes sent to devices:

```text
Profile { id, name, iconRef, sortOrder }
Page    { id, profileId, name, iconRef, sortOrder }
Button  { id, pageId, parentId, kind, sortOrder, label, iconRef, actionType, appearance, enabled, confirm }
```

`kind` is `"action"` or `"folder"`; `parentId` is the folder a button is in (`null` = on the
page). Devices open folders themselves: there are no navigation messages for folders, each
device keeps its own folder trail, and an `ACTION_EXECUTE` for a folder fails with
`NOT_AN_ACTION`. The Back key inside a folder is drawn by the device and is never stored.

`Button` never includes `actionConfig` (paths, URLs, arguments) or `stateConfig`. `sortOrder` is
the only position information; each device lays keys out for its own screen.
`iconRef` is `builtin:<name>` or `asset:<sha256>.png` (served at `/api/assets/<sha256>.png`).
When a button has no icon, the PC fills in the action's default icon.

`detail` in states is a small display vocabulary rendered the same way for every action:

```text
text       short status line: "62%", "Muted", "Running", "Live"
icon       built-in icon replacing the key's icon while in this state, e.g. "volume-off"
tone       status light: "online" | "busy" | "error"
countdown  {remainingMs, running}; the device animates it locally (no per-second messages)
```

Profile selection is per device. A device keeps showing the profile it chose (remembered across
reloads) and follows the PC only when the PC changes `activeProfileId`.

## Close codes

| Code | Meaning | Client behaviour |
|---|---|---|
| 1000/1001/1006 | normal / going away / network | Reconnect with backoff |
| 4001 | No valid `HELLO` | Reconnect |
| 4002 | Unsupported protocol version | Reload the page once to get the matching dashboard |
| 4003 | Authentication failed | Clear token, show pairing |
| 4004 | Device revoked | Clear token, show pairing |

## Reconnect policy (client)

Exponential backoff from 0.5 s, doubling to a 15 s cap, with jitter in the upper half of each
step. The attempt counter resets after a `WELCOME`. Visibility change, `online` and `pageshow`
events trigger an immediate retry.

`SYSTEM_MONITOR.metrics` (bytes are bytes, speeds are bytes per second):

```text
cpu       {status, usage}
gpu       {status, usage, name, adapters: [{id, name, usage}]}
memory    {status, usage, used, total, available}
cpuTemp   {status, celsius, source}
gpuTemp   {status, celsius, name}
network   {status, interface, kind: wifi|ethernet, connected, linkBps, upBytesPerSec, downBytesPerSec}
disks     {status, drives: [{drive, usage, used, total, free, disk, celsius|null}]}
battery   {status, percent, charging, pluggedIn}
wifi      {status, connected, ssid|null, signal|null, rxKbps|null}
internet  {status, connected}
status    ok | unavailable | unsupported | error | unknown
```

A value that is not `ok` has no number; devices show N/A, never a guess. `Page.kind` is
`"deck"` or `"monitor"`.

## Action error codes

`UNKNOWN_BUTTON`, `BUTTON_DISABLED`, `UNKNOWN_ACTION`, `INVALID_CONFIG`, `FILE_NOT_FOUND`,
`FOLDER_NOT_FOUND`, `PATH_NOT_FOUND`, `PERMISSION_DENIED`, `NO_ASSOCIATION`, `INVALID_EXECUTABLE`,
`CANCELLED` (UAC prompt declined), `LAUNCH_FAILED`, `PLATFORM_ERROR`, `ACTION_FAILED`
(unexpected; details only in the PC log), `CONFIRMATION_REQUIRED`, `NOT_AVAILABLE` (coming soon),
`DEVICE_NOT_FOUND` (audio), `HIBERNATE_UNAVAILABLE`, `APP_NOT_RUNNING`, `APP_STILL_RUNNING`,
`DEVICE_ONLY` (navigation tested from the editor), `EXIT_CODE`, `TIMEOUT`, `HTTP_ERROR`,
`HTTP_FAILED`, `WEBSOCKET_FAILED`, `TOO_DEEP`, `NOT_AN_ACTION` (a folder was executed).
`error.message` is always written for the user and never contains a stack trace.

## Version history

- **v2, additive** (System Monitoring): `MONITOR_SUBSCRIBE`, `SYSTEM_MONITOR`, `Page.kind`.
- **v2, additive** (folders): `Button.parentId`, `Button.kind`. A dashboard loaded before the
  update would show folder contents flat on the page until it reloads (the PC serves the new one).
- **v2, additive** (action system): `NAVIGATE`, `confirmed`, `confirm`, state `detail` vocabulary,
  `state: null`. Older v2 clients ignore the new fields.
- **v2** (Milestone 2): profiles in `SNAPSHOT`; buttons positioned by `sortOrder` instead of
  `row`/`col`; `enabled` flag; upper-case action error codes.
- **v1** (Milestone 1): single profile, grid positions.
