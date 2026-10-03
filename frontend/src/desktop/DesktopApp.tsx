// The Windows desktop app's UI (served at /desktop, shown in the WebView2 window).
// It reuses the existing editor, devices, OBS and monitoring screens and adds the
// application views: dashboard, settings, logs, diagnostics.

import { useCallback, useEffect, useRef, useState } from "react";
import { PRODUCT_NAME } from "../branding";
import { EditorApp } from "../editor/EditorApp";
import { MonitorCanvas } from "../editor/MonitorCanvas";
import { ObsPanel } from "../editor/ObsPanel";
import { BuiltinIcon } from "../icons/BuiltinIcon";
import { bridge, whenBridgeReady } from "./api";
import { DashboardView } from "./DashboardView";
import { DevicesView } from "./DevicesView";
import { DiagnosticsView } from "./DiagnosticsView";
import { useHostState, useServerInfo, useSystemInfo } from "./hooks";
import { LogsView } from "./LogsView";
import { StateChip } from "./parts";
import { SettingsView } from "./SettingsView";
import "../editor/editor.css";
import "./desktop.css";

const VIEWS = [
  { id: "dashboard", label: "Dashboard", icon: "home" },
  { id: "editor", label: "Editor", icon: "page" },
  { id: "devices", label: "Devices", icon: "computer" },
  { id: "monitoring", label: "System Monitoring", icon: "activity" },
  { id: "integrations", label: "Integrations", icon: "plug" },
  { id: "settings", label: "Settings", icon: "settings" },
  { id: "logs", label: "Logs", icon: "text" },
  { id: "diagnostics", label: "Diagnostics", icon: "workflow" },
] as const;
type ViewId = (typeof VIEWS)[number]["id"];

function viewFromHash(): ViewId {
  const id = window.location.hash.replace(/^#\/?/, "");
  return (VIEWS.find((v) => v.id === id)?.id ?? "dashboard") as ViewId;
}

export function DesktopApp() {
  const [view, setView] = useState<ViewId>(viewFromHash);
  const { info, engineDown, refresh } = useServerInfo();
  const host = useHostState();
  const system = useSystemInfo(host);
  const [toast, setToast] = useState<{ text: string; error?: boolean } | null>(null);
  const toastTimer = useRef<ReturnType<typeof setTimeout>>(undefined);

  const notify = useCallback((text: string, error = false) => {
    clearTimeout(toastTimer.current);
    setToast({ text, error });
    toastTimer.current = setTimeout(() => setToast(null), error ? 6000 : 2500);
  }, []);

  const go = useCallback((id: string) => {
    const next = (VIEWS.find((v) => v.id === id)?.id ?? "dashboard") as ViewId;
    if (window.location.hash !== `#${next}`) window.history.pushState(null, "", `#${next}`);
    setView(next);
  }, []);

  useEffect(() => {
    const onHash = () => setView(viewFromHash());
    window.addEventListener("hashchange", onHash);
    window.addEventListener("popstate", onHash);
    return () => {
      window.removeEventListener("hashchange", onHash);
      window.removeEventListener("popstate", onHash);
    };
  }, []);

  // The tray can ask for a view (Settings); pick it up when the window gets focus.
  useEffect(() => {
    const take = async () => {
      const requested = await bridge()?.take_requested_view().catch(() => null);
      if (requested) go(requested);
    };
    const cancel = whenBridgeReady(() => void take());
    window.addEventListener("focus", take);
    return () => {
      cancel();
      window.removeEventListener("focus", take);
    };
  }, [go]);

  useEffect(() => {
    document.title = PRODUCT_NAME;
  }, []);

  const crashed = host?.engine === "crashed";
  const serverState = engineDown ? "engine-down" : (info?.state ?? "stopped");
  const address = info?.state === "running" ? info.urls[0]?.replace(/^http:\/\//, "") : undefined;

  return (
    <div className="desk">
      <nav className="desk__rail" aria-label="Sections">
        <div className="desk__brand">
          <img src="/favicon.svg" alt="" width={22} height={22} />
          <span>{PRODUCT_NAME}</span>
        </div>
        <ul className="desk__nav" role="list">
          {VIEWS.map((v) => (
            <li key={v.id}>
              <a
                href={`#${v.id}`}
                className="desk__link"
                aria-current={view === v.id ? "page" : undefined}
                onClick={(e) => {
                  e.preventDefault();
                  go(v.id);
                }}
              >
                <BuiltinIcon name={v.icon} className="desk__link-icon" />
                {v.label}
              </a>
            </li>
          ))}
        </ul>
        <div className="desk__rail-foot">
          <StateChip state={serverState} size="sm" />
        </div>
      </nav>

      <main className="desk__main" data-view={view}>
        {view === "dashboard" && <DashboardView info={info} engineDown={engineDown} onInfo={refresh} system={system} go={go} notify={notify} />}
        {view === "editor" && <EditorApp embedded />}
        {view === "devices" && <DevicesView notify={notify} />}
        {view === "monitoring" && (
          <div className="view view--flush">
            <MonitorCanvas notify={notify} />
          </div>
        )}
        {view === "integrations" && (
          <div className="view view--flush">
            <ObsPanel />
          </div>
        )}
        {view === "settings" && <SettingsView host={host} notify={notify} />}
        {view === "logs" && <LogsView notify={notify} />}
        {view === "diagnostics" && <DiagnosticsView host={host} system={system} notify={notify} />}
      </main>

      <footer className="desk__status" aria-label="Status">
        <span className="desk__status-item">
          Server <StateChip state={serverState} size="sm" />
        </span>
        <span className="desk__status-item">{address ? address : info?.state === "running" ? "This PC only" : "—"}</span>
        <span className="desk__status-item">
          {info?.devices ?? 0} {info?.devices === 1 ? "device" : "devices"}
        </span>
        <span className="desk__status-spacer" />
        <span className="desk__status-item">CPU {system?.cpu != null ? `${Math.round(system.cpu)}%` : "—"}</span>
        <span className="desk__status-item">RAM {system ? `${Math.round(system.memory.usage)}%` : "—"}</span>
        <span className="desk__status-item">v{host?.version ?? "1.0.0"}</span>
      </footer>

      {(engineDown || crashed) && (
        <div className="desk__down" role="alertdialog" aria-labelledby="down-title">
          <div className="desk__down-card">
            <h2 id="down-title">{crashed ? "The engine stopped" : "Reconnecting to the engine…"}</h2>
            <p>
              {crashed
                ? (host?.error ?? "It stopped unexpectedly. Your configuration is safe.")
                : "The part of OpenDeck that runs your buttons isn't answering. This usually clears in a moment."}
            </p>
            {bridge() && (
              <div className="desk__down-actions">
                <button type="button" className="btn btn-primary" onClick={() => bridge()?.host_command("restart-engine")}>
                  Restart engine
                </button>
                <button type="button" className="btn" onClick={() => bridge()?.host_command("open-logs")}>
                  Open logs folder
                </button>
              </div>
            )}
          </div>
        </div>
      )}

      <div className="toast" role="status" aria-live="polite" data-visible={toast ? "" : undefined} data-error={toast?.error || undefined}>
        {toast?.text}
      </div>
    </div>
  );
}
