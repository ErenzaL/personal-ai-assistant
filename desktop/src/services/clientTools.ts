/**
 * Tools the assistant can call that must run here rather than on the backend.
 *
 * Calendar access lives in the macOS layer, so the backend dispatches
 * `calendar.read` to this app; we execute it through Tauri and post the
 * structured result back. The same JSON envelope the backend uses is
 * reproduced here, so a failure is reported honestly rather than as silence.
 */
import {
  getCalendarAuthorization,
  isCalendarError,
  listCalendars,
  listEvents,
  requestCalendarAccess,
} from "./calendar";
import { buildEventChanges, buildProposal, findEvent, findEventById } from "./eventPlanning";
import type { CalendarEvent, EventMutationProposal, EventProposal } from "../types/calendar";

export const CALENDAR_READ = "calendar.read";
export const CALENDAR_PROPOSE = "calendar.propose_event";
export const CALENDAR_UPDATE = "calendar.update_event";
export const CALENDAR_DELETE = "calendar.delete_event";

export interface ToolEnvelope {
  ok: boolean;
  tool: string;
  data?: Record<string, unknown>;
  error?: { code: string; message: string };
}

/**
 * Make sure the calendar can be read, asking macOS on first use so that the
 * question which needs it is also what triggers the permission prompt.
 * Returns a structured error when access is missing; never throws.
 */
async function ensureAccess(): Promise<{ code: string; message: string } | null> {
  try {
    let auth = await getCalendarAuthorization();
    if (!auth.can_read && auth.can_request) auth = await requestCalendarAccess();
    if (auth.can_read) return null;
    return {
      code: "not_authorized",
      message:
        auth.status === "not_determined"
          ? "Calendar access has not been granted yet. It can be allowed from Settings → Calendar."
          : "Calendar access is turned off for this app. It can be turned on in System Settings → Privacy & Security → Calendars.",
    };
  } catch (error) {
    return isCalendarError(error)
      ? { code: error.code, message: error.message }
      : { code: "unavailable", message: "The calendar could not be reached." };
  }
}

/** True when the backend asked for a tool this app knows how to run. */
export function canRun(name: string): boolean {
  return name === CALENDAR_READ || name === CALENDAR_PROPOSE;
}

/** True for the two tools that find and propose a change to an EXISTING
 *  event, handled by `useChat.ts` the same way `CALENDAR_PROPOSE` already is
 *  (a dedicated branch, not the generic `runClientTool` dispatch). */
export function isCalendarMutation(name: string): boolean {
  return name === CALENDAR_UPDATE || name === CALENDAR_DELETE;
}

/**
 * Prepare an event for confirmation. Reads the calendar to spot clashes but
 * writes nothing: only the Confirm button creates anything.
 */
export async function proposeEvent(
  args: Record<string, unknown>,
  preferredCalendarId: string | null,
): Promise<{ proposal: EventProposal } | { error: string }> {
  const title = typeof args.title === "string" ? args.title : "";
  const start = typeof args.start === "string" ? args.start : "";
  if (!title || !start) return { error: "I couldn't tell what to add, or when." };
  const denied = await ensureAccess();
  if (denied) return { error: denied.message };
  try {
    const proposal = await buildProposal(
      {
        title,
        start,
        end: typeof args.end === "string" ? args.end : null,
        duration_minutes: typeof args.duration_minutes === "number" ? args.duration_minutes : null,
        calendar_name: typeof args.calendar_name === "string" ? args.calendar_name : null,
        location: typeof args.location === "string" ? args.location : null,
        notes: typeof args.notes === "string" ? args.notes : null,
      },
      preferredCalendarId,
    );
    return { proposal };
  } catch (error) {
    const message = isCalendarError(error)
      ? error.message
      : error instanceof Error
        ? error.message
        : "I couldn't prepare that event.";
    return { error: message };
  }
}

/**
 * Find the existing event a change/deletion refers to.
 *
 * Resolution order: a remembered id when the wording names no event (a bare
 * "it"/"that meeting" follow-up -- read live, never trusted as still
 * accurate); otherwise a fresh text match within the given window. Ambiguous
 * candidates are never guessed at, and a stale/deleted remembered id falls
 * back to a fresh search rather than failing outright.
 */
async function resolveEvent(
  matchText: string,
  searchStart: string,
  searchEnd: string,
  lastFocusedEventId: string | null,
  hiddenCalendarIds: string[],
): Promise<{ event: CalendarEvent } | { ambiguous: CalendarEvent[] } | { error: string }> {
  const visibleIds = await visibleCalendarIds(hiddenCalendarIds);
  if (!matchText.trim() && lastFocusedEventId) {
    const byId = await findEventById(lastFocusedEventId);
    if (byId.kind === "found") return { event: byId.event };
  }
  const match = await findEvent(matchText, searchStart, searchEnd, visibleIds);
  if (match.kind === "found") return { event: match.event };
  if (match.kind === "ambiguous") return { ambiguous: match.candidates };
  return {
    error: matchText.trim()
      ? `I couldn't find "${matchText.trim()}" in that time range.`
      : "I couldn't tell which event you meant.",
  };
}

/** Prepare a change to an EXISTING event for confirmation. Writes nothing:
 *  only confirming (a click, or a typed "yes") calls `updateEvent`. */
export async function proposeEventUpdate(
  args: Record<string, unknown>,
  lastFocusedEventId: string | null,
  hiddenCalendarIds: string[] = [],
): Promise<{ proposal: EventMutationProposal } | { ambiguous: CalendarEvent[] } | { error: string }> {
  const denied = await ensureAccess();
  if (denied) return { error: denied.message };

  const matchText = typeof args.match === "string" ? args.match : "";
  const searchStart = typeof args.search_start === "string" ? args.search_start : "";
  const searchEnd = typeof args.search_end === "string" ? args.search_end : "";
  if (!searchStart || !searchEnd) return { error: "I wasn't given a time range to search." };

  const found = await resolveEvent(matchText, searchStart, searchEnd, lastFocusedEventId, hiddenCalendarIds);
  if ("error" in found) return found;
  if ("ambiguous" in found) return found;

  try {
    const calendars = await listCalendars();
    const changes = buildEventChanges(
      found.event,
      {
        newTitle: typeof args.new_title === "string" ? args.new_title : undefined,
        newDate: typeof args.new_date === "string" ? args.new_date : undefined,
        newTime: typeof args.new_time === "string" ? args.new_time : undefined,
        shiftMinutes: typeof args.shift_minutes === "number" ? args.shift_minutes : undefined,
        newLocation: typeof args.new_location === "string" ? args.new_location : undefined,
        newNotes: typeof args.new_notes === "string" ? args.new_notes : undefined,
        newCalendarName: typeof args.new_calendar_name === "string" ? args.new_calendar_name : undefined,
      },
      calendars,
    );
    if (Object.keys(changes).length === 0) return { error: "I couldn't tell what to change." };
    return {
      proposal: {
        kind: "update",
        eventId: found.event.id ?? "",
        title: found.event.title,
        calendarTitle: found.event.calendar_title,
        before: found.event,
        changes,
      },
    };
  } catch (error) {
    return { error: isCalendarError(error) ? error.message : "I couldn't prepare that change." };
  }
}

/** Prepare deleting an EXISTING event for confirmation. Writes nothing:
 *  only confirming calls `deleteEvent`. */
export async function proposeEventDelete(
  args: Record<string, unknown>,
  lastFocusedEventId: string | null,
  hiddenCalendarIds: string[] = [],
): Promise<{ proposal: EventMutationProposal } | { ambiguous: CalendarEvent[] } | { error: string }> {
  const denied = await ensureAccess();
  if (denied) return { error: denied.message };

  const matchText = typeof args.match === "string" ? args.match : "";
  const searchStart = typeof args.search_start === "string" ? args.search_start : "";
  const searchEnd = typeof args.search_end === "string" ? args.search_end : "";
  if (!searchStart || !searchEnd) return { error: "I wasn't given a time range to search." };

  const found = await resolveEvent(matchText, searchStart, searchEnd, lastFocusedEventId, hiddenCalendarIds);
  if ("error" in found) return found;
  if ("ambiguous" in found) return found;

  return {
    proposal: {
      kind: "delete",
      eventId: found.event.id ?? "",
      title: found.event.title,
      calendarTitle: found.event.calendar_title,
      before: found.event,
    },
  };
}

/**
 * Run one client-side tool. Never throws: a failure becomes an `ok: false`
 * envelope so the assistant can explain it instead of inventing an answer.
 */
export async function runClientTool(
  name: string,
  args: Record<string, unknown>,
  hiddenCalendarIds: string[] = [],
): Promise<ToolEnvelope> {
  if (name !== CALENDAR_READ) {
    return { ok: false, tool: name, error: { code: "unknown_tool", message: `No client tool ${name}.` } };
  }

  const start = typeof args.start === "string" ? args.start : "";
  const end = typeof args.end === "string" ? args.end : "";
  if (!start || !end) {
    return {
      ok: false,
      tool: name,
      error: { code: "invalid_arguments", message: "The calendar range was incomplete." },
    };
  }

  const denied = await ensureAccess();
  if (denied) return { ok: false, tool: name, error: denied };

  try {
    // Calendars turned off in Settings are excluded at the source, by
    // narrowing which calendars EventKit is asked to search -- not by
    // filtering the results after the fact.
    const visibleIds = await visibleCalendarIds(hiddenCalendarIds);
    const events = await listEvents(start, end, visibleIds);
    return { ok: true, tool: name, data: { range: { start, end }, events } };
  } catch (error) {
    const detail = isCalendarError(error)
      ? error
      : { code: "unavailable", message: "The calendar could not be read." };
    return { ok: false, tool: name, error: detail };
  }
}

/**
 * All calendar ids except the hidden ones, or `undefined` when nothing is
 * hidden (so `listEvents` searches every calendar, its normal default).
 * Best-effort: if the calendar list can't be read here, `listEvents` itself
 * will surface that failure right after.
 */
async function visibleCalendarIds(hiddenCalendarIds: string[]): Promise<string[] | undefined> {
  if (hiddenCalendarIds.length === 0) return undefined;
  try {
    const all = await listCalendars();
    return all.map((c) => c.id).filter((id) => !hiddenCalendarIds.includes(id));
  } catch {
    return undefined;
  }
}
