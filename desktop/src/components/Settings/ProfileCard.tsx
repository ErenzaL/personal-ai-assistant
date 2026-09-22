import { useEffect, useRef, useState } from "react";
import type { AssistantSettings } from "../../types/settings";

export interface ProfileCardProps {
  settings: AssistantSettings;
  onUpdate: (patch: { assistantName?: string }) => void;
}

/** Pause after typing before the name is saved. */
const SAVE_DELAY_MS = 600;

/**
 * Settings' header card: an avatar (the assistant's own initial), its name,
 * and a link that reveals the rename field in place. The name is stored by
 * the backend and fed into its system instructions; it saves shortly after
 * typing stops, and immediately on Enter or when the field loses focus.
 */
export function ProfileCard({ settings, onUpdate }: ProfileCardProps) {
  const [editing, setEditing] = useState(false);
  const [name, setName] = useState(settings.assistantName);
  const timer = useRef<number | undefined>(undefined);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => setName(settings.assistantName), [settings.assistantName]);
  useEffect(() => () => window.clearTimeout(timer.current), []);
  useEffect(() => {
    if (editing) inputRef.current?.focus();
  }, [editing]);

  const commit = (value: string) => {
    window.clearTimeout(timer.current);
    const trimmed = value.trim();
    if (!trimmed || trimmed === settings.assistantName) return;
    onUpdate({ assistantName: trimmed });
  };

  const onChange = (value: string) => {
    setName(value);
    window.clearTimeout(timer.current);
    timer.current = window.setTimeout(() => commit(value), SAVE_DELAY_MS);
  };

  const initial = settings.assistantName.trim().charAt(0).toUpperCase() || "D";

  return (
    <section className="settings-profile">
      <span className="settings-avatar" aria-hidden="true">
        {initial}
      </span>
      <div className="settings-profile__body">
        {editing ? (
          <input
            ref={inputRef}
            className="settings-profile__input"
            value={name}
            maxLength={24}
            onChange={(event) => onChange(event.target.value)}
            onBlur={() => {
              commit(name);
              if (!name.trim()) setName(settings.assistantName);
              setEditing(false);
            }}
            onKeyDown={(event) => {
              if (event.key === "Enter") event.currentTarget.blur();
              if (event.key === "Escape") {
                window.clearTimeout(timer.current);
                setName(settings.assistantName);
                setEditing(false);
              }
            }}
          />
        ) : (
          <span className="settings-profile__name">{settings.assistantName}</span>
        )}
        <span className="settings-profile__subtitle">Your personal assistant</span>
        {!editing && (
          <button type="button" className="settings-link" onClick={() => setEditing(true)}>
            Edit name
          </button>
        )}
      </div>
    </section>
  );
}
