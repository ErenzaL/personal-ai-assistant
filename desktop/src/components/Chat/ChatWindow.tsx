import { useCallback, useEffect, useState } from "react";
import { ChatHeader, type PanelView } from "./ChatHeader";
import { MessageList } from "./MessageList";
import { QuickActions } from "./QuickActions";
import { ChatInput } from "./ChatInput";
import { SettingsPanel, MemoryReviewPanel } from "../Settings";
import { MemoryToast } from "./MemoryToast";
import { useChat } from "../../hooks/useChat";
import { useSettings } from "../../hooks/useSettings";
import { useMemories } from "../../hooks/useMemories";
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
  // Lifted here (not inside SettingsPanel) so the Settings summary and the
  // full review list share one loaded list instead of fetching twice.
  const memories = useMemories(true);
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
    confirmProposal,
    cancelProposal,
    memoryNotice,
  } = useChat(settings.defaultCalendarId);

  // A save from passive extraction happened somewhere off-screen (Settings
  // and the review list only fetch once); bring the count and list back in
  // sync with what was actually learned. `reload` is stable (useCallback),
  // so this fires once per genuinely new notice, not on every render.
  const memoriesReload = memories.reload;
  useEffect(() => {
    if (memoryNotice) void memoriesReload();
  }, [memoryNotice, memoriesReload]);

  // "memory" steps back to "settings" (it was opened from there); anything
  // else steps back to "chat".
  const back = useCallback(() => setView((current) => (current === "memory" ? "settings" : "chat")), []);

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      if (view !== "chat") back();
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
        <SettingsPanel
          settings={settings}
          onUpdateSettings={update}
          onHistoryCleared={() => void newConversation()}
          memoryItemCount={memories.items.length}
          onOpenMemoryReview={() => setView("memory")}
          onClearMemories={memories.forgetAll}
          memoryError={memories.error}
        />
      ) : view === "memory" ? (
        <MemoryReviewPanel
          items={memories.items}
          isLoading={memories.isLoading}
          onEdit={memories.edit}
          onForget={memories.forget}
        />
      ) : (
        <>
          <MessageList
            messages={messages}
            emptyHint={isLoading ? "Loading…" : undefined}
            showTyping={isThinking}
            onRetry={canRetry ? retry : undefined}
            onConfirmProposal={(id, proposal) => void confirmProposal(id, proposal)}
            onCancelProposal={cancelProposal}
          />
          <QuickActions actions={QUICK_ACTIONS} onSelect={sendQuickAction} disabled={busy} />
          {memoryNotice && <MemoryToast content={memoryNotice.content} key={memoryNotice.at} />}
          <ChatInput onSend={send} disabled={busy} />
        </>
      )}
      <span className="chat-window__tail" aria-hidden="true" />
    </section>
  );
}
