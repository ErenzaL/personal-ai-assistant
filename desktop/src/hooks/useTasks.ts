import { useCallback, useEffect, useRef, useState } from "react";
import {
  addTaskItem,
  completeTask,
  completeTaskItem,
  createTask,
  deleteTaskItem,
  describeApiError,
  listTasks,
  reopenTask,
  reopenTaskItem,
  type TaskDto,
  type TaskItemDto,
} from "../services/api";
import type { NewTaskInput, Task, TaskItem } from "../types/tasks";

function itemFromDto(dto: TaskItemDto): TaskItem {
  return { id: dto.id, taskId: dto.task_id, text: dto.text, isCompleted: dto.is_completed, position: dto.position };
}

function fromDto(dto: TaskDto): Task {
  return {
    id: dto.id,
    title: dto.title,
    description: dto.description,
    dueAt: dto.due_at,
    priority: dto.priority as Task["priority"],
    status: dto.status as Task["status"],
    completedAt: dto.completed_at,
    category: dto.category,
    items: dto.items.map(itemFromDto),
  };
}

/**
 * Tasks for the panel's three tabs, loaded from and written through the
 * backend. SQLite is the source of truth: every mutation re-fetches all
 * three tabs afterward (one task can move between them, e.g. completing it
 * moves it out of Today into Completed), so the UI never shows a change the
 * database refused, and never drifts from what actually happened.
 */
export function useTasks(enabled: boolean) {
  const [today, setToday] = useState<Task[]>([]);
  const [upcoming, setUpcoming] = useState<Task[]>([]);
  const [completed, setCompleted] = useState<Task[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const mounted = useRef(true);

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);

  const reload = useCallback(async () => {
    setIsLoading(true);
    try {
      const [t, u, c] = await Promise.all([listTasks("today"), listTasks("upcoming"), listTasks("completed")]);
      if (!mounted.current) return;
      setToday(t.map(fromDto));
      setUpcoming(u.map(fromDto));
      setCompleted(c.map(fromDto));
      setError(null);
    } catch (err) {
      if (mounted.current) setError(describeApiError(err));
    } finally {
      if (mounted.current) setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    if (enabled) void reload();
  }, [enabled, reload]);

  /** Runs a mutation, refreshes all three tabs from the server, and reports
   *  whether it succeeded -- callers use this to show a failure gracefully
   *  instead of leaving the panel showing a change that didn't persist. */
  const run = useCallback(
    async (action: () => Promise<unknown>): Promise<boolean> => {
      try {
        await action();
        await reload();
        return true;
      } catch (err) {
        if (mounted.current) setError(describeApiError(err));
        return false;
      }
    },
    [reload],
  );

  const addTask = useCallback(
    (input: NewTaskInput) =>
      run(() =>
        createTask({
          title: input.title,
          description: input.description,
          due_at: input.dueAt,
          priority: input.priority,
          category: input.category,
          items: input.items,
        }),
      ),
    [run],
  );

  const complete = useCallback((id: string) => run(() => completeTask(id)), [run]);
  const reopen = useCallback((id: string) => run(() => reopenTask(id)), [run]);
  const addItem = useCallback((taskId: string, text: string) => run(() => addTaskItem(taskId, text)), [run]);
  const completeItem = useCallback(
    (taskId: string, itemId: string) => run(() => completeTaskItem(taskId, itemId)),
    [run],
  );
  const reopenItem = useCallback(
    (taskId: string, itemId: string) => run(() => reopenTaskItem(taskId, itemId)),
    [run],
  );
  const deleteItem = useCallback(
    (taskId: string, itemId: string) => run(() => deleteTaskItem(taskId, itemId)),
    [run],
  );

  return {
    today,
    upcoming,
    completed,
    isLoading,
    error,
    reload,
    addTask,
    complete,
    reopen,
    addItem,
    completeItem,
    reopenItem,
    deleteItem,
  };
}
