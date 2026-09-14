import { useEffect, useState } from "react";
import type { ReminderView } from "../../services/reminders";
import "./ReminderPopup.css";

export interface ReminderPopupProps {
  reminder: ReminderView;
  onSnooze: (minutes: number) => void;
  onDismiss: () => void;
}

function startLabel(iso: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso;
  const time = date.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
  const today = new Date();
  const sameDay = date.toDateString() === today.toDateString();
  if (sameDay) return `Today at ${time}`;
  const tomorrow = new Date(today);
  tomorrow.setDate(today.getDate() + 1);
  if (date.toDateString() === tomorrow.toDateString()) return `Tomorrow at ${time}`;
  return `${date.toLocaleDateString([], { weekday: "short" })} at ${time}`;
}

function countdown(startUnix: number): string {
  const minutes = Math.round((startUnix - Date.now() / 1000) / 60);
  if (minutes <= 0) return "Starting now";
  if (minutes === 1) return "Starts in 1 minute";
  return `Starts in ${minutes} minutes`;
}

/**
 * Compact card for one upcoming event. It is the same logical reminder as
 * the native notification; both buttons act on that one record.
 */
export function ReminderPopup({ reminder, onSnooze, onDismiss }: ReminderPopupProps) {
  // Keep "starts in N minutes" honest while the popup stays open.
  const [, tick] = useState(0);
  useEffect(() => {
    const timer = window.setInterval(() => tick((n) => n + 1), 30_000);
    return () => window.clearInterval(timer);
  }, []);

  return (
    <section className="reminder" role="alertdialog" aria-label="Upcoming event">
      <span className="reminder__kicker">{countdown(reminder.start_unix)}</span>
      <strong className="reminder__title" title={reminder.title}>
        {reminder.title}
      </strong>
      <span className="reminder__time">{startLabel(reminder.start)}</span>
      <div className="reminder__actions">
        <button type="button" className="reminder__button" onClick={() => onSnooze(5)}>
          Snooze 5 min
        </button>
        <button type="button" className="reminder__button" onClick={() => onSnooze(10)}>
          Snooze 10 min
        </button>
        <button type="button" className="reminder__button reminder__button--quiet" onClick={onDismiss}>
          Dismiss
        </button>
      </div>
    </section>
  );
}
