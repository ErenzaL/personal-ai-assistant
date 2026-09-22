import { Toggle } from "./Toggle";

export interface MemorySectionProps {
  enabled: boolean;
  onChangeEnabled: (enabled: boolean) => void;
  itemCount: number;
  onOpenReview: () => void;
}

/**
 * What Settings shows about memory: one switch, and a link to the review
 * list. Nothing is created here -- memories are learned automatically from
 * conversation (see `memory_extraction.py`); this is where the user turns
 * that off, or goes to see, edit, or forget what was kept.
 */
export function MemorySection({ enabled, onChangeEnabled, itemCount, onOpenReview }: MemorySectionProps) {
  return (
    <section className="settings-section">
      <div className="settings-section__head">
        <h3 className="settings-section__title">Memory</h3>
      </div>
      <div className="settings-card">
        <Toggle label="Remember things from chats" checked={enabled} onChange={onChangeEnabled} />
        <button type="button" className="settings-row-link" onClick={onOpenReview}>
          <span>Saved memories</span>
          <span className="settings-row-link__meta">
            {itemCount > 0 ? itemCount : ""}
            <span aria-hidden="true">›</span>
          </span>
        </button>
      </div>
      {!enabled ? (
        <p className="settings-hint">
          Nothing new will be learned. What's already saved stays, and is still used to answer.
        </p>
      ) : (
        <p className="settings-hint">Dully uses memories to personalize replies. You can review or delete them anytime.</p>
      )}
    </section>
  );
}
