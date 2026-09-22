/**
 * Settings the native layer enforces, and state only macOS knows.
 *
 * Ordinary settings are stored by the backend; the ones that change native
 * behaviour (edge activation, reminder timing, notifications) are pushed here
 * whenever they load or change. Launch-at-login is never stored: it is read
 * from and written to macOS itself, like the calendar permission.
 */
import { invoke } from "@tauri-apps/api/core";
import { getVersion } from "@tauri-apps/api/app";

export interface LoginItem {
  /** False outside an app bundle, e.g. the bare development binary. */
  supported: boolean;
  enabled: boolean;
  /** Registered, but still needs approval in System Settings. */
  requires_approval: boolean;
}

const NO_LOGIN_ITEM: LoginItem = { supported: false, enabled: false, requires_approval: false };

function inTauri(): boolean {
  return "__TAURI_INTERNALS__" in window;
}

export async function applyNativeSettings(settings: {
  edgeActivation: boolean;
  reminderMinutes: number;
  calendarNotifications: boolean;
}): Promise<void> {
  if (!inTauri()) return;
  await invoke("apply_settings", {
    edgeActivation: settings.edgeActivation,
    reminderMinutes: settings.reminderMinutes,
    calendarNotifications: settings.calendarNotifications,
  });
}

export async function getLoginItem(): Promise<LoginItem> {
  if (!inTauri()) return NO_LOGIN_ITEM;
  return invoke<LoginItem>("login_item_status");
}

export async function setLoginItem(enabled: boolean): Promise<LoginItem> {
  if (!inTauri()) return NO_LOGIN_ITEM;
  return invoke<LoginItem>("set_login_item", { enabled });
}

/** The packaged app's version (e.g. "1.0.0"), for the Settings footer. Null
 *  outside the desktop app, where there is no bundle to read it from. */
export async function getAppVersion(): Promise<string | null> {
  if (!inTauri()) return null;
  try {
    return await getVersion();
  } catch {
    return null;
  }
}
