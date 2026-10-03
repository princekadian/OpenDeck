import { useEffect, useRef, useState } from "react";
import { nextMonitor, type MonitorView } from "../connection/deckStore";
import { MonitorGrid } from "../monitor/MonitorGrid";
import { METRIC_LABELS } from "../monitor/tiles";
import { api, ApiError, type EditorPage, type EditorProfile, type MonitoringSettings } from "./api";
import { menuAt, type MenuItem, type MenuRequest } from "./Menu";
import { MoreButton } from "./Sidebar";

interface Props {
  /** The monitoring page being edited; absent in the desktop app's System Monitoring view. */
  profile?: EditorProfile;
  page?: EditorPage;
  onSelectProfile?: (profileId: string) => void;
  pageMenu?: (page: EditorPage) => MenuItem[];
  openMenu?: (request: MenuRequest) => void;
  notify: (text: string, error?: boolean) => void;
}

const INTERVALS = [1000, 2000, 5000];

/** A System Monitoring page in the editor: what devices will show, and its settings. */
export function MonitorCanvas({ profile, page, onSelectProfile, pageMenu, openMenu, notify }: Props) {
  const [settings, setSettings] = useState<MonitoringSettings | null>(null);
  const [monitor, setMonitor] = useState<MonitorView | null>(null);
  const [offline, setOffline] = useState(false);
  const monitorRef = useRef<MonitorView | null>(null);

  useEffect(() => {
    api.monitoring().then((r) => setSettings(r.settings), () => notify("Couldn't load monitoring settings.", true));
  }, [notify]);

  // Live preview: poll this PC's readings at the configured interval while the page is open.
  const intervalMs = settings?.intervalMs ?? 1000;
  useEffect(() => {
    let alive = true;
    let timer: ReturnType<typeof setTimeout>;
    const tick = async () => {
      try {
        const payload = await api.monitoringLive();
        if (!alive) return;
        monitorRef.current = nextMonitor(monitorRef.current, payload);
        setMonitor(monitorRef.current);
        setOffline(false);
      } catch {
        if (alive) setOffline(true);
      }
      if (alive) timer = setTimeout(tick, intervalMs);
    };
    void tick();
    return () => {
      alive = false;
      clearTimeout(timer);
    };
  }, [intervalMs]);

  async function save(next: MonitoringSettings) {
    const previous = settings;
    setSettings(next);
    try {
      const saved = await api.saveMonitoring(next);
      setSettings(saved.settings);
    } catch (e) {
      setSettings(previous);
      notify(e instanceof ApiError ? e.message : "Couldn't save monitoring settings.", true);
    }
  }

  function moveTile(index: number, delta: number) {
    if (!settings) return;
    const tiles = [...settings.tiles];
    const target = index + delta;
    if (target < 0 || target >= tiles.length) return;
    [tiles[index], tiles[target]] = [tiles[target], tiles[index]];
    void save({ ...settings, tiles });
  }

  return (
    <section className="canvas monitor-canvas" aria-labelledby="canvas-title">
      <header className="canvas__head">
        <div className="canvas__where">
          {profile && (
            <nav className="crumbs" aria-label="Location">
              <ol className="crumbs__list">
                <li>
                  <button type="button" className="crumbs__step" onClick={() => onSelectProfile?.(profile.id)}>
                    {profile.name}
                  </button>
                </li>
              </ol>
            </nav>
          )}
          <h1 id="canvas-title" className="canvas__title">
            {page?.name ?? "System Monitoring"}
          </h1>
        </div>
        {page && pageMenu && openMenu && (
          <div className="canvas__actions">
            <MoreButton label={`${page.name} options`} onOpen={(el) => openMenu({ ...menuAt(el), items: pageMenu(page), returnFocus: el })} />
          </div>
        )}
      </header>
      <p className="canvas__hint">
        Devices show these live readings from this PC. Readings are never stored; the PC only measures while a device or this preview is open.
      </p>

      <div className="monitor-canvas__body">
        <div className="monitor-canvas__preview" aria-label="Live preview">
          <MonitorGrid monitor={monitor} sizeClass="regular" online={!offline} />
        </div>

        <aside className="monitor-canvas__settings" aria-label="Monitoring settings">
          {settings && (
            <>
              <div className="field">
                <label className="field__label" htmlFor="monitor-interval">
                  Update every
                </label>
                <select
                  id="monitor-interval"
                  className="input input-narrow"
                  value={settings.intervalMs}
                  onChange={(e) => void save({ ...settings, intervalMs: Number(e.target.value) })}
                >
                  {INTERVALS.map((ms) => (
                    <option key={ms} value={ms}>
                      {ms / 1000} {ms === 1000 ? "second" : "seconds"}
                    </option>
                  ))}
                </select>
                <p className="field__hint">Applies to every monitoring page.</p>
              </div>

              <fieldset className="tile-list">
                <legend className="field__label">Tiles</legend>
                <ol className="tile-list__items">
                  {settings.tiles.map((tile, i) => (
                    <li key={tile.metric} className="tile-list__item">
                      <label className="tile-list__check">
                        <input
                          type="checkbox"
                          checked={tile.enabled}
                          onChange={(e) =>
                            void save({
                              ...settings,
                              tiles: settings.tiles.map((t) => (t.metric === tile.metric ? { ...t, enabled: e.target.checked } : t)),
                            })
                          }
                        />
                        <span>{METRIC_LABELS[tile.metric] ?? tile.metric}</span>
                      </label>
                      <span className="tile-list__move">
                        <button type="button" className="icon-btn" aria-label={`Move ${METRIC_LABELS[tile.metric]} up`} disabled={i === 0} onClick={() => moveTile(i, -1)}>
                          <Chevron up />
                        </button>
                        <button
                          type="button"
                          className="icon-btn"
                          aria-label={`Move ${METRIC_LABELS[tile.metric]} down`}
                          disabled={i === settings.tiles.length - 1}
                          onClick={() => moveTile(i, 1)}
                        >
                          <Chevron />
                        </button>
                      </span>
                    </li>
                  ))}
                </ol>
              </fieldset>

              <p className="field__hint monitor-canvas__note">
                Windows doesn't give apps a dependable CPU temperature. To show it, run LibreHardwareMonitor on this PC with
                Options › Remote Web Server switched on (port 8085). Values a PC doesn't report show as N/A, never as a guess.
              </p>
            </>
          )}
        </aside>
      </div>
    </section>
  );
}

function Chevron({ up = false }: { up?: boolean }) {
  return (
    <svg viewBox="0 0 24 24" width="16" height="16" aria-hidden="true">
      <path d={up ? "m6 15 6-6 6 6" : "m6 9 6 6 6-6"} fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}
