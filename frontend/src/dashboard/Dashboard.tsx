import { useEffect, useMemo } from "react";
import { DeckStore, useDeck, type HistoryEntry } from "../connection/deckStore";
import { sizeClassFor } from "../layout/gridLayout";
import { useViewport } from "../layout/useMeasure";
import { MonitorGrid } from "../monitor/MonitorGrid";
import { DeckGrid } from "./DeckGrid";
import { DeckHeader } from "./DeckHeader";
import { OfflineBanner } from "./OfflineBanner";
import { PageBar } from "./PageBar";
import "./dashboard.css";

interface Props {
  token: string;
  onUnauthorized: () => void;
  /** Injected in tests. */
  store?: DeckStore;
}

export function Dashboard({ token, onUnauthorized, store: injected }: Props) {
  const store = useMemo(() => injected ?? new DeckStore(token, onUnauthorized), [injected, token, onUnauthorized]);
  const deck = useDeck(store);
  const viewport = useViewport();
  const sizeClass = sizeClassFor(viewport.width, viewport.height);

  useEffect(() => {
    store.start();
    // Safari suspends sockets in background tabs and after sleep; reconnect at once on return.
    const wake = () => {
      if (document.visibilityState === "visible") store.nudge();
    };
    document.addEventListener("visibilitychange", wake);
    window.addEventListener("online", wake);
    window.addEventListener("pageshow", wake);
    // Browser Back/Forward moves through folders without reloading.
    const onPop = (e: PopStateEvent) => store.restoreFromHistory((e.state as { msd?: HistoryEntry } | null)?.msd);
    window.addEventListener("popstate", onPop);
    return () => {
      document.removeEventListener("visibilitychange", wake);
      window.removeEventListener("online", wake);
      window.removeEventListener("pageshow", wake);
      window.removeEventListener("popstate", onPop);
      store.stop();
    };
  }, [store]);

  // The PC was updated to a newer protocol: load the matching dashboard code once.
  useEffect(() => {
    if (deck.status !== "outdated") return;
    try {
      const last = Number(sessionStorage.getItem("msd.reloadedAt") ?? 0);
      if (Date.now() - last < 30_000) return; // avoid a reload loop
      sessionStorage.setItem("msd.reloadedAt", String(Date.now()));
    } catch {
      /* storage unavailable: still reload */
    }
    window.location.reload();
  }, [deck.status]);

  const page = deck.pages.find((p) => p.id === deck.activePageId) ?? null;
  const profilePages = deck.pages.filter((p) => p.profileId === deck.activeProfileId);
  const monitoring = page?.kind === "monitor";

  // The PC samples only while some device shows a monitoring page, so say when this one does.
  useEffect(() => {
    const sync = () => store.watchMonitor(monitoring && document.visibilityState === "visible");
    sync();
    document.addEventListener("visibilitychange", sync);
    return () => {
      document.removeEventListener("visibilitychange", sync);
      store.watchMonitor(false);
    };
  }, [store, monitoring]);

  return (
    <div className="deck" data-status={deck.status} data-size={sizeClass}>
      <DeckHeader
        deck={deck}
        pageName={page?.name ?? ""}
        onSelectProfile={(id) => store.selectProfile(id)}
        onFolderLevel={(depth) => store.goToFolderLevel(depth)}
        onBack={() => store.closeFolder()}
      />
      <main className="deck-main">
        {page && monitoring ? (
          <MonitorGrid monitor={deck.monitor} sizeClass={sizeClass} online={deck.status === "online"} />
        ) : page ? (
          <DeckGrid
            page={page}
            deck={deck}
            sizeClass={sizeClass}
            onPress={(id) => (deck.buttons.find((b) => b.id === id)?.kind === "folder" ? store.openFolder(id) : store.press(id))}
            onBack={() => store.closeFolder()}
          />
        ) : (
          <p className="deck-empty">
            {deck.synced ? "No pages yet. Add a page in the editor on your PC." : "Loading your deck…"}
          </p>
        )}
        {deck.status === "offline" && <OfflineBanner retryInMs={deck.retryInMs} onRetry={() => store.nudge()} />}
      </main>
      {profilePages.length > 1 && (
        <PageBar pages={profilePages} activePageId={deck.activePageId} onSelect={(id) => store.selectPage(id)} />
      )}
    </div>
  );
}
