/**
 * HTTP client for the FastAPI backend. Components never build URLs or call
 * `fetch` directly; they use the typed functions at the bottom of this file.
 */
import { invoke } from "@tauri-apps/api/core";
import { API_BASE_URL, API_TIMEOUT_MS } from "../config";
import type { AssistantAction } from "../types/chat";

let baseUrl: Promise<string> | null = null;

/**
 * Where the backend answers. The desktop app starts the backend itself and
 * moves to another port if 8000 is taken, so ask it once; outside Tauri
 * (a plain browser tab) fall back to the configured default.
 */
function apiBase(): Promise<string> {
  if (!baseUrl) {
    baseUrl =
      "__TAURI_INTERNALS__" in window
        ? invoke<string>("backend_url").catch(() => API_BASE_URL)
        : Promise.resolve(API_BASE_URL);
  }
  return baseUrl;
}

export type ApiErrorKind =
  | "offline" // could not connect at all
  | "timeout" // no response headers within API_TIMEOUT_MS
  | "http" // server answered with an error status or an in-band error event
  | "invalid" // server answered, but not in the expected shape
  | "interrupted" // stream ended before the server said it was done
  | "aborted"; // we cancelled it ourselves (panel closed)

export class ApiError extends Error {
  readonly kind: ApiErrorKind;
  readonly status?: number;
  /** Machine-readable code from the backend's `detail.code`, when present. */
  readonly code?: string;
  /** Human-readable message from the backend's `detail.message`, when present. */
  readonly serverMessage?: string;

  constructor(
    kind: ApiErrorKind,
    message: string,
    extra: { status?: number; code?: string; serverMessage?: string } = {},
  ) {
    super(message);
    this.name = "ApiError";
    this.kind = kind;
    this.status = extra.status;
    this.code = extra.code;
    this.serverMessage = extra.serverMessage;
  }
}

/** Human-readable explanation, safe to show in the UI. */
export function describeApiError(error: unknown): string {
  if (error instanceof ApiError) {
    switch (error.kind) {
      case "offline":
        return "Dully's local service isn't answering. It starts with the app; give it a moment or restart Dully.";
      case "timeout":
        return "The backend took too long to respond.";
      case "http":
        return error.serverMessage ?? `The backend returned an error (HTTP ${error.status}).`;
      case "invalid":
        return "The backend sent an unexpected response.";
      case "interrupted":
        return "The reply was cut off before it finished.";
      case "aborted":
        return "Cancelled.";
    }
  }
  return "Something went wrong talking to the backend.";
}

/** FastAPI error bodies: `{"detail": {"code", "message"}}` or `{"detail": "..."}`. */
async function readErrorDetail(response: Response): Promise<{ code?: string; message?: string }> {
  try {
    const body = (await response.json()) as { detail?: unknown };
    const detail = body.detail;
    if (typeof detail === "string") return { message: detail };
    if (detail && typeof detail === "object") {
      const d = detail as { code?: unknown; message?: unknown };
      return {
        code: typeof d.code === "string" ? d.code : undefined,
        message: typeof d.message === "string" ? d.message : undefined,
      };
    }
  } catch {
    // not JSON; fall through
  }
  return {};
}

type SendInit = Omit<RequestInit, "signal"> & { signal?: AbortSignal; timeoutMs?: number };

/**
 * `fetch` with connection-level error mapping and a timeout that covers the
 * wait for response headers only. Body streaming is the caller's business.
 * `timeoutMs` overrides the default for one call -- Gmail's connect request
 * blocks in the browser for as long as the backend's own OAuth window, far
 * longer than an ordinary request should ever wait.
 */
async function send(path: string, init: SendInit = {}): Promise<Response> {
  const controller = new AbortController();
  const timer = window.setTimeout(() => controller.abort(), init.timeoutMs ?? API_TIMEOUT_MS);
  const onOuterAbort = () => controller.abort();
  init.signal?.addEventListener("abort", onOuterAbort);

  try {
    const response = await fetch(`${await apiBase()}${path}`, {
      ...init,
      headers: { "Content-Type": "application/json", ...init.headers },
      signal: controller.signal,
    });
    if (!response.ok) {
      const detail = await readErrorDetail(response);
      throw new ApiError("http", `HTTP ${response.status}`, {
        status: response.status,
        code: detail.code,
        serverMessage: detail.message,
      });
    }
    return response;
  } catch (error) {
    if (error instanceof ApiError) throw error;
    // Nothing answered: the backend may have moved to another port (the app
    // restarts it if it goes away), so ask the app again next time.
    baseUrl = null;
    // fetch rejects (rather than resolving with a status) when the server is
    // unreachable, the connection is refused, CORS blocks it, or we aborted.
    if (init.signal?.aborted) throw new ApiError("aborted", "cancelled");
    if (error instanceof DOMException && error.name === "AbortError") {
      throw new ApiError("timeout", "request timed out");
    }
    throw new ApiError("offline", "backend unreachable");
  } finally {
    window.clearTimeout(timer);
    init.signal?.removeEventListener("abort", onOuterAbort);
  }
}

async function request<T>(path: string, init: SendInit = {}): Promise<T> {
  const response = await send(path, init);
  try {
    return (await response.json()) as T;
  } catch {
    throw new ApiError("invalid", "response was not JSON");
  }
}

// --- SSE parsing -------------------------------------------------------------

interface SseEvent {
  event: string;
  data: string;
}

/** Parse one SSE frame (the text between blank lines). */
function parseSseFrame(frame: string): SseEvent {
  let event = "message";
  const data: string[] = [];
  for (const line of frame.split("\n")) {
    if (line.startsWith("event:")) event = line.slice(6).trim();
    else if (line.startsWith("data:")) data.push(line.slice(5).trimStart());
  }
  return { event, data: data.join("\n") };
}

/** Yield SSE events from a streaming response body as they arrive. */
async function* readSse(body: ReadableStream<Uint8Array>): AsyncGenerator<SseEvent> {
  const reader = body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  try {
    for (;;) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      let end: number;
      while ((end = buffer.indexOf("\n\n")) !== -1) {
        const frame = buffer.slice(0, end);
        buffer = buffer.slice(end + 2);
        if (frame.trim()) yield parseSseFrame(frame);
      }
    }
  } finally {
    reader.releaseLock();
  }
}

// --- Types mirrored from the backend ----------------------------------------------

export interface ConversationDto {
  id: string;
  title: string | null;
  created_at: string;
  updated_at: string;
}

export interface MessageDto {
  id: string;
  conversation_id: string;
  role: "user" | "assistant" | "system";
  content: string;
  created_at: string;
}

export interface ConversationWithMessagesDto {
  conversation: ConversationDto;
  messages: MessageDto[];
}

export interface MemoryDto {
  id: string;
  category: string;
  key: string;
  content: string;
  source: string;
  confidence: number;
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

export interface AssistantSettingsDto {
  assistant_name: string;
  response_style: string;
  available_styles: string[];
  default_calendar_id: string | null;
  reminder_minutes: number;
  calendar_notifications: boolean;
  edge_activation: boolean;
  memory_enabled: boolean;
  hidden_calendar_ids: string[];
}

// --- Endpoints ---------------------------------------------------------------

interface HealthResponse {
  status: string;
}

/** True when the backend answers GET /health with status "ok". Never throws. */
export async function checkHealth(): Promise<boolean> {
  try {
    const body = await request<HealthResponse>("/health");
    return body.status === "ok";
  } catch {
    return false;
  }
}

/** The conversation to show on open, with its recent messages. */
export function getCurrentConversation(): Promise<ConversationWithMessagesDto> {
  return request<ConversationWithMessagesDto>("/conversations/current");
}

/** Start a fresh conversation; it becomes the current one. */
/** Delete every conversation and message. The settings panel confirms first. */
export function clearConversations(): Promise<{ deleted: number }> {
  return request<{ deleted: number }>("/conversations", { method: "DELETE" });
}

export function createConversation(): Promise<ConversationDto> {
  return request<ConversationDto>("/conversations", { method: "POST" });
}

export interface ChatToolResult {
  name: string;
  result: Record<string, unknown>;
}

export interface ChatTurnRequest {
  message: string;
  conversationId: string;
  /** On retry: the already-saved user message, so the backend doesn't save it twice. */
  userMessageId?: string;
  /** Second pass: outcomes of tools this app ran on the backend's behalf. */
  toolResults?: ChatToolResult[];
}

/** Either the reply finished, or the backend needs a tool run locally first. */
export type StreamResult =
  | {
      kind: "answer";
      assistantMessageId: string;
      memorySaved: string | null;
      isDraft: boolean;
      /** Set only for an explicit "open my tasks" navigation command: which
       *  Tasks-panel tab to open immediately, with no button. */
      openTasksTab: string | null;
      /** Buttons to show under this reply -- normally at most one, and
       *  often none. The panel never opens itself for these. */
      actions: AssistantAction[];
      /** True when some task or checklist item was created, changed, or had
       *  its status flipped this turn. */
      tasksChanged: boolean;
      /** tasks.delete resolved to exactly one task this turn, awaiting
       *  confirmation -- rendered as a pending-action card. Deletion itself
       *  only happens once the user confirms. */
      pendingTaskDelete: { taskId: string; title: string } | null;
    }
  | { kind: "client_tool"; name: string; arguments: Record<string, unknown> };

export interface StreamMeta {
  conversationId: string;
  userMessageId: string;
}

export interface StreamOptions {
  /** Called once, before any text: the ids the backend assigned. */
  onMeta?: (meta: StreamMeta) => void;
  /** Called with each piece of the reply, in order. */
  onDelta: (text: string) => void;
  /** Abort to cancel (e.g. when the chat panel closes). */
  signal?: AbortSignal;
}

/** Only ever a small, backend-computed list; malformed entries are dropped
 *  rather than shown, since a broken button is worse than none. */
function parseActions(raw: unknown): AssistantAction[] {
  if (!Array.isArray(raw)) return [];
  const out: AssistantAction[] = [];
  for (const item of raw) {
    if (!item || typeof item !== "object") continue;
    const { type, label, filter } = item as Record<string, unknown>;
    if (type === "open_task_panel" && typeof label === "string" && label) {
      out.push({ type, label, filter: typeof filter === "string" ? filter : undefined });
    }
  }
  return out;
}

/**
 * Stream one reply.
 *
 * Resolves with `answer` when the server sends `done`, or with `client_tool`
 * when it needs this app to run a tool natively -- call again with
 * `toolResults` to get the reply. Rejects with an `ApiError` whose kind says
 * what happened; any text already delivered via `onDelta` stays valid.
 */
export async function streamChatMessage(
  turn: ChatTurnRequest,
  { onMeta, onDelta, signal }: StreamOptions,
): Promise<StreamResult> {
  const response = await send("/chat/stream", {
    method: "POST",
    body: JSON.stringify({
      message: turn.message,
      conversation_id: turn.conversationId,
      user_message_id: turn.userMessageId ?? null,
      tool_results: (turn.toolResults ?? []).map((t) => ({ name: t.name, result: t.result })),
    }),
    signal,
  });
  if (!response.body) throw new ApiError("invalid", "no response body");

  let assistantMessageId: string | null = null;
  let memorySaved: string | null = null;
  let isDraft = false;
  let openTasksTab: string | null = null;
  let actions: AssistantAction[] = [];
  let tasksChanged = false;
  let pendingTaskDelete: { taskId: string; title: string } | null = null;
  let clientTool: { name: string; arguments: Record<string, unknown> } | null = null;
  try {
    for await (const { event, data } of readSse(response.body)) {
      if (event === "client_tool") {
        const t = JSON.parse(data) as { name: string; arguments?: Record<string, unknown> };
        clientTool = { name: t.name, arguments: t.arguments ?? {} };
        break;
      } else if (event === "delta") {
        const { text } = JSON.parse(data) as { text?: unknown };
        if (typeof text === "string" && text) onDelta(text);
      } else if (event === "meta") {
        const m = JSON.parse(data) as { conversation_id: string; user_message_id: string };
        onMeta?.({ conversationId: m.conversation_id, userMessageId: m.user_message_id });
      } else if (event === "done") {
        const d = JSON.parse(data) as {
          assistant_message_id?: string;
          memory_saved?: string | null;
          is_draft?: boolean;
          open_tasks_tab?: string | null;
          actions?: unknown;
          tasks_changed?: boolean;
          pending_task_delete?: { task_id?: unknown; title?: unknown } | null;
        };
        assistantMessageId = d.assistant_message_id ?? "";
        memorySaved = typeof d.memory_saved === "string" ? d.memory_saved : null;
        isDraft = d.is_draft === true;
        openTasksTab = typeof d.open_tasks_tab === "string" ? d.open_tasks_tab : null;
        actions = parseActions(d.actions);
        tasksChanged = d.tasks_changed === true;
        pendingTaskDelete =
          d.pending_task_delete &&
          typeof d.pending_task_delete.task_id === "string" &&
          typeof d.pending_task_delete.title === "string"
            ? { taskId: d.pending_task_delete.task_id, title: d.pending_task_delete.title }
            : null;
        break;
      } else if (event === "error") {
        const { code, message: serverMessage } = JSON.parse(data) as { code?: string; message?: string };
        throw new ApiError("http", serverMessage ?? "stream error", { code, serverMessage });
      }
    }
  } catch (error) {
    if (error instanceof ApiError) throw error;
    // Nothing answered: the backend may have moved to another port (the app
    // restarts it if it goes away), so ask the app again next time.
    baseUrl = null;
    if (signal?.aborted) throw new ApiError("aborted", "cancelled");
    throw new ApiError("interrupted", "stream interrupted");
  }
  if (clientTool) return { kind: "client_tool", ...clientTool };
  if (assistantMessageId === null) {
    if (signal?.aborted) throw new ApiError("aborted", "cancelled");
    throw new ApiError("interrupted", "stream ended early");
  }
  return {
    kind: "answer",
    assistantMessageId,
    memorySaved,
    isDraft,
    openTasksTab,
    actions,
    tasksChanged,
    pendingTaskDelete,
  };
}

// --- Personal memory ----------------------------------------------------------

/** Active memories, newest category/key order as the backend returns them. */
export function listMemories(): Promise<MemoryDto[]> {
  return request<MemoryDto[]>("/memories");
}

/** Create a memory. The backend derives the internal key from the content. */
export function createMemory(category: string, content: string): Promise<MemoryDto> {
  return request<MemoryDto>("/memories", {
    method: "POST",
    body: JSON.stringify({ category, content }),
  });
}

export function updateMemory(id: string, content: string): Promise<MemoryDto> {
  return request<MemoryDto>(`/memories/${id}`, {
    method: "PATCH",
    body: JSON.stringify({ content }),
  });
}

/** Forget = deactivate. The row is kept and can be restored through the API. */
export function forgetMemory(id: string): Promise<MemoryDto> {
  return request<MemoryDto>(`/memories/${id}`, { method: "DELETE" });
}

export function forgetAllMemories(): Promise<{ deactivated: number }> {
  return request<{ deactivated: number }>("/memories/deactivate-all", { method: "POST" });
}

// --- Assistant settings -------------------------------------------------------

export function getAssistantSettings(): Promise<AssistantSettingsDto> {
  return request<AssistantSettingsDto>("/settings");
}

export function updateAssistantSettings(patch: {
  assistant_name?: string;
  response_style?: string;
  default_calendar_id?: string;
  reminder_minutes?: number;
  calendar_notifications?: boolean;
  edge_activation?: boolean;
  memory_enabled?: boolean;
  hidden_calendar_ids?: string[];
}): Promise<AssistantSettingsDto> {
  return request<AssistantSettingsDto>("/settings", {
    method: "PATCH",
    body: JSON.stringify(patch),
  });
}

// --- Gmail ---------------------------------------------------------------------
// Read-only connection only: no message content ever passes through this
// client, and no token or credential ever appears in a response body.

export interface GmailStatusDto {
  connected: boolean;
  /** Set only when there is something more useful to say than "not
   *  connected" -- currently just a refresh that couldn't reach Google. */
  detail: string | null;
  /** The connected account's own address, when known. Never set unless
   *  `connected` is true. */
  email: string | null;
}

/** Never rejects with the connect-only errors below; those come from
 *  `connectGmail` instead, since a plain status check can't hit them. */
export function getGmailStatus(): Promise<GmailStatusDto> {
  return request<GmailStatusDto>("/gmail/status");
}

/**
 * Opens the user's browser for Google sign-in and waits for it to finish.
 * Can legitimately take a couple of minutes (it's waiting on a person, not
 * the network), so this uses a much longer timeout than an ordinary call --
 * long enough that the backend's own OAuth window always expires first, so
 * a real backend error is never masked by the frontend giving up early.
 */
export function connectGmail(): Promise<GmailStatusDto> {
  return request<GmailStatusDto>("/gmail/connect", { method: "POST", timeoutMs: 185_000 });
}

export function disconnectGmail(): Promise<GmailStatusDto> {
  return request<GmailStatusDto>("/gmail/disconnect", { method: "POST" });
}

// --- Tasks -----------------------------------------------------------------
// SQLite is the source of truth: every mutation here goes to a deterministic
// endpoint and the panel re-fetches from the response, so the UI never shows
// a change the database refused.

export interface TaskItemDto {
  id: string;
  task_id: string;
  text: string;
  is_completed: boolean;
  position: number;
  created_at: string;
  updated_at: string;
}

export interface TaskDto {
  id: string;
  title: string;
  description: string;
  due_at: string | null;
  priority: string;
  status: string;
  remind_at: string | null;
  completed_at: string | null;
  created_at: string;
  updated_at: string;
  category: string;
  items: TaskItemDto[];
}

export type TaskFilter = "today" | "tomorrow" | "week" | "upcoming" | "overdue" | "open" | "completed" | "cancelled" | "all";

export function listTasks(filter: TaskFilter): Promise<TaskDto[]> {
  return request<TaskDto[]>(`/tasks?filter=${encodeURIComponent(filter)}`);
}

export function createTask(body: {
  title: string;
  description?: string;
  due_at?: string;
  priority?: string;
  category?: string;
  items?: string[];
}): Promise<TaskDto> {
  return request<TaskDto>("/tasks", { method: "POST", body: JSON.stringify(body) });
}

export function completeTask(id: string): Promise<TaskDto> {
  return request<TaskDto>(`/tasks/${id}/complete`, { method: "POST" });
}

export function reopenTask(id: string): Promise<TaskDto> {
  return request<TaskDto>(`/tasks/${id}/reopen`, { method: "POST" });
}

export function addTaskItem(taskId: string, text: string): Promise<TaskDto> {
  return request<TaskDto>(`/tasks/${taskId}/items`, { method: "POST", body: JSON.stringify({ text }) });
}

export function completeTaskItem(taskId: string, itemId: string): Promise<TaskDto> {
  return request<TaskDto>(`/tasks/${taskId}/items/${itemId}/complete`, { method: "POST" });
}

export function reopenTaskItem(taskId: string, itemId: string): Promise<TaskDto> {
  return request<TaskDto>(`/tasks/${taskId}/items/${itemId}/reopen`, { method: "POST" });
}

export function deleteTaskItem(taskId: string, itemId: string): Promise<{ deleted: boolean }> {
  return request<{ deleted: boolean }>(`/tasks/${taskId}/items/${itemId}`, { method: "DELETE" });
}

/** Hard delete. Only ever called after the user confirms a pending
 *  tasks.delete action -- never a casual one-click action. */
export function deleteTask(id: string): Promise<{ deleted: boolean }> {
  return request<{ deleted: boolean }>(`/tasks/${id}`, { method: "DELETE" });
}
