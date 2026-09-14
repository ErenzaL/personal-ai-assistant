import { useState } from "react";
import type { EventProposal } from "../../types/calendar";
import { addMinutes, parseLocal } from "../../services/eventPlanning";
import "./EventProposalCard.css";

export interface EventProposalCardProps {
  proposal: EventProposal;
  /** Disabled once the user has acted, so an event cannot be created twice. */
  resolved?: boolean;
  onConfirm: (proposal: EventProposal) => void;
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

/** Minutes between two local ISO strings, for the editable duration field. */
function minutesBetween(start: string, end: string): number {
  const a = parseLocal(start);
  const b = parseLocal(end);
  if (!a || !b) return 60;
  return Math.max(1, Math.round((b.getTime() - a.getTime()) / 60000));
}

/**
 * The one place an event can be created from chat. Nothing is written until
 * Confirm is pressed; Edit adjusts the details first, Cancel drops it.
 */
export function EventProposalCard({ proposal, resolved = false, onConfirm, onCancel }: EventProposalCardProps) {
  const [editing, setEditing] = useState(false);
  const [title, setTitle] = useState(proposal.title);
  const [start, setStart] = useState(proposal.start.slice(0, 16));
  const [duration, setDuration] = useState(minutesBetween(proposal.start, proposal.end));

  const edited: EventProposal = {
    ...proposal,
    title: title.trim() || proposal.title,
    start: `${start}:00`,
    end: addMinutes(`${start}:00`, duration) ?? proposal.end,
  };
  const shown = editing ? edited : proposal;

  return (
    <div className="proposal">
      <span className="proposal__heading">Add to calendar</span>

      {editing ? (
        <div className="proposal__form">
          <label className="proposal__field">
            <span>Title</span>
            <input value={title} onChange={(e) => setTitle(e.target.value)} maxLength={200} autoFocus />
          </label>
          <label className="proposal__field">
            <span>Starts</span>
            <input type="datetime-local" value={start} onChange={(e) => setStart(e.target.value)} />
          </label>
          <label className="proposal__field">
            <span>Minutes</span>
            <input
              type="number"
              min={1}
              max={1440}
              value={duration}
              onChange={(e) => setDuration(Math.max(1, Number(e.target.value) || 1))}
            />
          </label>
        </div>
      ) : (
        <dl className="proposal__details">
          <dt>Title</dt>
          <dd>{shown.title}</dd>
          <dt>Date</dt>
          <dd>{dayLabel(shown.start)}</dd>
          <dt>Time</dt>
          <dd>
            {timeLabel(shown.start)} – {timeLabel(shown.end)}
          </dd>
          <dt>Calendar</dt>
          <dd>{shown.calendarTitle}</dd>
          {shown.location && (
            <>
              <dt>Where</dt>
              <dd>{shown.location}</dd>
            </>
          )}
        </dl>
      )}

      {proposal.conflicts.length > 0 && (
        <p className="proposal__conflict">
          {proposal.conflicts.map((c) => (
            <span key={c.id ?? c.title}>
              You already have {c.title} from {timeLabel(c.start)}–{timeLabel(c.end)}.
            </span>
          ))}
        </p>
      )}

      {!resolved && (
        <div className="proposal__actions">
          <button type="button" className="settings-button" onClick={() => onConfirm(shown)}>
            Confirm
          </button>
          <button type="button" className="settings-link" onClick={() => setEditing((v) => !v)}>
            {editing ? "Done" : "Edit"}
          </button>
          <button type="button" className="settings-link" onClick={onCancel}>
            Cancel
          </button>
        </div>
      )}
    </div>
  );
}
