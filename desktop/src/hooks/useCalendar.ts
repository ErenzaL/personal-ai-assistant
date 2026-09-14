import { useCallback, useEffect, useRef, useState } from "react";
import { getCalendarAuthorization, listCalendars, requestCalendarAccess } from "../services/calendar";
import type { AuthorizationStatus, CalendarError, CalendarInfo } from "../types/calendar";

/**
 * Calendar permission state. Reads the current status on mount, which never
 * prompts, and exposes a request that does (once).
 */
export function useCalendar(enabled: boolean) {
  const [status, setStatus] = useState<AuthorizationStatus | null>(null);
  const [calendars, setCalendars] = useState<CalendarInfo[]>([]);
  const [canRequest, setCanRequest] = useState(false);
  const [isBusy, setIsBusy] = useState(false);
  const [error, setError] = useState<CalendarError | null>(null);
  const mounted = useRef(true);

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);

  /** Calendars are only fetched once access is granted. */
  const loadCalendars = useCallback(async (granted: boolean) => {
    if (!granted) {
      setCalendars([]);
      return;
    }
    try {
      const list = await listCalendars();
      if (mounted.current) setCalendars(list);
    } catch (err) {
      if (mounted.current) setError(err as CalendarError);
    }
  }, []);

  const refresh = useCallback(async () => {
    try {
      const auth = await getCalendarAuthorization();
      if (!mounted.current) return;
      setStatus(auth.status);
      setCanRequest(auth.can_request);
      setError(null);
      await loadCalendars(auth.can_read);
    } catch (err) {
      if (mounted.current) setError(err as CalendarError);
    }
  }, [loadCalendars]);

  useEffect(() => {
    if (enabled) void refresh();
  }, [enabled, refresh]);

  /** Shows the macOS prompt the first time; afterwards returns the answer. */
  const requestAccess = useCallback(async () => {
    setIsBusy(true);
    setError(null);
    try {
      const auth = await requestCalendarAccess();
      if (!mounted.current) return;
      setStatus(auth.status);
      setCanRequest(auth.can_request);
      await loadCalendars(auth.can_read);
    } catch (err) {
      if (mounted.current) setError(err as CalendarError);
    } finally {
      if (mounted.current) setIsBusy(false);
    }
  }, [loadCalendars]);

  return { status, calendars, canRequest, isBusy, error, requestAccess, refresh };
}
