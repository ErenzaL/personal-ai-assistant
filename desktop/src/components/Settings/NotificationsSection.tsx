import { Toggle } from "./Toggle";

export interface NotificationsSectionProps {
  enabled: boolean;
  onChange: (enabled: boolean) => void;
}

export function NotificationsSection({ enabled, onChange }: NotificationsSectionProps) {
  return (
    <section className="settings-section">
      <div className="settings-section__head">
        <h3 className="settings-section__title">Notifications</h3>
      </div>
      <Toggle label="Calendar reminders" checked={enabled} onChange={onChange} />
      {!enabled && <p className="settings-hint">No banners or popups before events.</p>}
    </section>
  );
}
