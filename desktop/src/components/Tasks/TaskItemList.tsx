import { useState } from "react";
import { TaskItem } from "./TaskItem";
import type { TaskItem as TaskItemModel } from "../../types/tasks";

export interface TaskItemListProps {
  taskId: string;
  items: TaskItemModel[];
  onAddItem: (taskId: string, text: string) => Promise<boolean>;
  onCompleteItem: (taskId: string, itemId: string) => void;
  onReopenItem: (taskId: string, itemId: string) => void;
  onDeleteItem: (taskId: string, itemId: string) => void;
}

/** The checklist under an expanded task card, plus a small inline "add a
 *  step" control. Stops click propagation so nothing here toggles the
 *  parent card's expand/collapse. */
export function TaskItemList({ taskId, items, onAddItem, onCompleteItem, onReopenItem, onDeleteItem }: TaskItemListProps) {
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);

  const submit = async () => {
    const text = draft.trim();
    if (!text || busy) return;
    setBusy(true);
    const ok = await onAddItem(taskId, text);
    setBusy(false);
    if (ok) setDraft("");
  };

  return (
    <div className="task-items" onClick={(event) => event.stopPropagation()}>
      {items.length > 0 && (
        <ul className="task-items__list">
          {items.map((item) => (
            <TaskItem
              key={item.id}
              taskId={taskId}
              item={item}
              onComplete={onCompleteItem}
              onReopen={onReopenItem}
              onDelete={onDeleteItem}
            />
          ))}
        </ul>
      )}
      <div className="task-items__add">
        <input
          className="task-items__input"
          value={draft}
          placeholder="Add a step…"
          maxLength={200}
          onChange={(event) => setDraft(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter") void submit();
          }}
        />
        <button type="button" className="settings-link" onClick={() => void submit()} disabled={busy || !draft.trim()}>
          Add
        </button>
      </div>
    </div>
  );
}
