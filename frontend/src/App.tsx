import { lazy, Suspense, useCallback, useState } from "react";
import { clearCredentials, loadCredentials, type DeviceCredentials } from "./connection/credentials";
import { Dashboard } from "./dashboard/Dashboard";
import { PairingScreen } from "./dashboard/PairingScreen";

// Editor code is only downloaded on the PC; control devices never load it.
const EditorApp = lazy(() => import("./editor/EditorApp").then((m) => ({ default: m.EditorApp })));
// The Windows desktop app's window (served by the engine on 127.0.0.1).
const DesktopApp = lazy(() => import("./desktop/DesktopApp").then((m) => ({ default: m.DesktopApp })));

export function App() {
  const path = window.location.pathname.replace(/\/+$/, "");
  if (path === "/desktop") {
    return (
      <Suspense fallback={null}>
        <DesktopApp />
      </Suspense>
    );
  }
  // Editor mode lives on the PC; the API refuses these routes from other devices.
  if (path === "/editor" || path === "/pc") {
    return (
      <Suspense fallback={null}>
        <EditorApp initialView={path === "/pc" ? "devices" : undefined} />
      </Suspense>
    );
  }
  return <DeviceApp />;
}

function DeviceApp() {
  const [credentials, setCredentials] = useState<DeviceCredentials | null>(loadCredentials);
  const [notice, setNotice] = useState<string | undefined>();

  const handleUnauthorized = useCallback(() => {
    clearCredentials();
    setCredentials(null);
    setNotice("This device was removed or its pairing expired. Pair it again.");
  }, []);

  if (!credentials) return <PairingScreen notice={notice} onPaired={setCredentials} />;
  return <Dashboard token={credentials.token} onUnauthorized={handleUnauthorized} />;
}
