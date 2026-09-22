import type { EventMutationProposal, EventProposal } from "./calendar";

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
  /** A calendar event awaiting confirmation, rendered as a card. */
  proposal?: EventProposal;
  /** Set once the user has confirmed or cancelled that proposal. */
  proposalResolved?: boolean;
  /** This message's whole text is a Gmail reply draft: rendered as a
   *  labelled draft card with a Copy button instead of a plain bubble.
   *  Never sent, never saved to Gmail -- copy-and-send-yourself only. */
  isDraft?: boolean;
  /** At most one or two small buttons shown under this reply, e.g. "Open
   *  today's tasks". Computed by the backend from the tool that actually
   *  ran, never guessed from the reply's own text. */
  actions?: AssistantAction[];
  /** A change to an EXISTING calendar event or task, awaiting confirmation
   *  -- rendered as a card. Nothing is written until the user confirms,
   *  either by clicking or by typing an affirmative reply. */
  pendingAction?: PendingAction;
  /** Set once the user has confirmed or cancelled that pending action. */
  pendingActionResolved?: boolean;
}

/** A destructive or changing action on something that already exists,
 *  found and proposed but not yet applied. */
export type PendingAction =
  | { kind: "calendar_update"; proposal: EventMutationProposal }
  | { kind: "calendar_delete"; proposal: EventMutationProposal }
  | { kind: "task_delete"; taskId: string; title: string };

/** A button under an assistant message. Clicking it is a direct frontend
 *  action (e.g. switch the panel view) -- it never sends a fake chat
 *  message on the user's behalf. */
export interface AssistantAction {
  type: "open_task_panel";
  label: string;
  /** For "open_task_panel": which Tasks-panel tab to land on. */
  filter?: string;
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
