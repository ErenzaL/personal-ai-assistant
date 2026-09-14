import { invoke } from "@tauri-apps/api/core";

/** True when running inside the Tauri webview (false in a plain browser tab). */
function inTauri(): boolean {
  return "__TAURI_INTERNALS__" in window;
}

/**
 * Tell the native side to resize/anchor the window and pin it visible while
 * chat is open. Outside Tauri (e.g. `npm run dev` in a browser) this is a no-op
 * so the layout can still be developed and inspected.
 */
export async function setChatOpen(open: boolean): Promise<void> {
  if (!inTauri()) return;
  await invoke("set_chat_open", { open });
}
