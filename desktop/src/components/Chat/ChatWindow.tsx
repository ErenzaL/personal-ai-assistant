import { useCallback, useEffect, useState } from "react";
import { ChatHeader, type PanelView } from "./ChatHeader";
import { MessageList } from "./MessageList";
import { QuickActions } from "./QuickActions";
import { ChatInput } from "./ChatInput";
import { SettingsPanel } from "../Settings";
import { useChat } from "../../hooks/useChat";
import { useSettings } from "../../hooks/useSettings";
import { QUICK_ACTIONS } from "../../stores/chatSeed";
import "./ChatWindow.css";

export interface ChatWindowProps {
  onClose: () => void;
}

/**
 * The panel above the mascot. Holds two views in one window: the chat
 * transcript and a compact settings page. Escape closes settings first,
 * then the panel.
 */
export function ChatWindow({ onClose }: ChatWindowProps) {
  const [view, setView] = useState<PanelView>("chat");
  const { settings, update } = useSettings();
  const {
    messages,
    isLoading,
    isReplying,
    isThinking,
    status,
    canRetry,
    send,
    sendQuickAction,
    retry,
    newConversation,
  } = useChat();

  const back = useCallback(() => setView("chat"), []);

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      if (view === "settings") back();
      else onClose();
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [back, onClose, view]);

  const busy = isLoading || isReplying;

  return (
    <section className="chat-window" role="dialog" aria-label={`${settings.assistantName} panel`}>
      <ChatHeader
        name={settings.assistantName}
        status={status}
        view={view}
        onNewChat={() => void newConversation()}
        onOpenSettings={() => setView("settings")}
        onBack={back}
        onClose={onClose}
      />
      {view === "settings" ? (
        <SettingsPanel settings={settings} onUpdateSettings={update} />
      ) : (
        <>
          <MessageList
            messages={messages}
            emptyHint={isLoading ? "Loading…" : undefined}
            showTyping={isThinking}
            onRetry={canRetry ? retry : undefined}
          />
          <QuickActions actions={QUICK_ACTIONS} onSelect={sendQuickAction} disabled={busy} />
          <ChatInput onSend={send} disabled={busy} />
        </>
      )}
      <span className="chat-window__tail" aria-hidden="true" />
    </section>
  );
}
