import { useState } from "react";
import { Toggle } from "./Toggle";

export interface NotificationsSectionProps {
  enabled: boolean;
  onChange: (enabled: boolean) => void;
  reminderMinutes: number;
  onChangeReminderMinutes: (minutes: number) => void;
}

/** Common lead times; the current value is always included even if it isn't one of these. */
const PRESETS = [5, 10, 15, 30, 60];

export function NotificationsSection({
  enabled,
  onChange,
  reminderMinutes,
  onChangeReminderMinutes,
}: NotificationsSectionProps) {
  const [editing, setEditing] = useState(false);
  const options = [...new Set([...PRESETS, reminderMinutes])].sort((a, b) => a - b);

  return (
    <section className="settings-section">
      <div className="settings-section__head">
        <h3 className="settings-section__title">Notifications</h3>
      </div>
      <div className="settings-card">
        <Toggle label="Event reminders" checked={enabled} onChange={onChange} />
        {enabled &&
          (editing ? (
            <label className="settings-field">
              <span className="settings-field__label">Remind me</span>
              <select
                className="settings-field__input"
                autoFocus
                value={reminderMinutes}
                onChange={(event) => {
                  onChangeReminderMinutes(Number(event.target.value));
                  setEditing(false);
                }}
                onBlur={() => setEditing(false)}
              >
                {options.map((minutes) => (
                  <option key={minutes} value={minutes}>
                    {minutes} min before
                  </option>
                ))}
              </select>
            </label>
          ) : (
            <button type="button" className="settings-connection-row" onClick={() => setEditing(true)}>
              <span>Remind me</span>
              <span className="settings-connection-row__meta">
                {reminderMinutes} min before
                <span aria-hidden="true">›</span>
              </span>
            </button>
          ))}
      </div>
      {!enabled && <p className="settings-hint">No banners or popups before events.</p>}
    </section>
  );
}
