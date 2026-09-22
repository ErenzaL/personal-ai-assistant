/** The three tabs of the Tasks panel. */
export type TaskTabId = "today" | "upcoming" | "completed";

export interface TaskItem {
  id: string;
  taskId: string;
  text: string;
  isCompleted: boolean;
  position: number;
}

export interface Task {
  id: string;
  title: string;
  description: string;
  /** ISO 8601 UTC, or null when the task has no due date. */
  dueAt: string | null;
  priority: "low" | "normal" | "high";
  status: "open" | "completed" | "cancelled";
  completedAt: string | null;
  /** Free-text label ("School", "Work"); "" means uncategorised. */
  category: string;
  items: TaskItem[];
}

/** Fields for the "+ Add task" form. Only `title` is required. */
export interface NewTaskInput {
  title: string;
  description?: string;
  /** Local-time ISO 8601, e.g. "2026-09-15T20:00:00". */
  dueAt?: string;
  category?: string;
  priority?: "low" | "normal" | "high";
  items?: string[];
}
