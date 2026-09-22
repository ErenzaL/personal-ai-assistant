import type { BackendStatus } from "../../types/chat";
import "./ChatHeader.css";

export type PanelView = "chat" | "settings" | "memory" | "calendar" | "gmail" | "tasks";

export interface ChatHeaderProps {
  name: string;
  status: BackendStatus;
  view: PanelView;
  onNewChat: () => void;
  onOpenSettings: () => void;
  onBack: () => void;
  onClose: () => void;
}

const TITLE: Record<Exclude<PanelView, "chat">, string> = {
  settings: "Settings",
  memory: "What Dully remembers",
  calendar: "Calendar",
  gmail: "Gmail",
  tasks: "Tasks",
};

/** Every non-chat view steps back to Settings, its one parent, except
 *  Settings itself and Tasks (a sibling top-level view), which step back
 *  to chat. */
const BACK_LABEL: Record<Exclude<PanelView, "chat">, string> = {
  settings: "Back to chat",
  memory: "Back to Settings",
  calendar: "Back to Settings",
  gmail: "Back to Settings",
  tasks: "Back to chat",
};

const STATUS_LABEL: Record<BackendStatus, string> = {
  unknown: "Connecting…",
  online: "Online",
  offline: "Backend offline",
};

/** Title bar of the panel. Dragging it moves the whole window. */
export function ChatHeader({ name, status, view, onNewChat, onOpenSettings, onBack, onClose }: ChatHeaderProps) {
  const inChat = view === "chat";
  return (
    <header className="chat-header" data-tauri-drag-region>
      {!inChat && (
        <button
          type="button"
          className="chat-header__button"
          onClick={onBack}
          aria-label={inChat ? "Back to chat" : BACK_LABEL[view]}
          title="Back"
        >
          ‹
        </button>
      )}
      <div className="chat-header__titles" data-tauri-drag-region>
        <span className="chat-header__name" data-tauri-drag-region>
          {inChat ? name : TITLE[view]}
        </span>
        {inChat && (
          <span className={`chat-header__status chat-header__status--${status}`} data-tauri-drag-region>
            {STATUS_LABEL[status]}
          </span>
        )}
      </div>
      <div className="chat-header__actions">
        {inChat && (
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
