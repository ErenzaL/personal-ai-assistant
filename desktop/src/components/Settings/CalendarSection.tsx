import { openCalendarSettings } from "../../services/calendar";
import { ReminderMinutesField } from "./ReminderMinutesField";
import { useMemo } from "react";
import { useCalendar } from "../../hooks/useCalendar";
import { STATUS_LABEL, SYSTEM_SETTINGS_PATH, UNKNOWN_SOURCE } from "../../types/calendar";
import type { CalendarInfo } from "../../types/calendar";

export interface CalendarSectionProps {
  /** EventKit identifier chosen for new events; null means the macOS default. */
  defaultCalendarId: string | null;
  onChangeDefaultCalendar: (id: string) => void;
  reminderMinutes: number;
  onChangeReminderMinutes: (minutes: number) => void;
}

/** Groups calendars under the account macOS files them under, preserving order. */
function groupBySource(calendars: CalendarInfo[]): [string, CalendarInfo[]][] {
  const groups = new Map<string, CalendarInfo[]>();
  for (const calendar of calendars) {
    const key = calendar.source_name ?? UNKNOWN_SOURCE;
    const existing = groups.get(key);
    if (existing) existing.push(calendar);
    else groups.set(key, [calendar]);
  }
  return [...groups.entries()];
}

/**
 * Calendar permission and the calendars it exposes. macOS owns the decision:
 * the button can show the system prompt only once, and after that the user
 * has to change it in System Settings.
 */
export function CalendarSection({
  defaultCalendarId,
  onChangeDefaultCalendar,
  reminderMinutes,
  onChangeReminderMinutes,
}: CalendarSectionProps) {
  const { status, calendars, canRequest, isBusy, error, requestAccess } = useCalendar(true);

  const grouped = useMemo(() => groupBySource(calendars), [calendars]);
  const writable = useMemo(() => calendars.filter((c) => c.allows_modifications), [calendars]);
  const systemDefault = useMemo(() => calendars.find((c) => c.is_default), [calendars]);

  const label = status ? STATUS_LABEL[status] : "Checking…";
  const tone =
    status === "full_access"
      ? "allowed"
      : status === "denied" || status === "restricted"
        ? "blocked"
        : "unknown";

  return (
    <section className="settings-section">
      <div className="settings-section__head">
        <h3 className="settings-section__title">Calendar</h3>
      </div>

      <div className="settings-field">
        <span className="settings-field__label">Status</span>
        <span className={`calendar-status calendar-status--${tone}`}>{label}</span>
      </div>

      {canRequest && (
        <button
          type="button"
          className="settings-button settings-section__footer"
          onClick={() => void requestAccess()}
          disabled={isBusy}
        >
          {isBusy ? "Waiting for macOS…" : "Allow Calendar Access"}
        </button>
      )}

      {calendars.length > 0 && (
        <>
          {grouped.map(([source, items]) => (
            <div key={source} className="calendar-group">
              <span className="calendar-group__source">{source}</span>
              <ul className="calendar-list">
                {items.map((calendar) => (
                  <li key={calendar.id} className="calendar-row">
                    <span
                      className="calendar-row__dot"
                      style={calendar.color ? { background: calendar.color } : undefined}
                      aria-hidden="true"
                    />
                    <span className="calendar-row__title">{calendar.title}</span>
                    {!calendar.allows_modifications && (
                      <span className="calendar-row__tag" title="Events cannot be added here">
                        read-only
                      </span>
                    )}
                  </li>
                ))}
              </ul>
            </div>
          ))}

          <label className="settings-field">
            <span className="settings-field__label">New events go to</span>
            <select
              className="settings-field__input"
              value={defaultCalendarId ?? ""}
              onChange={(event) => onChangeDefaultCalendar(event.target.value)}
            >
              <option value="">
                {systemDefault ? `macOS default (${systemDefault.title})` : "macOS default"}
              </option>
              {writable.map((calendar) => (
                <option key={calendar.id} value={calendar.id}>
                  {calendar.source_name ? `${calendar.source_name} — ${calendar.title}` : calendar.title}
                </option>
              ))}
            </select>
          </label>
        </>
      )}

      <ReminderMinutesField value={reminderMinutes} onChange={onChangeReminderMinutes} />

      {status === "denied" && (
        <>
          <p className="settings-empty">
            Calendar access is turned off for Dully, so it cannot read or add events. Turn it on under:
            <br />
            <span className="calendar-path">{SYSTEM_SETTINGS_PATH}</span>
          </p>
          <button type="button" className="settings-button" onClick={() => void openCalendarSettings()}>
            Open System Settings
          </button>
        </>
      )}

      {status === "restricted" && (
        <p className="settings-empty">
          Calendar access is blocked by a policy on this Mac, so it cannot be turned on here.
        </p>
      )}

      {status === "write_only" && (
        <>
          <p className="settings-empty">
            Only adding events is allowed. To let Dully read your schedule, open:
            <br />
            <span className="calendar-path">{SYSTEM_SETTINGS_PATH}</span>
          </p>
          <button type="button" className="settings-button" onClick={() => void openCalendarSettings()}>
            Open System Settings
          </button>
        </>
      )}

      {error && (
        <p className={error.code === "prompt_unavailable" ? "settings-empty" : "settings-error"}>
          {error.message}
        </p>
      )}
    </section>
  );
}
