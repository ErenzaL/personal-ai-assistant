import { useCallback, useEffect, useRef, useState } from "react";
import {
  activeReminder,
  dismissReminder,
  onReminderFired,
  snoozeReminder,
  type ReminderView,
} from "../services/reminders";

/** How long the mascot bounces after an alert. */
const BOUNCE_MS = 1100;

/**
 * The one reminder currently shown, if any. Restores it on load so a popup
 * survives an app restart, and follows alerts from the native service.
 */
export function useReminders() {
  const [reminder, setReminder] = useState<ReminderView | null>(null);
  const [bounce, setBounce] = useState(false);
  const bounceTimer = useRef<number | undefined>(undefined);

  useEffect(() => {
    let cancelled = false;
    let unlisten: (() => void) | undefined;

    activeReminder()
      .then((current) => {
        if (!cancelled && current) setReminder(current);
      })
      .catch(() => undefined);

    onReminderFired((fired) => {
      setReminder(fired);
      setBounce(true);
      window.clearTimeout(bounceTimer.current);
      bounceTimer.current = window.setTimeout(() => setBounce(false), BOUNCE_MS);
    }).then((stop) => {
      if (cancelled) stop();
      else unlisten = stop;
    });

    return () => {
      cancelled = true;
      unlisten?.();
      window.clearTimeout(bounceTimer.current);
    };
  }, []);

  // Close the popup at once; the native side shrinks the window afterwards,
  // so nothing is clipped mid-resize.
  const snooze = useCallback(
    async (minutes: number) => {
      if (!reminder) return;
      const { key } = reminder;
      setReminder(null);
      await snoozeReminder(key, minutes).catch(() => undefined);
    },
    [reminder],
  );

  const dismiss = useCallback(async () => {
    if (!reminder) return;
    const { key } = reminder;
    setReminder(null);
    await dismissReminder(key).catch(() => undefined);
  }, [reminder]);

  return { reminder, bounce, snooze, dismiss };
}
