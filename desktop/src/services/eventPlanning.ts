/**
 * Turning a parsed request into a concrete proposal.
 *
 * The model supplies words ("tomorrow at 7", "for one hour"); everything that
 * has to be exact -- the end time, which calendar, whether it clashes -- is
 * worked out here in code, so the same request always yields the same event.
 */
import { listCalendars, listEvents } from "./calendar";
import { DEFAULT_DURATION_MINUTES } from "../types/calendar";
import type { CalendarEvent, CalendarInfo, EventProposal } from "../types/calendar";

/** `2026-09-15T19:00:00`, the shape the native layer reads as local time. */
export function toLocalIso(date: Date): string {
  const pad = (n: number) => String(n).padStart(2, "0");
  return (
    `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}` +
    `T${pad(date.getHours())}:${pad(date.getMinutes())}:${pad(date.getSeconds())}`
  );
}

/** Parses local ISO (no offset) as local time, which is what the spec says. */
export function parseLocal(iso: string): Date | null {
  const date = new Date(iso);
  return Number.isNaN(date.getTime()) ? null : date;
}

/** Adds minutes across DST correctly by going through the Date arithmetic. */
export function addMinutes(iso: string, minutes: number): string | null {
  const date = parseLocal(iso);
  if (!date) return null;
  date.setMinutes(date.getMinutes() + minutes);
  return toLocalIso(date);
}

/**
 * Which calendar to put this on.
 *
 * A name the user said wins, then their configured default, then the calendar
 * macOS uses for new events, then simply the first writable one. Read-only
 * calendars (holidays, subscriptions) are never chosen.
 */
export function pickCalendar(
  calendars: CalendarInfo[],
  named: string | undefined,
  preferredId: string | null,
): CalendarInfo | null {
  const writable = calendars.filter((c) => c.allows_modifications);
  if (writable.length === 0) return null;

  if (named) {
    const needle = named.trim().toLowerCase();
    const match =
      writable.find((c) => c.title.toLowerCase() === needle) ??
      writable.find((c) => c.title.toLowerCase().includes(needle)) ??
      writable.find((c) => (c.source_name ?? "").toLowerCase().includes(needle));
    if (match) return match;
  }

  return (
    writable.find((c) => c.id === preferredId) ??
    writable.find((c) => c.is_default) ??
    writable[0]
  );
}

/** Existing events that genuinely overlap. All-day entries are not clashes. */
export function findConflicts(existing: CalendarEvent[], start: string, end: string): CalendarEvent[] {
  const from = parseLocal(start)?.getTime();
  const to = parseLocal(end)?.getTime();
  if (from === undefined || to === undefined) return [];
  return existing.filter((event) => {
    if (event.all_day) return false;
    const s = new Date(event.start).getTime();
    const e = new Date(event.end).getTime();
    return Number.isFinite(s) && Number.isFinite(e) && s < to && e > from;
  });
}

export interface ProposalInput {
  title: string;
  start: string;
  end?: string | null;
  duration_minutes?: number | null;
  calendar_name?: string | null;
  location?: string | null;
  notes?: string | null;
}

/**
 * Build a proposal. Reads the calendar to look for clashes but writes nothing.
 */
export async function buildProposal(
  input: ProposalInput,
  preferredCalendarId: string | null,
): Promise<EventProposal> {
  const start = input.start.trim();
  if (!parseLocal(start)) throw new Error("I couldn't work out the start time.");

  // The end is always computed here, never taken from the model's arithmetic.
  const end =
    (input.end && parseLocal(input.end) ? input.end : null) ??
    addMinutes(start, input.duration_minutes ?? DEFAULT_DURATION_MINUTES);
  if (!end) throw new Error("I couldn't work out the end time.");

  const calendars = await listCalendars();
  const calendar = pickCalendar(calendars, input.calendar_name ?? undefined, preferredCalendarId);
  if (!calendar) throw new Error("None of your calendars accept new events.");

  const existing = await listEvents(start, end, [calendar.id]).catch(() => []);

  return {
    title: input.title.trim(),
    start,
    end,
    calendarId: calendar.id,
    calendarTitle: calendar.title,
    location: input.location?.trim() || undefined,
    notes: input.notes?.trim() || undefined,
    conflicts: findConflicts(existing, start, end),
  };
}
