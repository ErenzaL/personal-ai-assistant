import { useEffect, useState } from "react";
import { ProfileCard } from "./ProfileCard";
import { GeneralSection } from "./GeneralSection";
import { MemorySection } from "./MemorySection";
import { ConnectionsSection } from "./ConnectionsSection";
import { NotificationsSection } from "./NotificationsSection";
import { DataSection } from "./DataSection";
import { clearConversations } from "../../services/api";
import { getAppVersion } from "../../services/native";
import type { AssistantSettings, SettingsPatch } from "../../types/settings";
import "./SettingsPanel.css";

export interface SettingsPanelProps {
  settings: AssistantSettings;
  onUpdateSettings: (patch: SettingsPatch) => void;
  /** Called after every conversation was deleted, so the chat starts afresh. */
  onHistoryCleared: () => void;
  memoryItemCount: number;
  onOpenMemoryReview: () => void;
  onOpenCalendar: () => void;
  onOpenGmail: () => void;
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
  onOpenCalendar,
  onOpenGmail,
  onClearMemories,
  memoryError,
}: SettingsPanelProps) {
  const [version, setVersion] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    void getAppVersion().then((v) => alive && setVersion(v));
    return () => {
      alive = false;
    };
  }, []);

  return (
    <div className="settings-panel">
      {memoryError && <p className="settings-error">{memoryError}</p>}
      <ProfileCard settings={settings} onUpdate={onUpdateSettings} />
      <GeneralSection
        settings={settings}
        onChangeEdgeActivation={(enabled) => onUpdateSettings({ edgeActivation: enabled })}
        onChangeResponseStyle={(style) => onUpdateSettings({ responseStyle: style })}
      />
      <MemorySection
        enabled={settings.memoryEnabled}
        onChangeEnabled={(enabled) => onUpdateSettings({ memoryEnabled: enabled })}
        itemCount={memoryItemCount}
        onOpenReview={onOpenMemoryReview}
      />
      <ConnectionsSection onOpenCalendar={onOpenCalendar} onOpenGmail={onOpenGmail} />
      <NotificationsSection
        enabled={settings.calendarNotifications}
        onChange={(enabled) => onUpdateSettings({ calendarNotifications: enabled })}
        reminderMinutes={settings.reminderMinutes}
        onChangeReminderMinutes={(minutes) => onUpdateSettings({ reminderMinutes: minutes })}
      />
      <DataSection
        onClearHistory={async () => {
          await clearConversations();
          onHistoryCleared();
        }}
        onClearMemories={async () => {
          await onClearMemories();
        }}
      />
      {version && <p className="settings-version">Dully {version}</p>}
    </div>
  );
}
