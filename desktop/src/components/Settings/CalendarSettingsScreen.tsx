import { useMemo, useState } from "react";
import { openCalendarSettings } from "../../services/calendar";
import { useCalendar } from "../../hooks/useCalendar";
import { STATUS_LABEL, SYSTEM_SETTINGS_PATH, UNKNOWN_SOURCE } from "../../types/calendar";
import type { CalendarInfo } from "../../types/calendar";

export interface CalendarSettingsScreenProps {
  /** EventKit identifier chosen for new events; null means the macOS default. */
  defaultCalendarId: string | null;
  onChangeDefaultCalendar: (id: string) => void;
  hiddenCalendarIds: string[];
  onChangeHiddenCalendarIds: (ids: string[]) => void;
}

/** A friendly group heading derived from EventKit's own source_type, e.g.
 *  "ICLOUD" or "GOOGLE · name@gmail.com" -- never a guess beyond what
 *  EventKit itself reports. */
function groupLabel(sourceType: CalendarInfo["source_type"], sourceName: string | null): string {
  const base =
    sourceType === "mobile_me"
      ? "iCloud"
      : sourceType === "local"
        ? "On My Mac"
        : sourceType === "exchange"
          ? "Exchange"
          : sourceType === "subscribed"
            ? "Subscribed"
            : sourceType === "birthdays"
              ? "Birthdays"
              : sourceType === "cal_dav"
                ? sourceName?.includes("@")
                  ? "Google"
                  : "CalDAV"
                : null;
  if (!base) return (sourceName ?? UNKNOWN_SOURCE).toUpperCase();
  if (sourceName && sourceName.toLowerCase() !== base.toLowerCase()) {
    return `${base.toUpperCase()} · ${sourceName}`;
  }
  return base.toUpperCase();
}

/** Groups calendars under the account macOS files them under, preserving order. */
function groupBySource(calendars: CalendarInfo[]): [string, CalendarInfo[]][] {
  const groups = new Map<string, CalendarInfo[]>();
  for (const calendar of calendars) {
    const key = groupLabel(calendar.source_type, calendar.source_name);
    const existing = groups.get(key);
    if (existing) existing.push(calendar);
    else groups.set(key, [calendar]);
  }
  return [...groups.entries()];
}

/**
 * Calendar permission, the calendars it exposes, and which of them Dully is
 * allowed to see. Unlike Gmail, macOS -- not Dully -- holds this grant: there
 * is no API for an app to revoke its own EventKit access, so "Manage" here
 * only opens System Settings, where the user turns it off themselves.
 */
export function CalendarSettingsScreen({
  defaultCalendarId,
  onChangeDefaultCalendar,
  hiddenCalendarIds,
  onChangeHiddenCalendarIds,
}: CalendarSettingsScreenProps) {
  const { status, calendars, canRequest, isBusy, error, requestAccess } = useCalendar(true);
  const [editingDefault, setEditingDefault] = useState(false);

  const grouped = useMemo(() => groupBySource(calendars), [calendars]);
  const writable = useMemo(
    () => calendars.filter((c) => c.allows_modifications && !hiddenCalendarIds.includes(c.id)),
    [calendars, hiddenCalendarIds],
  );
  const systemDefault = useMemo(() => calendars.find((c) => c.is_default), [calendars]);
  const selectedDefault = calendars.find((c) => c.id === defaultCalendarId);

  const label = status ? STATUS_LABEL[status] : "Checking…";
  const connected = status === "full_access" || status === "write_only";
  const tone = connected ? "allowed" : status === "denied" || status === "restricted" ? "blocked" : "unknown";

  const toggleHidden = (id: string, visible: boolean) => {
    onChangeHiddenCalendarIds(
      visible ? hiddenCalendarIds.filter((h) => h !== id) : [...hiddenCalendarIds, id],
    );
  };

  const anyReadOnly = calendars.some((c) => !c.allows_modifications);

  return (
    <div className="settings-panel">
      <div className="settings-card">
        <div className="settings-card__head-group">
          <div className="settings-card__head">
            <span className="settings-card__title">Calendar Access</span>
            {(connected || status === "denied") && (
              <button type="button" className="settings-link" onClick={() => void openCalendarSettings()}>
                Manage
              </button>
            )}
          </div>
          <span className={`calendar-status calendar-status--${tone}`}>{label}</span>
        </div>
        {canRequest && (
          <button type="button" className="settings-button" onClick={() => void requestAccess()} disabled={isBusy}>
            {isBusy ? "Waiting for macOS…" : "Connect Calendar"}
          </button>
        )}
      </div>

      {status === "denied" && (
        <p className="settings-empty">
          Calendar access is turned off for Dully, so it cannot read or add events. Manage opens:
          <br />
          <span className="calendar-path">{SYSTEM_SETTINGS_PATH}</span>
        </p>
      )}
      {status === "restricted" && (
        <p className="settings-empty">
          Calendar access is blocked by a policy on this Mac, so it cannot be turned on here.
        </p>
      )}
      {status === "write_only" && (
        <p className="settings-empty">
          Only adding events is allowed. To let Dully read your schedule too, use Manage above to open:
          <br />
          <span className="calendar-path">{SYSTEM_SETTINGS_PATH}</span>
        </p>
      )}
      {error && (
        <p className={error.code === "prompt_unavailable" ? "settings-empty" : "settings-error"}>
          {error.message}
        </p>
      )}

      {connected && calendars.length > 0 && (
        <>
          <section className="settings-section">
            <div className="settings-section__head">
              <h3 className="settings-section__title">Defaults</h3>
            </div>
            <div className="settings-card">
              {editingDefault ? (
                <label className="settings-field">
                  <span className="settings-field__label">Add new events to</span>
                  <select
                    className="settings-field__input"
                    autoFocus
                    value={defaultCalendarId ?? ""}
                    onChange={(event) => {
                      onChangeDefaultCalendar(event.target.value);
                      setEditingDefault(false);
                    }}
                    onBlur={() => setEditingDefault(false)}
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
              ) : (
                <button type="button" className="settings-connection-row" onClick={() => setEditingDefault(true)}>
                  <span>Add new events to</span>
                  <span className="settings-connection-row__meta">
                    {selectedDefault
                      ? `${selectedDefault.source_name ? `${selectedDefault.source_name} · ` : ""}${selectedDefault.title}`
                      : systemDefault
                        ? `macOS default · ${systemDefault.title}`
                        : "macOS default"}
                    <span aria-hidden="true">›</span>
                  </span>
                </button>
              )}
            </div>
            <p className="settings-hint">Only calendars Dully can write to, and that aren't turned off below.</p>
          </section>

          {grouped.map(([source, items], index) => (
            <div key={source} className="calendar-group">
              <span className="calendar-group__source">{source}</span>
              <div className="settings-card">
                <ul className="calendar-list">
                  {items.map((calendar) => {
                    const visible = !hiddenCalendarIds.includes(calendar.id);
                    return (
                      <li key={calendar.id} className="calendar-row">
                        <span
                          className="calendar-row__dot"
                          style={calendar.color ? { background: calendar.color } : undefined}
                          aria-hidden="true"
                        />
                        <span className="calendar-row__title">{calendar.title}</span>
                        {!calendar.allows_modifications && (
                          <span className="calendar-row__tag" title="Events cannot be added here">
                            Read-only
                          </span>
                        )}
                        <span className={`settings-toggle settings-toggle--sm${visible ? " settings-toggle--on" : ""}`}>
                          <input
                            type="checkbox"
                            role="switch"
                            aria-checked={visible}
                            aria-label={`Show ${calendar.title} to Dully`}
                            checked={visible}
                            onChange={(event) => toggleHidden(calendar.id, event.target.checked)}
                          />
                          <span className="settings-toggle__knob" />
                        </span>
                      </li>
                    );
                  })}
                </ul>
              </div>
              {index === 0 && (
                <p className="settings-hint">Turn a calendar off to hide it from Dully -- it stays untouched, just unseen.</p>
              )}
            </div>
          ))}
          {anyReadOnly && (
            <p className="settings-hint">Read-only calendars can be viewed but Dully can't add events to them.</p>
          )}
        </>
      )}
    </div>
  );
}
