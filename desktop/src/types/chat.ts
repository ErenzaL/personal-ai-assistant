import type { EventProposal } from "./calendar";

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
