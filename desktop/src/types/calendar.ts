/** Mirrors `src-tauri/src/calendar/types.rs`. */

export type AuthorizationStatus =
  | "not_determined"
  | "restricted"
  | "denied"
  | "full_access"
  | "write_only";

export interface CalendarAuthorization {
  status: AuthorizationStatus;
  /** True once the app may read events. */
  can_read: boolean;
  /** True while asking again could still show the system prompt. */
  can_request: boolean;
}

/** EventKit's own source classification, reported as-is. */
export type SourceType =
  | "local"
  | "exchange"
  | "cal_dav"
  | "mobile_me"
  | "subscribed"
  | "birthdays";

/** Mirrors `CalendarInfo` in the Rust layer. */
export interface CalendarInfo {
  /** EventKit's stable identifier, preserved verbatim. */
  id: string;
  title: string;
  /** The account macOS groups it under ("iCloud", "Google"), or null. */
  source_name: string | null;
  source_type: SourceType | null;
  allows_modifications: boolean;
  color: string | null;
  /** True for the calendar macOS itself uses for new events. */
  is_default: boolean;
}

/** One occurrence, already in local time. Mirrors the Rust `CalendarEvent`. */
export interface CalendarEvent {
  id: string | null;
  title: string;
  /** ISO 8601 with the local offset. For all-day events only the date matters. */
  start: string;
  end: string;
  /** The same instants as unix seconds. */
  start_unix: number;
  end_unix: number;
  all_day: boolean;
  calendar_id: string;
  calendar_title: string;
  location: string | null;
  notes: string | null;
}

export type CalendarErrorCode =
  | "unsupported"
  | "unavailable"
  | "request_failed"
  | "timeout"
  /** macOS declined to show the prompt (app started from a terminal). */
  | "prompt_unavailable"
  /** Access has not been granted, so there is nothing to read. */
  | "not_authorized"
  /** A start/end date could not be read, or the range is backwards. */
  | "invalid_range"
  /** A command argument was missing, too long, or otherwise unusable. */
  | "invalid_input";

export interface CalendarError {
  code: CalendarErrorCode;
  message: string;
}

/** Wording for the Settings row. */
export const STATUS_LABEL: Record<AuthorizationStatus, string> = {
  not_determined: "Not connected",
  full_access: "Allowed",
  write_only: "Write only",
  denied: "Denied",
  restricted: "Restricted",
};

/** Where the user has to go when macOS will no longer show the prompt. */
export const SYSTEM_SETTINGS_PATH = "System Settings → Privacy & Security → Calendars";

/** Calendars with no source are listed last under this heading. */
export const UNKNOWN_SOURCE = "Other";

/** A new event the user has not confirmed yet. Nothing is written until they do. */
export interface EventProposal {
  title: string;
  /** Local ISO 8601 without an offset, e.g. 2026-09-15T19:00:00. */
  start: string;
  end: string;
  calendarId: string;
  calendarTitle: string;
  location?: string;
  notes?: string;
  /** Existing events that overlap. A warning only; it never blocks. */
  conflicts: CalendarEvent[];
}

/** Used when the user gives a start time but no duration. */
export const DEFAULT_DURATION_MINUTES = 60;
