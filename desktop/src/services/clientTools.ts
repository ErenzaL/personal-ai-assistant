/**
 * Tools the assistant can call that must run here rather than on the backend.
 *
 * Calendar access lives in the macOS layer, so the backend dispatches
 * `calendar.read` to this app; we execute it through Tauri and post the
 * structured result back. The same JSON envelope the backend uses is
 * reproduced here, so a failure is reported honestly rather than as silence.
 */
import { getCalendarAuthorization, isCalendarError, listEvents, requestCalendarAccess } from "./calendar";
import { buildProposal } from "./eventPlanning";
import type { EventProposal } from "../types/calendar";

export const CALENDAR_READ = "calendar.read";
export const CALENDAR_PROPOSE = "calendar.propose_event";

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
 * Run one client-side tool. Never throws: a failure becomes an `ok: false`
 * envelope so the assistant can explain it instead of inventing an answer.
 */
export async function runClientTool(
  name: string,
  args: Record<string, unknown>,
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
    const events = await listEvents(start, end);
    return { ok: true, tool: name, data: { range: { start, end }, events } };
  } catch (error) {
    const detail = isCalendarError(error)
      ? error
      : { code: "unavailable", message: "The calendar could not be read." };
    return { ok: false, tool: name, error: detail };
  }
}
