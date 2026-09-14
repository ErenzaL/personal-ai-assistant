import { GeneralSection } from "./GeneralSection";
import { AssistantSection } from "./AssistantSection";
import { MemorySection } from "./MemorySection";
import { CalendarSection } from "./CalendarSection";
import { NotificationsSection } from "./NotificationsSection";
import { DataSection } from "./DataSection";
import { useMemories } from "../../hooks/useMemories";
import { clearConversations } from "../../services/api";
import type { AssistantSettings, SettingsPatch } from "../../types/settings";
import "./SettingsPanel.css";

export interface SettingsPanelProps {
  settings: AssistantSettings;
  onUpdateSettings: (patch: SettingsPatch) => void;
  /** Called after every conversation was deleted, so the chat starts afresh. */
  onHistoryCleared: () => void;
}

/** Settings body, shown in place of the chat transcript in the same window. */
export function SettingsPanel({ settings, onUpdateSettings, onHistoryCleared }: SettingsPanelProps) {
  const { items, isLoading, error, add, edit, forget, forgetAll } = useMemories(true);

  return (
    <div className="settings-panel">
      {error && <p className="settings-error">{error}</p>}
      <GeneralSection
        edgeActivation={settings.edgeActivation}
        onChangeEdgeActivation={(enabled) => onUpdateSettings({ edgeActivation: enabled })}
      />
      <AssistantSection settings={settings} onUpdate={onUpdateSettings} />
      <MemorySection items={items} isLoading={isLoading} onAdd={add} onEdit={edit} onForget={forget} />
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
      <DataSection
        onClearHistory={async () => {
          await clearConversations();
          onHistoryCleared();
        }}
        onClearMemories={async () => {
          await forgetAll();
        }}
      />
    </div>
  );
}
