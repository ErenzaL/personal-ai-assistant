import { useState } from "react";

export interface DataSectionProps {
  onClearHistory: () => Promise<void>;
  onClearMemories: () => Promise<void>;
}

type Action = "history" | "memories";

/** Two destructive actions, each behind an inline confirmation. */
export function DataSection({ onClearHistory, onClearMemories }: DataSectionProps) {
  const [pending, setPending] = useState<Action | null>(null);
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState<string | null>(null);

  const run = async (action: Action) => {
    setBusy(true);
    try {
      if (action === "history") {
        await onClearHistory();
        setNote("Conversation history cleared.");
      } else {
        await onClearMemories();
        setNote("Personal memories cleared.");
      }
    } catch {
      setNote("That didn't work. Please try again.");
    } finally {
      setBusy(false);
      setPending(null);
    }
  };

  const row = (action: Action, label: string, question: string) =>
    pending === action ? (
      <div className="settings-confirm">
        <span>{question}</span>
        <button
          type="button"
          className="settings-link settings-link--danger"
          disabled={busy}
          onClick={() => void run(action)}
        >
          Yes, clear
        </button>
        <button type="button" className="settings-link" onClick={() => setPending(null)}>
          Cancel
        </button>
      </div>
    ) : (
      <button
        type="button"
        className="settings-link settings-link--danger settings-link--block"
        onClick={() => {
          setNote(null);
          setPending(action);
        }}
      >
        {label}
      </button>
    );

  return (
    <section className="settings-section">
      <div className="settings-section__head">
        <h3 className="settings-section__title">Data &amp; Privacy</h3>
      </div>
      <div className="settings-card">
        {row("history", "Clear conversation history", "Delete every conversation? This cannot be undone.")}
        {row("memories", "Clear saved memories", "Forget everything Dully remembers about you?")}
      </div>
      <p className="settings-hint">These actions can't be undone.</p>
      {note && <p className="settings-hint">{note}</p>}
    </section>
  );
}
