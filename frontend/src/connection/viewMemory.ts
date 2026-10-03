// Remembers which profile and page this device last showed, so a reload or
// reconnect returns to the same place. Per device (localStorage), not shared.

const KEY = "msd.view.v1";

export interface ViewMemory {
  profileId: string | null;
  /** Last page shown per profile. */
  pages: Record<string, string>;
}

export function loadView(): ViewMemory {
  try {
    const parsed = JSON.parse(localStorage.getItem(KEY) ?? "null") as ViewMemory | null;
    if (parsed && typeof parsed.pages === "object") return parsed;
  } catch {
    /* unavailable or corrupt: start fresh */
  }
  return { profileId: null, pages: {} };
}

export function saveView(view: ViewMemory): void {
  try {
    localStorage.setItem(KEY, JSON.stringify(view));
  } catch {
    /* private mode: selection is simply not remembered */
  }
}
