/**
 * Turning a parsed request into a concrete proposal.
 *
 * The model supplies words ("tomorrow at 7", "for one hour"); everything that
 * has to be exact -- the end time, which calendar, whether it clashes -- is
 * worked out here in code, so the same request always yields the same event.
 */
import { getEvent, listCalendars, listEvents } from "./calendar";
import { DEFAULT_DURATION_MINUTES } from "../types/calendar";
import type { CalendarEvent, CalendarInfo, EventChanges, EventProposal } from "../types/calendar";

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

// --- finding an EXISTING event (update / reschedule / delete) --------------
//
// EventKit only exists on this side of the app, so unlike tasks (which the
// backend can search itself) an existing event has to be found here. This
// mirrors the term-overlap matcher in `backend/app/services/tools/tasks.py`
// (`_terms`/`_stem`/tie-detection) in spirit, not literally -- the two can't
// share code across the Python/TypeScript boundary, but the same
// unique-match / tied-match-is-ambiguous / no-match-is-not-found trichotomy
// applies, so "find the thing the user means, never guess" feels consistent
// in both places.

const STOPWORDS = new Set([
  "the", "a", "an", "my", "me", "i", "to", "of", "and", "or", "in", "on", "for", "with", "that",
  "this", "it", "is", "are", "do", "you", "your", "please", "at", "from", "meeting", "event",
  "appointment", "calendar",
]);

function stem(word: string): string {
  const suffixes: [string, string][] = [
    ["ies", "y"],
    ["ing", ""],
    ["ed", ""],
    ["es", ""],
    ["s", ""],
  ];
  for (const [suffix, replacement] of suffixes) {
    if (word.endsWith(suffix) && word.length - suffix.length >= 3 && !word.endsWith("ss")) {
      return word.slice(0, -suffix.length) + replacement;
    }
  }
  return word;
}

function terms(text: string): string[] {
  const pieces = text
    .toLowerCase()
    .split(/[^\w]+/)
    .filter((piece) => piece.length >= 2 && !STOPWORDS.has(piece))
    .map(stem);
  return [...new Set(pieces)];
}

export type EventMatch =
  | { kind: "found"; event: CalendarEvent }
  | { kind: "ambiguous"; candidates: CalendarEvent[] }
  | { kind: "not_found" };

/** Search events in [searchStart, searchEnd) for the one `matchText` means.
 *  Empty `matchText` always misses -- a bare "it" is resolved by the caller
 *  via `findEventById` using a remembered id, never by matching here. */
export async function findEvent(
  matchText: string,
  searchStart: string,
  searchEnd: string,
  visibleCalendarIds?: string[],
): Promise<EventMatch> {
  const query = terms(matchText);
  if (query.length === 0) return { kind: "not_found" };

  const events = await listEvents(searchStart, searchEnd, visibleCalendarIds);
  const scored = events
    .map((event) => ({ event, score: query.filter((t) => terms(event.title).includes(t)).length }))
    .filter((entry) => entry.score > 0);
  if (scored.length === 0) return { kind: "not_found" };

  scored.sort((a, b) => b.score - a.score || a.event.start_unix - b.event.start_unix);
  const best = scored[0].score;
  const tied = scored.filter((entry) => entry.score === best);
  if (tied.length > 1) return { kind: "ambiguous", candidates: tied.map((entry) => entry.event) };
  return { kind: "found", event: tied[0].event };
}

/** Resolve "it"/"that meeting" from a remembered id, read live so a stale
 *  reference (deleted since, or moved) is never silently trusted. */
export async function findEventById(id: string): Promise<EventMatch> {
  try {
    return { kind: "found", event: await getEvent(id) };
  } catch {
    return { kind: "not_found" };
  }
}

/** What the model resolved about a change, before it's merged with the
 *  event's own current fields. All optional: only what the user actually
 *  asked to change. */
export interface UpdateRequest {
  newTitle?: string;
  /** YYYY-MM-DD. Given without newTime, the original time is kept. */
  newDate?: string;
  /** HH:MM, 24-hour. Given without newDate, the original date is kept. */
  newTime?: string;
  /** A relative move ("one hour later", "30 minutes earlier"); takes
   *  precedence over newDate/newTime when both are somehow present. */
  shiftMinutes?: number;
  newLocation?: string;
  newNotes?: string;
  newCalendarName?: string;
}

/**
 * Merge a requested change with the event's own current fields -- never the
 * other way around. Untouched fields (per spec: title/date/duration/
 * location/notes/calendar the user didn't mention) come from `event`, read
 * live moments earlier by the caller, not from any earlier snapshot.
 */
export function buildEventChanges(
  event: CalendarEvent,
  request: UpdateRequest,
  calendars: CalendarInfo[],
): EventChanges {
  const changes: EventChanges = {};
  if (request.newTitle?.trim()) changes.title = request.newTitle.trim();
  if (request.newLocation !== undefined) changes.location = request.newLocation.trim();
  if (request.newNotes !== undefined) changes.notes = request.newNotes.trim();
  if (request.newCalendarName) {
    const target = pickCalendar(calendars, request.newCalendarName, null);
    if (target) changes.calendarId = target.id;
  }

  const currentStart = parseLocal(event.start);
  const currentEnd = parseLocal(event.end);
  const touchesTime = request.shiftMinutes !== undefined || request.newDate || request.newTime;
  if (currentStart && currentEnd && touchesTime) {
    // The event's own current duration, never recomputed by the model.
    const durationMs = currentEnd.getTime() - currentStart.getTime();
    const newStart = new Date(currentStart);

    if (request.shiftMinutes !== undefined) {
      newStart.setMinutes(newStart.getMinutes() + request.shiftMinutes);
    } else {
      if (request.newDate) {
        const [y, m, d] = request.newDate.split("-").map(Number);
        if (y && m && d) newStart.setFullYear(y, m - 1, d);
      }
      if (request.newTime) {
        const [h, min] = request.newTime.split(":").map(Number);
        if (Number.isFinite(h) && Number.isFinite(min)) newStart.setHours(h, min, 0, 0);
      }
    }

    changes.start = toLocalIso(newStart);
    changes.end = toLocalIso(new Date(newStart.getTime() + durationMs));
  }

  return changes;
}
