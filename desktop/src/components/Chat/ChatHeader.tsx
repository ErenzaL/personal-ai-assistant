import type { BackendStatus } from "../../types/chat";
import "./ChatHeader.css";

export type PanelView = "chat" | "settings";

export interface ChatHeaderProps {
  name: string;
  status: BackendStatus;
  view: PanelView;
  onNewChat: () => void;
  onOpenSettings: () => void;
  onBack: () => void;
  onClose: () => void;
}

const STATUS_LABEL: Record<BackendStatus, string> = {
  unknown: "Connecting…",
  online: "Online",
  offline: "Backend offline",
};

/** Title bar of the panel. Dragging it moves the whole window. */
export function ChatHeader({ name, status, view, onNewChat, onOpenSettings, onBack, onClose }: ChatHeaderProps) {
  const inSettings = view === "settings";
  return (
    <header className="chat-header" data-tauri-drag-region>
      {inSettings && (
        <button type="button" className="chat-header__button" onClick={onBack} aria-label="Back to chat" title="Back">
          ‹
        </button>
      )}
      <div className="chat-header__titles" data-tauri-drag-region>
        <span className="chat-header__name" data-tauri-drag-region>
          {inSettings ? "Settings" : name}
        </span>
        {!inSettings && (
          <span className={`chat-header__status chat-header__status--${status}`} data-tauri-drag-region>
            {STATUS_LABEL[status]}
          </span>
        )}
      </div>
      <div className="chat-header__actions">
        {!inSettings && (
          <>
            <button
              type="button"
              className="chat-header__button"
              onClick={onOpenSettings}
              aria-label="Settings"
              title="Settings"
            >
              ⚙
            </button>
            <button
              type="button"
              className="chat-header__button"
              onClick={onNewChat}
              aria-label="New chat"
              title="New chat"
            >
              +
            </button>
          </>
        )}
        <button
          type="button"
          className="chat-header__button chat-header__close"
          onClick={onClose}
          aria-label="Close"
          title="Close (Esc)"
        >
          ×
        </button>
      </div>
    </header>
  );
}
