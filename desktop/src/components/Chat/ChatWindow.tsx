import { useCallback, useEffect, useState } from "react";
import { ChatHeader, type PanelView } from "./ChatHeader";
import { MessageList } from "./MessageList";
import { QuickActions } from "./QuickActions";
import { ChatInput } from "./ChatInput";
import { SettingsPanel, MemoryReviewPanel, CalendarSettingsScreen, GmailSettingsScreen } from "../Settings";
import { TaskPanel } from "../Tasks";
import { MemoryToast } from "./MemoryToast";
import { useChat } from "../../hooks/useChat";
import { useSettings } from "../../hooks/useSettings";
import { useMemories } from "../../hooks/useMemories";
import { useTasks } from "../../hooks/useTasks";
import { QUICK_ACTIONS } from "../../stores/chatSeed";
import type { AssistantAction, QuickAction } from "../../types/chat";
import type { TaskTabId } from "../../types/tasks";
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
  const [tasksTab, setTasksTab] = useState<TaskTabId>("today");
  const { settings, update } = useSettings();
  // Lifted here (not inside SettingsPanel) so the Settings summary and the
  // full review list share one loaded list instead of fetching twice.
  const memories = useMemories(true);
  // Lifted the same way: kept alive regardless of `view` so a chat-triggered
  // change can refresh it in the background, ready the moment the panel opens.
  const tasks = useTasks(view === "tasks");
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
    confirmPendingAction,
    cancelPendingAction,
    memoryNotice,
  } = useChat(settings.defaultCalendarId, settings.hiddenCalendarIds, {
    onOpenTasksTab: (tab) => {
      setTasksTab(tab as TaskTabId);
      setView("tasks");
    },
    onTasksChanged: () => void tasks.reload(),
  });

  // A save from passive extraction happened somewhere off-screen (Settings
  // and the review list only fetch once); bring the count and list back in
  // sync with what was actually learned. `reload` is stable (useCallback),
  // so this fires once per genuinely new notice, not on every render.
  const memoriesReload = memories.reload;
  useEffect(() => {
    if (memoryNotice) void memoriesReload();
  }, [memoryNotice, memoriesReload]);

  // "memory", "calendar" and "gmail" step back to "settings" (they were
  // opened from there); "settings" and "tasks" (a sibling top-level view,
  // not a Settings child) both step back to "chat".
  const back = useCallback(
    () =>
      setView((current) =>
        current === "settings" || current === "chat" || current === "tasks" ? "chat" : "settings",
      ),
    [],
  );

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

  // "Today" and "Tasks" open the panel directly rather than round-tripping
  // through chat as a fake message -- any future quick action that's
  // genuinely conversational still falls through to `sendQuickAction`.
  const handleQuickAction = useCallback(
    (action: QuickAction) => {
      if (action.id === "today" || action.id === "tasks") {
        setTasksTab("today");
        setView("tasks");
        return;
      }
      sendQuickAction(action);
    },
    [sendQuickAction],
  );

  // A button under an assistant reply is a direct frontend action, never a
  // fake chat message: the backend already computed which tab it means.
  const handleAssistantAction = useCallback((action: AssistantAction) => {
    if (action.type !== "open_task_panel") return;
    setTasksTab((action.filter as TaskTabId | undefined) ?? "today");
    setView("tasks");
  }, []);

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
          onOpenCalendar={() => setView("calendar")}
          onOpenGmail={() => setView("gmail")}
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
      ) : view === "calendar" ? (
        <CalendarSettingsScreen
          defaultCalendarId={settings.defaultCalendarId}
          onChangeDefaultCalendar={(id) => update({ defaultCalendarId: id })}
          hiddenCalendarIds={settings.hiddenCalendarIds}
          onChangeHiddenCalendarIds={(ids) => update({ hiddenCalendarIds: ids })}
        />
      ) : view === "gmail" ? (
        <GmailSettingsScreen />
      ) : view === "tasks" ? (
        <TaskPanel
          activeTab={tasksTab}
          onChangeTab={setTasksTab}
          today={tasks.today}
          upcoming={tasks.upcoming}
          completed={tasks.completed}
          isLoading={tasks.isLoading}
          error={tasks.error}
          onAddTask={tasks.addTask}
          onCompleteTask={tasks.complete}
          onReopenTask={tasks.reopen}
          onAddItem={tasks.addItem}
          onCompleteItem={tasks.completeItem}
          onReopenItem={tasks.reopenItem}
          onDeleteItem={tasks.deleteItem}
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
            onAction={handleAssistantAction}
            onConfirmPendingAction={confirmPendingAction}
            onCancelPendingAction={cancelPendingAction}
          />
          <QuickActions actions={QUICK_ACTIONS} onSelect={handleQuickAction} disabled={busy} />
          {memoryNotice && <MemoryToast content={memoryNotice.content} key={memoryNotice.at} />}
          <ChatInput onSend={send} disabled={busy} />
        </>
      )}
      <span className="chat-window__tail" aria-hidden="true" />
    </section>
  );
}
