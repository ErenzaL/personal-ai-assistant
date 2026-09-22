import { useState } from "react";
import { TaskCheckbox } from "./TaskCheckbox";
import { TaskItemList } from "./TaskItemList";
import { formatCompletedLabel, formatDueLabel, isPastDue } from "./taskFormat";
import type { Task } from "../../types/tasks";

export interface TaskCardProps {
  task: Task;
  onComplete: (id: string) => void;
  onReopen: (id: string) => void;
  onAddItem: (taskId: string, text: string) => Promise<boolean>;
  onCompleteItem: (taskId: string, itemId: string) => void;
  onReopenItem: (taskId: string, itemId: string) => void;
  onDeleteItem: (taskId: string, itemId: string) => void;
}

/** One task: checkbox, title, an optional truncated description that
 *  expands with the card, due date/category, checklist progress, and (when
 *  expanded) the checklist itself. Completed tasks render visually quieter
 *  -- checked, muted/struck title, completion date -- per spec, never as
 *  the dominant thing on screen. */
export function TaskCard({ task, onComplete, onReopen, onAddItem, onCompleteItem, onReopenItem, onDeleteItem }: TaskCardProps) {
  const [expanded, setExpanded] = useState(false);
  const done = task.status === "completed";
  const progress = task.items.length > 0 ? task.items.filter((i) => i.isCompleted).length : null;
  const dueLabel = formatDueLabel(task.dueAt);
  const completedLabel = done ? formatCompletedLabel(task.completedAt) : null;
  const overdue = !done && isPastDue(task.dueAt);
  const hasExpandable = task.description.trim().length > 0 || task.items.length > 0;

  const toggleExpanded = () => {
    if (hasExpandable) setExpanded((v) => !v);
  };

  return (
    <li className={`task-card${done ? " task-card--done" : ""}`}>
      {/* A div, not a button: it has to contain the checkbox's own <input>,
          and a button can't legally contain another interactive control. */}
      <div
        className="task-card__row"
        role={hasExpandable ? "button" : undefined}
        tabIndex={hasExpandable ? 0 : undefined}
        aria-expanded={hasExpandable ? expanded : undefined}
        onClick={toggleExpanded}
        onKeyDown={(event) => {
          if (hasExpandable && (event.key === "Enter" || event.key === " ")) {
            event.preventDefault();
            toggleExpanded();
          }
        }}
      >
        <TaskCheckbox
          checked={done}
          label={task.title}
          onChange={(checked) => (checked ? onComplete(task.id) : onReopen(task.id))}
        />
        <span className="task-card__body">
          <span className="task-card__title">{task.title}</span>
          {task.description && (
            <span className={`task-card__description${expanded ? " task-card__description--expanded" : ""}`}>
              {task.description}
            </span>
          )}
          <span className="task-card__meta">
            {done ? (
              completedLabel && <span>Completed {completedLabel}</span>
            ) : (
              <>
                {dueLabel && <span className={overdue ? "task-card__due--overdue" : undefined}>Due {dueLabel}</span>}
                {task.category && <span>{task.category}</span>}
              </>
            )}
          </span>
          {progress !== null && (
            <span className="task-card__progress">
              Progress: {progress} / {task.items.length}
            </span>
          )}
        </span>
        {hasExpandable && (
          <span className={`task-card__chevron${expanded ? " task-card__chevron--open" : ""}`} aria-hidden="true">
            ›
          </span>
        )}
      </div>
      {expanded && (
        <TaskItemList
          taskId={task.id}
          items={task.items}
          onAddItem={onAddItem}
          onCompleteItem={onCompleteItem}
          onReopenItem={onReopenItem}
          onDeleteItem={onDeleteItem}
        />
      )}
    </li>
  );
}
