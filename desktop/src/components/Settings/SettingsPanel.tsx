import { GeneralSection } from "./GeneralSection";
import { AssistantSection } from "./AssistantSection";
import { MemorySection } from "./MemorySection";
import { CalendarSection } from "./CalendarSection";
import { NotificationsSection } from "./NotificationsSection";
import { GmailSection } from "./GmailSection";
import { DataSection } from "./DataSection";
import { clearConversations } from "../../services/api";
import type { AssistantSettings, SettingsPatch } from "../../types/settings";
import "./SettingsPanel.css";

export interface SettingsPanelProps {
  settings: AssistantSettings;
  onUpdateSettings: (patch: SettingsPatch) => void;
  /** Called after every conversation was deleted, so the chat starts afresh. */
  onHistoryCleared: () => void;
  memoryItemCount: number;
  onOpenMemoryReview: () => void;
  onClearMemories: () => Promise<boolean>;
  memoryError: string | null;
}

/** Settings body, shown in place of the chat transcript in the same window. */
export function SettingsPanel({
  settings,
  onUpdateSettings,
  onHistoryCleared,
  memoryItemCount,
  onOpenMemoryReview,
  onClearMemories,
  memoryError,
}: SettingsPanelProps) {
  return (
    <div className="settings-panel">
      {memoryError && <p className="settings-error">{memoryError}</p>}
      <GeneralSection
        edgeActivation={settings.edgeActivation}
        onChangeEdgeActivation={(enabled) => onUpdateSettings({ edgeActivation: enabled })}
      />
      <AssistantSection settings={settings} onUpdate={onUpdateSettings} />
      <MemorySection
        enabled={settings.memoryEnabled}
        onChangeEnabled={(enabled) => onUpdateSettings({ memoryEnabled: enabled })}
        itemCount={memoryItemCount}
        onOpenReview={onOpenMemoryReview}
      />
      <CalendarSection
        defaultCalendarId={settings.defaultCalendarId}
        onChangeDefaultCalendar={(id) => onUpdateSettings({ defaultCalendarId: id })}
        reminderMinutes={settings.reminderMinutes}
        onChangeReminderMinutes={(minutes) => onUpdateSettings({ reminderMinutes: minutes })}
      />
      <NotificationsSection
        enabled={settings.calendarNotifications}
        onChange={(enabled) => onUpdateSettings({ calendarNotifications: enabled })}
      />
      <GmailSection />
      <DataSection
        onClearHistory={async () => {
          await clearConversations();
          onHistoryCleared();
        }}
        onClearMemories={async () => {
          await onClearMemories();
        }}
      />
    </div>
  );
}
