import type { AssistantAction } from "../../types/chat";
import "./MessageActions.css";

export interface MessageActionsProps {
  actions: AssistantAction[];
  onAction: (action: AssistantAction) => void;
}

/**
 * At most one or two small, secondary buttons under an assistant reply --
 * never a toolbar. Clicking one is a direct frontend action (switch the
 * panel view); it never sends a fake chat message on the user's behalf.
 */
export function MessageActions({ actions, onAction }: MessageActionsProps) {
  if (actions.length === 0) return null;
  return (
    <div className="message-actions">
      {actions.map((action, index) => (
        <button
          key={`${action.type}-${action.filter ?? index}`}
          type="button"
          className="message-actions__button"
          onClick={() => onAction(action)}
        >
          {action.label}
        </button>
      ))}
    </div>
  );
}
