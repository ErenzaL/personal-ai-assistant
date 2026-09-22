/**
 * Calendar permission, straight to the native layer.
 *
 * These call Tauri commands that talk to Apple's EventKit. The Python backend
 * is not involved, and no credentials exist to store: macOS owns the
 * permission and the Calendar database owns the accounts.
 */
import { invoke } from "@tauri-apps/api/core";
import type {
  CalendarAuthorization,
  CalendarError,
  CalendarEvent,
  CalendarInfo,
  EventChanges,
} from "../types/calendar";

/** True when running inside the Tauri webview (false in a plain browser tab). */
function inTauri(): boolean {
  return "__TAURI_INTERNALS__" in window;
}

/** Commands reject with the serialized `CalendarError`; anything else is normalised. */
function toCalendarError(error: unknown): CalendarError {
  if (error && typeof error === "object" && "code" in error && "message" in error) {
    return error as CalendarError;
  }
  return { code: "unavailable", message: "The calendar service could not be reached." };
}

const UNSUPPORTED: CalendarError = {
  code: "unsupported",
  message: "Calendar access is only available in the desktop app.",
};

/** Current permission. Never shows a prompt. */
export async function getCalendarAuthorization(): Promise<CalendarAuthorization> {
  if (!inTauri()) throw UNSUPPORTED;
  try {
    return await invoke<CalendarAuthorization>("calendar_get_authorization_status");
  } catch (error) {
    throw toCalendarError(error);
  }
}

/**
 * Ask macOS for calendar access.
 *
 * The system prompt appears only the first time. Once the user has answered,
 * this returns the standing answer immediately and only System Settings can
 * change it.
 */
export async function requestCalendarAccess(): Promise<CalendarAuthorization> {
  if (!inTauri()) throw UNSUPPORTED;
  try {
    return await invoke<CalendarAuthorization>("calendar_request_access");
  } catch (error) {
    throw toCalendarError(error);
  }
}

/**
 * Every event calendar macOS knows about, from all configured accounts.
 * Requires access; rejects with `not_authorized` otherwise.
 */
export async function listCalendars(): Promise<CalendarInfo[]> {
  if (!inTauri()) throw UNSUPPORTED;
  try {
    return await invoke<CalendarInfo[]>("calendar_list_calendars");
  } catch (error) {
    throw toCalendarError(error);
  }
}

/**
 * Events overlapping [start, end), oldest first. Dates are ISO 8601; without
 * an offset they are read as local time. Recurring events come back as
 * individual occurrences.
 */
export async function listEvents(
  start: string,
  end: string,
  calendarIds?: string[],
): Promise<CalendarEvent[]> {
  if (!inTauri()) throw UNSUPPORTED;
  try {
    return await invoke<CalendarEvent[]>("calendar_list_events", {
      startDatetime: start,
      endDatetime: end,
      calendarIds: calendarIds ?? null,
    });
  } catch (error) {
    throw toCalendarError(error);
  }
}

/** Write one event. Only ever called after the user presses Confirm. */
export async function createEvent(input: {
  title: string;
  start: string;
  end: string;
  calendarId?: string;
  location?: string;
  notes?: string;
}): Promise<CalendarEvent> {
  if (!inTauri()) throw UNSUPPORTED;
  try {
    return await invoke<CalendarEvent>("calendar_create_event", {
      event: {
        title: input.title,
        start: input.start,
        end: input.end,
        calendar_id: input.calendarId ?? null,
        location: input.location ?? null,
        notes: input.notes ?? null,
      },
    });
  } catch (error) {
    throw toCalendarError(error);
  }
}

/** One event by id, exactly as EventKit currently has it. */
export async function getEvent(id: string): Promise<CalendarEvent> {
  if (!inTauri()) throw UNSUPPORTED;
  try {
    return await invoke<CalendarEvent>("calendar_get_event", { eventId: id });
  } catch (error) {
    throw toCalendarError(error);
  }
}

/** Change only the given fields of an existing event. Only ever called
 *  after the user confirms a proposed change. */
export async function updateEvent(id: string, changes: EventChanges): Promise<CalendarEvent> {
  if (!inTauri()) throw UNSUPPORTED;
  try {
    return await invoke<CalendarEvent>("calendar_update_event", {
      eventId: id,
      changes: {
        title: changes.title ?? null,
        start: changes.start ?? null,
        end: changes.end ?? null,
        calendar_id: changes.calendarId ?? null,
        location: changes.location ?? null,
        notes: changes.notes ?? null,
      },
    });
  } catch (error) {
    throw toCalendarError(error);
  }
}

/** Remove an event, returning what it was immediately before removal. Only
 *  ever called after the user confirms. */
export async function deleteEvent(id: string): Promise<CalendarEvent> {
  if (!inTauri()) throw UNSUPPORTED;
  try {
    return await invoke<CalendarEvent>("calendar_delete_event", { eventId: id });
  } catch (error) {
    throw toCalendarError(error);
  }
}

/** True for the structured error the native calendar layer throws. */
export function isCalendarError(value: unknown): value is CalendarError {
  return (
    !!value &&
    typeof value === "object" &&
    typeof (value as CalendarError).code === "string" &&
    typeof (value as CalendarError).message === "string"
  );
}

/** Open System Settings at Privacy & Security > Calendars. */
export async function openCalendarSettings(): Promise<void> {
  if (!inTauri()) return;
  try {
    await invoke("calendar_open_settings");
  } catch (error) {
    throw toCalendarError(error);
  }
}
