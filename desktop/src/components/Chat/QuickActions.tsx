import type { QuickAction } from "../../types/chat";
import "./QuickActions.css";

export interface QuickActionsProps {
  actions: QuickAction[];
  onSelect: (action: QuickAction) => void;
  disabled?: boolean;
}

/** Row of one-tap prompts above the input. */
export function QuickActions({ actions, onSelect, disabled = false }: QuickActionsProps) {
  return (
    <div className="quick-actions" role="group" aria-label="Quick actions">
      {actions.map((action) => (
        <button
          key={action.id}
          type="button"
          className="quick-actions__button"
          onClick={() => onSelect(action)}
          disabled={disabled}
        >
          {action.label}
        </button>
      ))}
    </div>
  );
}
