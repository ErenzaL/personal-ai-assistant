import { useState } from "react";
import { CATEGORY_LABEL, MEMORY_CATEGORIES, type MemoryCategory, type MemoryItem } from "../../types/settings";

export interface MemorySectionProps {
  items: MemoryItem[];
  isLoading: boolean;
  onAdd: (category: MemoryCategory, content: string) => Promise<boolean>;
  onEdit: (id: string, content: string) => Promise<boolean>;
  onForget: (id: string) => Promise<boolean>;
  onForgetAll: () => Promise<boolean>;
}

/**
 * Compact list of what the assistant remembers, with add / edit / forget.
 * Only the category and the wording are shown; keys, ids, confidence and
 * source stay internal. Forgetting deactivates a memory, it does not delete
 * the row, and forgetting everything asks first.
 */
export function MemorySection({ items, isLoading, onAdd, onEdit, onForget, onForgetAll }: MemorySectionProps) {
  const [adding, setAdding] = useState(false);
  const [draftCategory, setDraftCategory] = useState<MemoryCategory>("preference");
  const [draftContent, setDraftContent] = useState("");
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editContent, setEditContent] = useState("");
  const [confirmClear, setConfirmClear] = useState(false);
  const [busy, setBusy] = useState(false);

  const resetAdd = () => {
    setAdding(false);
    setDraftContent("");
  };

  const submitAdd = async () => {
    if (!draftContent.trim() || busy) return;
    setBusy(true);
    const ok = await onAdd(draftCategory, draftContent.trim());
    setBusy(false);
    if (ok) resetAdd();
  };

  const submitEdit = async () => {
    if (!editingId || !editContent.trim() || busy) return;
    setBusy(true);
    const ok = await onEdit(editingId, editContent.trim());
    setBusy(false);
    if (ok) setEditingId(null);
  };

  const clearAll = async () => {
    setBusy(true);
    await onForgetAll();
    setBusy(false);
    setConfirmClear(false);
  };

  return (
    <section className="settings-section">
      <div className="settings-section__head">
        <h3 className="settings-section__title">Personal memory</h3>
        {!adding && (
          <button type="button" className="settings-link" onClick={() => setAdding(true)}>
            + Add
          </button>
        )}
      </div>

      {adding && (
        <div className="memory-form">
          <select
            className="memory-form__category"
            value={draftCategory}
            onChange={(event) => setDraftCategory(event.target.value as MemoryCategory)}
            aria-label="Category"
          >
            {MEMORY_CATEGORIES.map((category) => (
              <option key={category} value={category}>
                {CATEGORY_LABEL[category]}
              </option>
            ))}
          </select>
          <input
            className="memory-form__input"
            value={draftContent}
            onChange={(event) => setDraftContent(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter") void submitAdd();
              if (event.key === "Escape") resetAdd();
            }}
            placeholder="Prefers meetings after 2 PM"
            aria-label="What to remember"
            autoFocus
          />
          <div className="memory-form__actions">
            <button type="button" className="settings-button" onClick={() => void submitAdd()} disabled={busy}>
              Save
            </button>
            <button type="button" className="settings-link" onClick={resetAdd}>
              Cancel
            </button>
          </div>
        </div>
      )}

      {isLoading && items.length === 0 && <p className="settings-empty">Loading…</p>}
      {!isLoading && items.length === 0 && !adding && (
        <p className="settings-empty">Nothing saved yet. Add something, or say “Remember that…” in chat.</p>
      )}

      <ul className="memory-list">
        {items.map((item) => (
          <li key={item.id} className="memory-row">
            <span className="memory-row__category">{CATEGORY_LABEL[item.category]}</span>
            {editingId === item.id ? (
              <>
                <input
                  className="memory-form__input"
                  value={editContent}
                  onChange={(event) => setEditContent(event.target.value)}
                  onKeyDown={(event) => {
                    if (event.key === "Enter") void submitEdit();
                    if (event.key === "Escape") setEditingId(null);
                  }}
                  aria-label="Edit memory"
                  autoFocus
                />
                <div className="memory-row__actions">
                  <button type="button" className="settings-link" onClick={() => void submitEdit()} disabled={busy}>
                    Save
                  </button>
                  <button type="button" className="settings-link" onClick={() => setEditingId(null)}>
                    Cancel
                  </button>
                </div>
              </>
            ) : (
              <>
                <span className="memory-row__content">{item.content}</span>
                <div className="memory-row__actions">
                  <button
                    type="button"
                    className="settings-link"
                    onClick={() => {
                      setEditingId(item.id);
                      setEditContent(item.content);
                    }}
                  >
                    Edit
                  </button>
                  <button
                    type="button"
                    className="settings-link settings-link--danger"
                    onClick={() => void onForget(item.id)}
                  >
                    Forget
                  </button>
                </div>
              </>
            )}
          </li>
        ))}
      </ul>

      {items.length > 0 &&
        (confirmClear ? (
          <div className="settings-confirm">
            <span>Forget all {items.length} {items.length === 1 ? "memory" : "memories"}?</span>
            <button
              type="button"
              className="settings-link settings-link--danger"
              onClick={() => void clearAll()}
              disabled={busy}
            >
              Yes, forget all
            </button>
            <button type="button" className="settings-link" onClick={() => setConfirmClear(false)}>
              Cancel
            </button>
          </div>
        ) : (
          <button
            type="button"
            className="settings-link settings-link--danger settings-section__footer"
            onClick={() => setConfirmClear(true)}
          >
            Forget all
          </button>
        ))}
    </section>
  );
}
