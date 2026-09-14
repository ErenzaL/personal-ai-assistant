/**
 * The reminder popup's link to the native reminder service.
 *
 * Scheduling, notifications and state all live in Rust; this file only
 * receives "a reminder fired" and sends back snooze or dismiss for that same
 * reminder, identified by its key.
 */
import { invoke } from "@tauri-apps/api/core";
import { listen, type UnlistenFn } from "@tauri-apps/api/event";

export interface ReminderView {
  key: string;
  title: string;
  /** Event start, ISO 8601 with the local offset. */
  start: string;
  start_unix: number;
  minutes_until: number;
  snoozed_until: number | null;
}

function inTauri(): boolean {
  return "__TAURI_INTERNALS__" in window;
}

/** Fires for a new alert, and again after a snooze elapses. */
export async function onReminderFired(handler: (reminder: ReminderView) => void): Promise<UnlistenFn> {
  if (!inTauri()) return () => {};
  return listen<ReminderView>("reminder:fired", (event) => handler(event.payload));
}

/** The reminder whose popup should be showing now, e.g. after a restart. */
export async function activeReminder(): Promise<ReminderView | null> {
  if (!inTauri()) return null;
  return (await invoke<ReminderView | null>("reminder_active")) ?? null;
}

export async function snoozeReminder(key: string, minutes: number): Promise<void> {
  if (!inTauri()) return;
  await invoke("reminder_snooze", { key, minutes });
}

export async function dismissReminder(key: string): Promise<void> {
  if (!inTauri()) return;
  await invoke("reminder_dismiss", { key });
}
