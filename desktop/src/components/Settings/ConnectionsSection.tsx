import { useMemo } from "react";
import { useCalendar } from "../../hooks/useCalendar";
import { useGmail } from "../../hooks/useGmail";
import { STATUS_LABEL } from "../../types/calendar";

export interface ConnectionsSectionProps {
  onOpenCalendar: () => void;
  onOpenGmail: () => void;
}

/**
 * Entry points into the two drill-down screens. Both summaries are read
 * live from their own hooks (the same ones the drill-down screens use), so
 * this never shows a status that could be stale or faked.
 */
export function ConnectionsSection({ onOpenCalendar, onOpenGmail }: ConnectionsSectionProps) {
  const { status: calendarStatus, calendars } = useCalendar(true);
  const { status: gmailStatus } = useGmail(true);

  const calendarLabel = useMemo(() => {
    if (!calendarStatus) return "Checking…";
    // Calendars are only listable with full (read) access; write-only grants
    // nothing to count, so it keeps its own label rather than showing "0".
    if (calendarStatus === "full_access") {
      return `${calendars.length} calendar${calendars.length === 1 ? "" : "s"}`;
    }
    return STATUS_LABEL[calendarStatus];
  }, [calendarStatus, calendars.length]);

  const gmailLabel = gmailStatus === null ? "Checking…" : gmailStatus.connected ? "Connected" : "Not connected";
  const gmailConnected = gmailStatus?.connected ?? false;

  return (
    <section className="settings-section">
      <div className="settings-section__head">
        <h3 className="settings-section__title">Connections</h3>
      </div>
      <div className="settings-card">
        <button type="button" className="settings-connection-row" onClick={onOpenCalendar}>
          <span>Calendar</span>
          <span className="settings-connection-row__meta">
            {calendarLabel}
            <span aria-hidden="true">›</span>
          </span>
        </button>
        <button type="button" className="settings-connection-row" onClick={onOpenGmail}>
          <span>Gmail</span>
          <span
            className={`settings-connection-row__meta${gmailConnected ? " settings-connection-row__meta--on" : ""}`}
          >
            {gmailLabel}
            <span aria-hidden="true">›</span>
          </span>
        </button>
      </div>
    </section>
  );
}
