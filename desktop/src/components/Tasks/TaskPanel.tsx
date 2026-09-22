import { useState } from "react";
import { TaskTabs } from "./TaskTabs";
import { TaskList } from "./TaskList";
import { TaskForm } from "./TaskForm";
import type { NewTaskInput, Task, TaskTabId } from "../../types/tasks";
import "./TaskPanel.css";

export interface TaskPanelProps {
  activeTab: TaskTabId;
  onChangeTab: (tab: TaskTabId) => void;
  today: Task[];
  upcoming: Task[];
  completed: Task[];
  isLoading: boolean;
  error: string | null;
  onAddTask: (input: NewTaskInput) => Promise<boolean>;
  onCompleteTask: (id: string) => void;
  onReopenTask: (id: string) => void;
  onAddItem: (taskId: string, text: string) => Promise<boolean>;
  onCompleteItem: (taskId: string, itemId: string) => void;
  onReopenItem: (taskId: string, itemId: string) => void;
  onDeleteItem: (taskId: string, itemId: string) => void;
}

/**
 * Tasks as structured, interactive data -- not chat text. Tabs pick a
 * window (Today/Upcoming/Completed); the list under them is read from and
 * written straight through the backend (`useTasks`), the same service a
 * chat-driven task action uses, so a manual click and "I finished the
 * plots" both end up in exactly the same place.
 */
export function TaskPanel({
  activeTab,
  onChangeTab,
  today,
  upcoming,
  completed,
  isLoading,
  error,
  onAddTask,
  onCompleteTask,
  onReopenTask,
  onAddItem,
  onCompleteItem,
  onReopenItem,
  onDeleteItem,
}: TaskPanelProps) {
  const [isFormOpen, setIsFormOpen] = useState(false);
  const tasksByTab: Record<TaskTabId, Task[]> = { today, upcoming, completed };
  const tasks = tasksByTab[activeTab];

  return (
    <div className="task-panel">
      <TaskTabs activeTab={activeTab} onChangeTab={onChangeTab} />
      <div className="task-panel__body">
        {error && <p className="settings-error">{error}</p>}
        <TaskList
          tab={activeTab}
          tasks={tasks}
          isLoading={isLoading}
          onComplete={onCompleteTask}
          onReopen={onReopenTask}
          onAddItem={onAddItem}
          onCompleteItem={onCompleteItem}
          onReopenItem={onReopenItem}
          onDeleteItem={onDeleteItem}
        />
        {isFormOpen ? (
          <TaskForm
            onSubmit={async (input) => {
              const ok = await onAddTask(input);
              if (ok) setIsFormOpen(false);
              return ok;
            }}
            onCancel={() => setIsFormOpen(false)}
          />
        ) : (
          <button type="button" className="task-add-button" onClick={() => setIsFormOpen(true)}>
            + Add task
          </button>
        )}
      </div>
    </div>
  );
}
