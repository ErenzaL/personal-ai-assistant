import { useState } from "react";
import { CATEGORY_LABEL, type MemoryItem } from "../../types/settings";
import "./SettingsPanel.css";

export interface MemoryReviewPanelProps {
  items: MemoryItem[];
  isLoading: boolean;
  onEdit: (id: string, content: string) => Promise<boolean>;
  onForget: (id: string) => Promise<boolean>;
}

/**
 * The full list behind Settings' "What the assistant remembers" link.
 * Review, edit, or forget one at a time -- there is no "+ Add" here:
 * everything here was learned automatically from conversation, not typed
 * in, so creating one by hand would misrepresent where it came from.
 */
export function MemoryReviewPanel({ items, isLoading, onEdit, onForget }: MemoryReviewPanelProps) {
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editContent, setEditContent] = useState("");
  const [busy, setBusy] = useState(false);

  const submitEdit = async () => {
    if (!editingId || !editContent.trim() || busy) return;
    setBusy(true);
    const ok = await onEdit(editingId, editContent.trim());
    setBusy(false);
    if (ok) setEditingId(null);
  };

  return (
    <div className="settings-panel">
      <p className="settings-hint">
        Learned automatically from conversation. Edit anything that's wrong, or forget what you'd rather
        Dully not use.
      </p>

      {isLoading && items.length === 0 && <p className="settings-empty">Loading…</p>}
      {!isLoading && items.length === 0 && (
        <p className="settings-empty">Nothing remembered yet. It fills in as you talk with Dully.</p>
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
    </div>
  );
}
