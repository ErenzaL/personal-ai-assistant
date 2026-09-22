import { useState } from "react";
import type { NewTaskInput } from "../../types/tasks";

export interface TaskFormProps {
  onSubmit: (input: NewTaskInput) => Promise<boolean>;
  onCancel: () => void;
}

/** "+ Add task" form: title is the only required field. Combines the date
 *  and time inputs into one local-time ISO string, the shape the backend's
 *  `due_at` already expects everywhere else in the app. */
export function TaskForm({ onSubmit, onCancel }: TaskFormProps) {
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [date, setDate] = useState("");
  const [time, setTime] = useState("");
  const [category, setCategory] = useState("");
  const [priority, setPriority] = useState<"low" | "normal" | "high">("normal");
  const [items, setItems] = useState<string[]>([]);
  const [itemDraft, setItemDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const addItemDraft = () => {
    const text = itemDraft.trim();
    if (!text) return;
    setItems((prev) => [...prev, text]);
    setItemDraft("");
  };

  const removeItem = (index: number) => setItems((prev) => prev.filter((_, i) => i !== index));

  const submit = async () => {
    const trimmedTitle = title.trim();
    if (!trimmedTitle || busy) return;
    setBusy(true);
    setError(null);
    const ok = await onSubmit({
      title: trimmedTitle,
      description: description.trim() || undefined,
      dueAt: date ? `${date}T${time || "09:00"}:00` : undefined,
      category: category.trim() || undefined,
      priority,
      items: items.length > 0 ? items : undefined,
    });
    setBusy(false);
    if (!ok) setError("That didn't save. Please try again.");
  };

  return (
    <div className="task-form">
      <div className="settings-card">
        <label className="settings-field">
          <span className="settings-field__label">Title</span>
          <input
            className="settings-field__input"
            value={title}
            onChange={(event) => setTitle(event.target.value)}
            maxLength={200}
            placeholder="What needs doing?"
            autoFocus
          />
        </label>
        <label className="settings-field">
          <span className="settings-field__label">Description</span>
          <input
            className="settings-field__input"
            value={description}
            onChange={(event) => setDescription(event.target.value)}
            maxLength={2000}
          />
        </label>
        <label className="settings-field">
          <span className="settings-field__label">Due date</span>
          <input
            className="settings-field__input"
            type="date"
            value={date}
            onChange={(event) => setDate(event.target.value)}
          />
        </label>
        {date && (
          <label className="settings-field">
            <span className="settings-field__label">Due time</span>
            <input
              className="settings-field__input"
              type="time"
              value={time}
              onChange={(event) => setTime(event.target.value)}
            />
          </label>
        )}
        <label className="settings-field">
          <span className="settings-field__label">Category</span>
          <input
            className="settings-field__input"
            value={category}
            onChange={(event) => setCategory(event.target.value)}
            maxLength={60}
            placeholder="School, Work…"
          />
        </label>
        <label className="settings-field">
          <span className="settings-field__label">Priority</span>
          <select
            className="settings-field__input"
            value={priority}
            onChange={(event) => setPriority(event.target.value as "low" | "normal" | "high")}
          >
            <option value="low">Low</option>
            <option value="normal">Normal</option>
            <option value="high">High</option>
          </select>
        </label>
        <div className="task-form__items">
          <span className="settings-field__label">Checklist</span>
          {items.length > 0 && (
            <ul className="task-form__item-list">
              {items.map((text, index) => (
                <li key={`${text}-${index}`}>
                  <span>{text}</span>
                  <button type="button" className="settings-link settings-link--danger" onClick={() => removeItem(index)}>
                    Remove
                  </button>
                </li>
              ))}
            </ul>
          )}
          <div className="task-items__add">
            <input
              className="task-items__input"
              value={itemDraft}
              placeholder="Add a step…"
              maxLength={200}
              onChange={(event) => setItemDraft(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === "Enter") {
                  event.preventDefault();
                  addItemDraft();
                }
              }}
            />
            <button type="button" className="settings-link" onClick={addItemDraft} disabled={!itemDraft.trim()}>
              Add
            </button>
          </div>
        </div>
      </div>
      {error && <p className="settings-error">{error}</p>}
      <div className="task-form__actions">
        <button type="button" className="settings-button" onClick={() => void submit()} disabled={busy || !title.trim()}>
          {busy ? "Adding…" : "Add task"}
        </button>
        <button type="button" className="settings-link" onClick={onCancel}>
          Cancel
        </button>
      </div>
    </div>
  );
}
