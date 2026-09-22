import { Fragment } from "react";
import { TaskCard } from "./TaskCard";
import type { Task, TaskTabId } from "../../types/tasks";

export interface TaskListProps {
  tab: TaskTabId;
  tasks: Task[];
  isLoading: boolean;
  onComplete: (id: string) => void;
  onReopen: (id: string) => void;
  onAddItem: (taskId: string, text: string) => Promise<boolean>;
  onCompleteItem: (taskId: string, itemId: string) => void;
  onReopenItem: (taskId: string, itemId: string) => void;
  onDeleteItem: (taskId: string, itemId: string) => void;
}

const EMPTY_COPY: Record<TaskTabId, string> = {
  today: "No tasks for today.",
  upcoming: "No upcoming tasks.",
  completed: "No completed tasks yet.",
};

/** One tab's scrollable list. Undated tasks are never hidden in Upcoming --
 *  a single "No due date" divider marks where they start, since the
 *  backend already sorts dated tasks first and undated ones after. */
export function TaskList({
  tab,
  tasks,
  isLoading,
  onComplete,
  onReopen,
  onAddItem,
  onCompleteItem,
  onReopenItem,
  onDeleteItem,
}: TaskListProps) {
  if (isLoading && tasks.length === 0) return <p className="settings-empty">Loading…</p>;
  if (!isLoading && tasks.length === 0) return <p className="settings-empty">{EMPTY_COPY[tab]}</p>;

  const firstUndated = tasks.findIndex((t) => t.dueAt === null);
  const showDivider = tab === "upcoming" && firstUndated > 0;

  return (
    <ul className="task-list">
      {tasks.map((task, index) => (
        <Fragment key={task.id}>
          {showDivider && index === firstUndated && (
            <li className="task-list__divider" aria-hidden="true">
              No due date
            </li>
          )}
          <TaskCard
            task={task}
            onComplete={onComplete}
            onReopen={onReopen}
            onAddItem={onAddItem}
            onCompleteItem={onCompleteItem}
            onReopenItem={onReopenItem}
            onDeleteItem={onDeleteItem}
          />
        </Fragment>
      ))}
    </ul>
  );
}
