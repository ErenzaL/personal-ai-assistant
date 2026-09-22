import type { PendingAction } from "../../types/chat";
import { parseLocal } from "../../services/eventPlanning";
import "./EventProposalCard.css";

export interface PendingActionCardProps {
  action: PendingAction;
  /** Disabled once the user has acted, so nothing runs twice. */
  resolved?: boolean;
  onConfirm: () => void;
  onCancel: () => void;
}

function dayLabel(iso: string): string {
  const date = parseLocal(iso);
  if (!date) return iso;
  return date.toLocaleDateString([], { weekday: "long", day: "numeric", month: "short" });
}

function timeLabel(iso: string): string {
  const date = parseLocal(iso);
  if (!date) return iso;
  return date.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
}

const HEADING: Record<PendingAction["kind"], string> = {
  calendar_update: "Update event",
  calendar_delete: "Cancel event",
  task_delete: "Delete task",
};

const CONFIRM_LABEL: Record<PendingAction["kind"], string> = {
  calendar_update: "Move it",
  calendar_delete: "Cancel appointment",
  task_delete: "Delete it",
};

const CANCEL_LABEL: Record<PendingAction["kind"], string> = {
  calendar_update: "Keep it as is",
  calendar_delete: "Keep it",
  task_delete: "Keep it",
};

/**
 * A change to something that already exists (an event or a task), awaiting
 * confirmation -- distinct from `EventProposalCard`, which is for a brand
 * new event and has its own inline edit form. Nothing here is written until
 * Confirm; the card only ever describes what's about to happen.
 */
export function PendingActionCard({ action, resolved = false, onConfirm, onCancel }: PendingActionCardProps) {
  return (
    <div className="proposal">
      <span className="proposal__heading">{HEADING[action.kind]}</span>

      {action.kind === "task_delete" ? (
        <dl className="proposal__details">
          <dt>Task</dt>
          <dd>{action.title}</dd>
        </dl>
      ) : (
        <dl className="proposal__details">
          <dt>Title</dt>
          <dd>{action.proposal.title}</dd>
          <dt>Date</dt>
          <dd>{dayLabel(action.proposal.before.start)}</dd>
          <dt>Time</dt>
          <dd>
            {timeLabel(action.proposal.before.start)} – {timeLabel(action.proposal.before.end)}
            {action.kind === "calendar_update" && action.proposal.changes?.start && (
              <>
                {" "}
                → {timeLabel(action.proposal.changes.start)} – {timeLabel(action.proposal.changes.end ?? action.proposal.changes.start)}
              </>
            )}
          </dd>
          {action.kind === "calendar_update" && action.proposal.changes?.title && (
            <>
              <dt>New title</dt>
              <dd>{action.proposal.changes.title}</dd>
            </>
          )}
          {action.kind === "calendar_update" && action.proposal.changes?.location !== undefined && (
            <>
              <dt>New location</dt>
              <dd>{action.proposal.changes.location || "(cleared)"}</dd>
            </>
          )}
          <dt>Calendar</dt>
          <dd>{action.proposal.calendarTitle}</dd>
        </dl>
      )}

      {!resolved && (
        <div className="proposal__actions">
          <button type="button" className="settings-button" onClick={onConfirm}>
            {CONFIRM_LABEL[action.kind]}
          </button>
          <button type="button" className="settings-link" onClick={onCancel}>
            {CANCEL_LABEL[action.kind]}
          </button>
        </div>
      )}
    </div>
  );
}
