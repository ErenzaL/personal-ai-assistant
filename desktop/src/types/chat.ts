export type MessageRole = "user" | "assistant" | "system";

export interface Message {
  id: string;
  role: MessageRole;
  text: string;
  /** ISO 8601 timestamp. */
  sentAt: string;
  /** True while the assistant's text is still arriving. */
  streaming?: boolean;
  /** True for local-only notices that are not stored on the backend. */
  local?: boolean;
}

export interface Conversation {
  id: string;
  title: string | null;
}

export type QuickActionId = "today" | "tasks" | "overdue";

export interface QuickAction {
  id: QuickActionId;
  label: string;
  /** Text sent as the user message when the button is pressed. */
  prompt: string;
}

/** Whether the backend answered the last request. */
export type BackendStatus = "unknown" | "online" | "offline";
