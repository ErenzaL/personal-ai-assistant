import { useEffect, useState } from "react";
import { REMINDER_MINUTES_MAX, REMINDER_MINUTES_MIN } from "../../types/settings";

export interface ReminderMinutesFieldProps {
  value: number;
  onChange: (minutes: number) => void;
}

/** Minutes before an event to alert. Commits on blur or Enter, within range. */
export function ReminderMinutesField({ value, onChange }: ReminderMinutesFieldProps) {
  const [text, setText] = useState(String(value));
  useEffect(() => setText(String(value)), [value]);

  const commit = () => {
    const parsed = Math.round(Number(text));
    if (!Number.isFinite(parsed) || text.trim() === "") {
      setText(String(value));
      return;
    }
    const clamped = Math.min(REMINDER_MINUTES_MAX, Math.max(REMINDER_MINUTES_MIN, parsed));
    setText(String(clamped));
    if (clamped !== value) onChange(clamped);
  };

  return (
    <label className="settings-field">
      <span className="settings-field__label">Remind me before events</span>
      <span className="settings-minutes">
        <input
          className="settings-field__input settings-field__input--short"
          type="number"
          inputMode="numeric"
          min={REMINDER_MINUTES_MIN}
          max={REMINDER_MINUTES_MAX}
          value={text}
          onChange={(event) => setText(event.target.value)}
          onBlur={commit}
          onKeyDown={(event) => {
            if (event.key === "Enter") event.currentTarget.blur();
          }}
        />
        <span>min</span>
      </span>
    </label>
  );
}
