import { MemorySection } from "./MemorySection";
import { AssistantSection } from "./AssistantSection";
import { useMemories } from "../../hooks/useMemories";
import type { AssistantSettings } from "../../types/settings";
import "./SettingsPanel.css";

export interface SettingsPanelProps {
  settings: AssistantSettings;
  onUpdateSettings: (patch: { assistantName?: string; responseStyle?: string }) => void;
}

/** Settings body, shown in place of the chat transcript in the same window. */
export function SettingsPanel({ settings, onUpdateSettings }: SettingsPanelProps) {
  const { items, isLoading, error, add, edit, forget, forgetAll } = useMemories(true);

  return (
    <div className="settings-panel">
      {error && <p className="settings-error">{error}</p>}
      <MemorySection
        items={items}
        isLoading={isLoading}
        onAdd={add}
        onEdit={edit}
        onForget={forget}
        onForgetAll={forgetAll}
      />
      <AssistantSection settings={settings} onUpdate={onUpdateSettings} />
    </div>
  );
}
