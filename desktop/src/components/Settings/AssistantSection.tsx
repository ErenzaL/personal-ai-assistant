import { useEffect, useRef, useState } from "react";
import { STYLE_LABEL, type AssistantSettings } from "../../types/settings";

export interface AssistantSectionProps {
  settings: AssistantSettings;
  onUpdate: (patch: { assistantName?: string; responseStyle?: string }) => void;
}

/** Pause after typing before the name is saved. */
const SAVE_DELAY_MS = 600;

/**
 * Assistant name and response style. Both are stored by the backend and feed
 * the assistant's system instructions. The name saves shortly after typing
 * stops, and immediately on Enter or when the field loses focus, so a change
 * is never lost by navigating away.
 */
export function AssistantSection({ settings, onUpdate }: AssistantSectionProps) {
  const [name, setName] = useState(settings.assistantName);
  const timer = useRef<number | undefined>(undefined);

  // Follow the stored value when it loads or changes elsewhere.
  useEffect(() => setName(settings.assistantName), [settings.assistantName]);

  useEffect(() => () => window.clearTimeout(timer.current), []);

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

  return (
    <section className="settings-section">
      <div className="settings-section__head">
        <h3 className="settings-section__title">Assistant</h3>
      </div>
      <label className="settings-field">
        <span className="settings-field__label">Name</span>
        <input
          className="settings-field__input"
          value={name}
          maxLength={24}
          onChange={(event) => onChange(event.target.value)}
          onBlur={() => {
            commit(name);
            if (!name.trim()) setName(settings.assistantName);
          }}
          onKeyDown={(event) => {
            if (event.key === "Enter") event.currentTarget.blur();
            if (event.key === "Escape") {
              window.clearTimeout(timer.current);
              setName(settings.assistantName);
            }
          }}
        />
      </label>
      <label className="settings-field">
        <span className="settings-field__label">Response style</span>
        <select
          className="settings-field__input"
          value={settings.responseStyle}
          onChange={(event) => onUpdate({ responseStyle: event.target.value })}
        >
          {settings.availableStyles.map((style) => (
            <option key={style} value={style}>
              {STYLE_LABEL[style] ?? style}
            </option>
          ))}
        </select>
      </label>
    </section>
  );
}
