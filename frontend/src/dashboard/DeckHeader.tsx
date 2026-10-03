import type { DeckState } from "../connection/deckStore";

function connectionText(deck: DeckState): { tone: string | undefined; label: string } {
  switch (deck.status) {
    case "online":
      return { tone: "online", label: "Connected" };
    case "connecting":
      return { tone: "busy", label: "Connecting" };
    case "offline":
      return { tone: "error", label: "PC offline" };
    case "unauthorized":
      return { tone: "error", label: "Not paired" };
    case "outdated":
      return { tone: "busy", label: "Updating" };
  }
}

interface Props {
  deck: DeckState;
  pageName: string;
  onSelectProfile: (profileId: string) => void;
  /** Jump to a level of the folder trail (0 = the page). */
  onFolderLevel: (depth: number) => void;
  onBack: () => void;
}

export function DeckHeader({ deck, pageName, onSelectProfile, onFolderLevel, onBack }: Props) {
  const folders = deck.folderStack.map((id) => deck.buttons.find((b) => b.id === id)?.label || "Folder");
  const { tone, label } = connectionText(deck);
  const profile = deck.profiles.find((p) => p.id === deck.activeProfileId);
  return (
    <header className="deck-header">
      <div className="deck-header__where">
        {deck.profiles.length > 1 && profile && (
          <label className="profile-switch">
            <span className="profile-switch__name">{profile.name}</span>
            <svg className="profile-switch__chevron" viewBox="0 0 24 24" aria-hidden="true">
              <path d="m7 10 5 5 5-5" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round" />
            </svg>
            {/* Invisible native select: the device's own picker, large and accessible. */}
            <select
              className="profile-switch__select"
              value={profile.id}
              onChange={(e) => onSelectProfile(e.target.value)}
              aria-label="Choose profile"
            >
              {deck.profiles.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.name}
                </option>
              ))}
            </select>
          </label>
        )}
        {folders.length === 0 ? (
          <h1 className="deck-header__page">{pageName}</h1>
        ) : (
          <nav className="deck-trail" aria-label="Location">
            <button type="button" className="deck-trail__step" onClick={() => onFolderLevel(0)}>
              {pageName}
            </button>
            {folders.map((name, i) => (
              <span key={i} className="deck-trail__part">
                <span className="deck-trail__sep" aria-hidden="true">
                  ›
                </span>
                {i === folders.length - 1 ? (
                  <h1 className="deck-header__page" aria-current="location">
                    {name}
                  </h1>
                ) : (
                  <button type="button" className="deck-trail__step" onClick={() => onFolderLevel(i + 1)}>
                    {name}
                  </button>
                )}
              </span>
            ))}
          </nav>
        )}
      </div>
      {folders.length > 0 && (
        <button type="button" className="deck-header__back" onClick={onBack}>
          <svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true">
            <path d="M10 6.5 4.5 12l5.5 5.5M4.5 12h15" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round" />
          </svg>
          Back
        </button>
      )}
      <div className="deck-header__link" role="status" aria-live="polite">
        {deck.serverName && <span className="deck-header__pc">{deck.serverName}</span>}
        <span className="deck-header__pill">
          <span className="led" data-tone={tone} aria-hidden="true" />
          {label}
        </span>
      </div>
    </header>
  );
}
