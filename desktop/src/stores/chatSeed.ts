/**
 * Static chat content: the assistant's name, the opening greeting, and the
 * quick-action prompts. Messages themselves live on the backend.
 */
import type { QuickAction } from "../types/chat";

export const ASSISTANT_NAME = "Assistant";

/**
 * Opening line for an empty conversation. Shown as a local assistant bubble
 * (not stored, not sent to the model), so a new chat costs no API call.
 */
export function greeting(now: Date = new Date()): string {
  const hour = now.getHours();
  const opener =
  hour < 5 ? "Working late?" :
  hour < 12 ? "Good morning" :
  hour < 18 ? "Good afternoon" :
  "Good evening";

return `${opener}!\nWhat are we working on today?`;
}

export const QUICK_ACTIONS: QuickAction[] = [
  { id: "today", label: "Today", prompt: "What tasks do I have today?" },
  { id: "tasks", label: "Tasks", prompt: "What are my open tasks?" },
  { id: "overdue", label: "Overdue", prompt: "What tasks are overdue?" },
];
