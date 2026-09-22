import { TaskCheckbox } from "./TaskCheckbox";
import type { TaskItem as TaskItemModel } from "../../types/tasks";

export interface TaskItemProps {
  taskId: string;
  item: TaskItemModel;
  onComplete: (taskId: string, itemId: string) => void;
  onReopen: (taskId: string, itemId: string) => void;
  onDelete: (taskId: string, itemId: string) => void;
}

/** One checklist row: its own checkbox, independent of the parent task's. */
export function TaskItem({ taskId, item, onComplete, onReopen, onDelete }: TaskItemProps) {
  return (
    <li className="task-item">
      <TaskCheckbox
        checked={item.isCompleted}
        label={item.text}
        onChange={(checked) => (checked ? onComplete(taskId, item.id) : onReopen(taskId, item.id))}
      />
      <span className={`task-item__text${item.isCompleted ? " task-item__text--done" : ""}`}>{item.text}</span>
      <button
        type="button"
        className="settings-link settings-link--danger task-item__delete"
        onClick={(event) => {
          event.stopPropagation();
          onDelete(taskId, item.id);
        }}
      >
        Delete
      </button>
    </li>
  );
}
