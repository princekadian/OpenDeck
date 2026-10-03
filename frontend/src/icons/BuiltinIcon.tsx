// Built-in icons, drawn on a 24px grid with 1.75px strokes so they read as one family.
// Referenced as "builtin:<name>". Uploaded and extracted icons use "asset:<hash>.png".

import type { ReactElement } from "react";

const PATHS: Record<string, ReactElement> = {
  home: (
    <>
      <path d="M4 11 12 4l8 7" />
      <path d="M6 9.5V20h12V9.5" />
      <path d="M10 20v-5h4v5" />
    </>
  ),
  settings: (
    <>
      <circle cx="12" cy="12" r="3" />
      <path d="M12 2.5v3M12 18.5v3M2.5 12h3M18.5 12h3M5.3 5.3l2.1 2.1M16.6 16.6l2.1 2.1M5.3 18.7l2.1-2.1M16.6 7.4l2.1-2.1" />
    </>
  ),
  folder: <path d="M3.5 7a2 2 0 0 1 2-2h4l2 2.5h7a2 2 0 0 1 2 2V17a2 2 0 0 1-2 2h-13a2 2 0 0 1-2-2Z" />,
  file: (
    <>
      <path d="M14 3.5H7a2 2 0 0 0-2 2v13a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8.5Z" />
      <path d="M14 3.5v5h5M9 13h6M9 16.5h4" />
    </>
  ),
  globe: (
    <>
      <circle cx="12" cy="12" r="8.5" />
      <path d="M3.5 12h17M12 3.5c2.5 2.5 3.5 5.5 3.5 8.5s-1 6-3.5 8.5c-2.5-2.5-3.5-5.5-3.5-8.5s1-6 3.5-8.5Z" />
    </>
  ),
  link: (
    <>
      <path d="M10 14a4 4 0 0 0 5.7 0l3-3a4 4 0 0 0-5.7-5.7l-1 1" />
      <path d="M14 10a4 4 0 0 0-5.7 0l-3 3a4 4 0 0 0 5.7 5.7l1-1" />
    </>
  ),
  volume: (
    <>
      <path d="M4 9.5h3.5L12 5.5v13l-4.5-4H4Z" />
      <path d="M15.5 9a4 4 0 0 1 0 6M18 6.5a7.5 7.5 0 0 1 0 11" />
    </>
  ),
  "volume-off": (
    <>
      <path d="M4 9.5h3.5L12 5.5v13l-4.5-4H4Z" />
      <path d="m16 9.5 5 5M21 9.5l-5 5" />
    </>
  ),
  lock: (
    <>
      <rect x="5" y="10.5" width="14" height="10" rx="2" />
      <path d="M8 10.5V7.5a4 4 0 0 1 8 0v3" />
      <path d="M12 14.5v2.5" />
    </>
  ),
  power: (
    <>
      <path d="M12 3.5v8" />
      <path d="M7.2 6.6a7.5 7.5 0 1 0 9.6 0" />
    </>
  ),
  play: <path d="M8 5.5v13l10.5-6.5Z" />,
  pause: <path d="M8.5 5.5v13M15.5 5.5v13" />,
  previous: <path d="M18 6v12l-8.5-6ZM6.5 6v12" />,
  next: <path d="M6 6v12l8.5-6ZM17.5 6v12" />,
  monitor: (
    <>
      <rect x="3" y="4.5" width="18" height="12" rx="2" />
      <path d="M9 20h6M12 16.5V20" />
    </>
  ),
  game: (
    <>
      <path d="M7 8h10a4 4 0 0 1 3.9 4.8l-.8 4a2.4 2.4 0 0 1-4.1 1.1L14 16h-4l-2 1.9a2.4 2.4 0 0 1-4.1-1.1l-.8-4A4 4 0 0 1 7 8Z" />
      <path d="M8 11v3M6.5 12.5h3M15.5 12h.01M17.5 13.5h.01" />
    </>
  ),
  computer: (
    <>
      <rect x="4" y="5" width="16" height="10.5" rx="1.5" />
      <path d="M2.5 19h19" />
    </>
  ),
  app: (
    <>
      <rect x="4" y="4" width="16" height="16" rx="3" />
      <path d="M4 9h16" />
    </>
  ),
  key: (
    <>
      <rect x="3" y="6" width="18" height="12" rx="2" />
      <path d="M7 10h.01M11 10h.01M15 10h.01M8 14h8" />
    </>
  ),
  mail: (
    <>
      <rect x="3.5" y="5.5" width="17" height="13" rx="2" />
      <path d="m4 7 8 6 8-6" />
    </>
  ),
  music: (
    <>
      <path d="M9 18V5.5l11-2V16" />
      <circle cx="6.5" cy="18" r="2.5" />
      <circle cx="17.5" cy="16" r="2.5" />
    </>
  ),
  camera: (
    <>
      <rect x="3" y="7" width="13" height="10" rx="2" />
      <path d="m16 10.5 5-3v9l-5-3" />
    </>
  ),
  mic: (
    <>
      <rect x="9" y="3.5" width="6" height="11" rx="3" />
      <path d="M5.5 11.5a6.5 6.5 0 0 0 13 0M12 18v2.5" />
    </>
  ),
  download: <path d="M12 4v11m-4.5-4.5L12 15l4.5-4.5M5 19.5h14" />,
  terminal: (
    <>
      <rect x="3" y="4.5" width="18" height="15" rx="2" />
      <path d="m7 9.5 3 2.5-3 2.5M12.5 15h4.5" />
    </>
  ),
  "volume-up": (
    <>
      <path d="M4 9.5h3.5L12 5.5v13l-4.5-4H4Z" />
      <path d="M16 12h5M18.5 9.5v5" />
    </>
  ),
  "volume-down": (
    <>
      <path d="M4 9.5h3.5L12 5.5v13l-4.5-4H4Z" />
      <path d="M16 12h5" />
    </>
  ),
  "mic-off": (
    <>
      <path d="M15 10V6.5a3 3 0 0 0-5.7-1.3M9 9v2.5a3 3 0 0 0 4.6 2.5" />
      <path d="M5.5 11.5a6.5 6.5 0 0 0 10.4 5.2M18.4 13a6.5 6.5 0 0 0 .1-1.5M12 18v2.5M4 4l16 16" />
    </>
  ),
  speaker: (
    <>
      <rect x="6" y="3" width="12" height="18" rx="2" />
      <circle cx="12" cy="14" r="3.2" />
      <path d="M12 7h.01" />
    </>
  ),
  moon: <path d="M19.5 14.5A7.5 7.5 0 0 1 9.5 4.5a7.5 7.5 0 1 0 10 10Z" />,
  restart: (
    <>
      <path d="M4.5 12a7.5 7.5 0 1 0 2.2-5.3" />
      <path d="M4.5 4.5v4h4" />
    </>
  ),
  "sign-out": (
    <>
      <path d="M14 4.5H6.5a2 2 0 0 0-2 2v11a2 2 0 0 0 2 2H14" />
      <path d="M10 12h10.5m-3.5-3.5L20.5 12 17 15.5" />
    </>
  ),
  activity: <path d="M3 12h4l2.5-6 5 12 2.5-6h4" />,
  sun: (
    <>
      <circle cx="12" cy="12" r="3.8" />
      <path d="M12 2.5v2.2M12 19.3v2.2M2.5 12h2.2M19.3 12h2.2M5.3 5.3l1.6 1.6M17.1 17.1l1.6 1.6M5.3 18.7l1.6-1.6M17.1 6.9l1.6-1.6" />
    </>
  ),
  hdr: (
    <>
      <rect x="3" y="6" width="18" height="12" rx="2" />
      <path d="M7 9.5v5M10 9.5v5M7 12h3M13 9.5v5h1.2a2.5 2.5 0 0 0 0-5ZM18 14.5v-5" />
    </>
  ),
  window: (
    <>
      <rect x="3.5" y="4.5" width="17" height="15" rx="2" />
      <path d="M3.5 8.5h17" />
    </>
  ),
  "window-minimize": (
    <>
      <rect x="3.5" y="4.5" width="17" height="15" rx="2" />
      <path d="M8 15.5h8" />
    </>
  ),
  "window-maximize": (
    <>
      <rect x="3.5" y="4.5" width="17" height="15" rx="2" />
      <rect x="7.5" y="8.5" width="9" height="7" rx="1" />
    </>
  ),
  "window-close": (
    <>
      <rect x="3.5" y="4.5" width="17" height="15" rx="2" />
      <path d="m9 9.5 6 6M15 9.5l-6 6" />
    </>
  ),
  move: <path d="M12 3v18M3 12h18M12 3l-2.5 2.5M12 3l2.5 2.5M12 21l-2.5-2.5M12 21l2.5-2.5M3 12l2.5-2.5M3 12l2.5 2.5M21 12l-2.5-2.5M21 12l-2.5 2.5" />,
  resize: (
    <>
      <path d="M14 4h6v6M10 20H4v-6" />
      <path d="M20 4l-6.5 6.5M4 20l6.5-6.5" />
    </>
  ),
  switch: (
    <>
      <path d="M4 8h13l-3.5-3.5" />
      <path d="M20 16H7l3.5 3.5" />
    </>
  ),
  focus: (
    <>
      <path d="M4 8V5.5A1.5 1.5 0 0 1 5.5 4H8M16 4h2.5A1.5 1.5 0 0 1 20 5.5V8M20 16v2.5a1.5 1.5 0 0 1-1.5 1.5H16M8 20H5.5A1.5 1.5 0 0 1 4 18.5V16" />
      <circle cx="12" cy="12" r="2.5" />
    </>
  ),
  keyboard: (
    <>
      <rect x="2.5" y="6" width="19" height="12" rx="2" />
      <path d="M6 10h.01M9.5 10h.01M13 10h.01M16.5 10h.01M7 14h10" />
    </>
  ),
  text: <path d="M5 6.5V5h14v1.5M12 5v14M9.5 19h5" />,
  "play-pause": <path d="M4 6v12l8-6ZM15 6v12M19.5 6v12" />,
  stop: <rect x="6.5" y="6.5" width="11" height="11" rx="1.5" />,
  page: (
    <>
      <rect x="4.5" y="3.5" width="15" height="17" rx="2" />
      <path d="M8.5 8.5h7M8.5 12h7M8.5 15.5h4" />
    </>
  ),
  profile: (
    <>
      <circle cx="12" cy="8.5" r="3.5" />
      <path d="M5 20a7 7 0 0 1 14 0" />
    </>
  ),
  back: <path d="M10 6.5 4.5 12l5.5 5.5M4.5 12h15" />,
  workflow: (
    <>
      <rect x="3" y="4" width="7" height="5" rx="1.2" />
      <rect x="14" y="15" width="7" height="5" rx="1.2" />
      <path d="M6.5 9v4.5a2 2 0 0 0 2 2H14" />
    </>
  ),
  clock: (
    <>
      <circle cx="12" cy="12" r="8.5" />
      <path d="M12 7.5V12l3 2" />
    </>
  ),
  toggle: (
    <>
      <rect x="2.5" y="7" width="19" height="10" rx="5" />
      <circle cx="16.5" cy="12" r="3" />
    </>
  ),
  counter: <path d="M5 9h14M5 15h14M10 4.5 8 19.5M16 4.5l-2 15" />,
  timer: (
    <>
      <circle cx="12" cy="13" r="7.5" />
      <path d="M12 9v4l2.5 1.5M9.5 2.5h5M18.5 6.5l1.5-1.5" />
    </>
  ),
  http: (
    <>
      <circle cx="12" cy="12" r="8.5" />
      <path d="M3.5 12h17M12 3.5c2.5 2.5 3.5 5.5 3.5 8.5s-1 6-3.5 8.5c-2.5-2.5-3.5-5.5-3.5-8.5s1-6 3.5-8.5Z" />
      <path d="M17 17.5l3 3" />
    </>
  ),
  plug: (
    <>
      <path d="M9 3v4M15 3v4M6.5 7h11v4a5.5 5.5 0 0 1-11 0Z" />
      <path d="M12 16.5V21" />
    </>
  ),
  broadcast: (
    <>
      <circle cx="12" cy="12" r="2" />
      <path d="M8 8a5.7 5.7 0 0 0 0 8M16 8a5.7 5.7 0 0 1 0 8M5.2 5.2a9.6 9.6 0 0 0 0 13.6M18.8 5.2a9.6 9.6 0 0 1 0 13.6" />
    </>
  ),
  record: (
    <>
      <circle cx="12" cy="12" r="8.5" />
      <circle cx="12" cy="12" r="3.5" fill="currentColor" />
    </>
  ),
  star: <path d="m12 4 2.4 5 5.4.7-4 3.8 1 5.4-4.8-2.6-4.8 2.6 1-5.4-4-3.8 5.4-.7Z" />,
  cpu: (
    <>
      <rect x="6" y="6" width="12" height="12" rx="1.5" />
      <rect x="9.5" y="9.5" width="5" height="5" rx="0.5" />
      <path d="M9.5 3v3M14.5 3v3M9.5 18v3M14.5 18v3M3 9.5h3M3 14.5h3M18 9.5h3M18 14.5h3" />
    </>
  ),
  gpu: (
    <>
      <rect x="3" y="6.5" width="18" height="10" rx="1.5" />
      <circle cx="9" cy="11.5" r="2.5" />
      <path d="M14 10h4M14 13h4M6 16.5V19M10 16.5V19" />
    </>
  ),
  memory: (
    <>
      <rect x="3" y="7" width="18" height="9" rx="1" />
      <path d="M7 10v3M11 10v3M15 10v3M5 16v2.5M9 16v2.5M13 16v2.5M17 16v2.5" />
    </>
  ),
  thermometer: (
    <>
      <path d="M10 13.5V5a2 2 0 0 1 4 0v8.5a4 4 0 1 1-4 0Z" />
      <path d="M12 9v6.5" />
    </>
  ),
  upload: (
    <>
      <path d="M12 16V4M7 9l5-5 5 5" />
      <path d="M5 20h14" />
    </>
  ),
  disk: (
    <>
      <rect x="3.5" y="5" width="17" height="14" rx="2" />
      <path d="M3.5 14h17" />
      <circle cx="16.5" cy="16.5" r="0.75" fill="currentColor" />
    </>
  ),
  battery: (
    <>
      <rect x="3" y="7.5" width="16" height="9" rx="1.5" />
      <path d="M21 10.5v3" />
    </>
  ),
  "battery-charging": (
    <>
      <rect x="3" y="7.5" width="16" height="9" rx="1.5" />
      <path d="M21 10.5v3M11.5 9.5 9.5 12.5h3l-2 3" />
    </>
  ),
  wifi: (
    <>
      <path d="M2.5 9a14 14 0 0 1 19 0M5.5 12.5a9.5 9.5 0 0 1 13 0M8.5 16a5 5 0 0 1 7 0" />
      <circle cx="12" cy="19" r="0.75" fill="currentColor" />
    </>
  ),
  "wifi-off": (
    <>
      <path d="M8.5 16a5 5 0 0 1 7 0M5.5 12.5a9.5 9.5 0 0 1 4.5-2.4M14.5 10.2a9.5 9.5 0 0 1 4 2.3M2.5 9A14 14 0 0 1 7 6.4M3 3l18 18" />
      <circle cx="12" cy="19" r="0.75" fill="currentColor" />
    </>
  ),
  ethernet: (
    <>
      <rect x="5" y="5" width="14" height="12" rx="1.5" />
      <path d="M9 17v3h6v-3M8.5 8.5v2.5M11 8.5v2.5M13.5 8.5v2.5M16 8.5v2.5" />
    </>
  ),
};

/** Shown in the icon picker, in this order. */
export const BUILTIN_ICONS: Array<{ name: string; label: string }> = [
  { name: "home", label: "Home" },
  { name: "settings", label: "Settings" },
  { name: "folder", label: "Folder" },
  { name: "file", label: "File" },
  { name: "globe", label: "Globe" },
  { name: "link", label: "Link" },
  { name: "volume", label: "Volume" },
  { name: "volume-off", label: "Mute" },
  { name: "lock", label: "Lock" },
  { name: "power", label: "Power" },
  { name: "play", label: "Play" },
  { name: "pause", label: "Pause" },
  { name: "previous", label: "Previous" },
  { name: "next", label: "Next" },
  { name: "monitor", label: "Monitor" },
  { name: "game", label: "Game" },
  { name: "computer", label: "Computer" },
  { name: "app", label: "App" },
  { name: "mail", label: "Mail" },
  { name: "music", label: "Music" },
  { name: "camera", label: "Camera" },
  { name: "mic", label: "Microphone" },
  { name: "download", label: "Download" },
  { name: "terminal", label: "Terminal" },
  { name: "star", label: "Star" },
  { name: "key", label: "Key" },
  { name: "volume-up", label: "Volume up" },
  { name: "volume-down", label: "Volume down" },
  { name: "mic-off", label: "Mic off" },
  { name: "speaker", label: "Speaker" },
  { name: "moon", label: "Sleep" },
  { name: "restart", label: "Restart" },
  { name: "sign-out", label: "Sign out" },
  { name: "activity", label: "Activity" },
  { name: "sun", label: "Brightness" },
  { name: "hdr", label: "HDR" },
  { name: "window", label: "Window" },
  { name: "window-minimize", label: "Minimize" },
  { name: "window-maximize", label: "Maximize" },
  { name: "window-close", label: "Close" },
  { name: "move", label: "Move" },
  { name: "resize", label: "Resize" },
  { name: "switch", label: "Switch" },
  { name: "focus", label: "Focus" },
  { name: "keyboard", label: "Keyboard" },
  { name: "text", label: "Text" },
  { name: "play-pause", label: "Play / pause" },
  { name: "stop", label: "Stop" },
  { name: "page", label: "Page" },
  { name: "profile", label: "Profile" },
  { name: "back", label: "Back" },
  { name: "workflow", label: "Workflow" },
  { name: "clock", label: "Clock" },
  { name: "toggle", label: "Toggle" },
  { name: "counter", label: "Counter" },
  { name: "timer", label: "Timer" },
  { name: "http", label: "Web request" },
  { name: "plug", label: "Connection" },
  { name: "broadcast", label: "Broadcast" },
  { name: "record", label: "Record" },
];

export function builtinIconName(iconRef: string | null): string | null {
  return iconRef?.startsWith("builtin:") ? iconRef.slice("builtin:".length) : null;
}

export function BuiltinIcon({ name, className }: { name: string; className?: string }) {
  return (
    <svg
      className={className}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.75}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      focusable="false"
    >
      {PATHS[name] ?? PATHS.key}
    </svg>
  );
}
