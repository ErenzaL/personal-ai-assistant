import { useEffect, useState } from "react";
import { Toggle } from "./Toggle";
import { getLoginItem, setLoginItem, type LoginItem } from "../../services/native";
import { STYLE_LABEL } from "../../types/settings";
import type { AssistantSettings } from "../../types/settings";

export interface GeneralSectionProps {
  settings: AssistantSettings;
  onChangeEdgeActivation: (enabled: boolean) => void;
  onChangeResponseStyle: (style: string) => void;
}

/**
 * "Open at login" is macOS state, read live and written through the system,
 * so it always matches System Settings. The rest are stored settings.
 */
export function GeneralSection({ settings, onChangeEdgeActivation, onChangeResponseStyle }: GeneralSectionProps) {
  const [login, setLogin] = useState<LoginItem | null>(null);
  const [loginError, setLoginError] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    getLoginItem()
      .then((state) => alive && setLogin(state))
      .catch(() => alive && setLogin({ supported: false, enabled: false, requires_approval: false }));
    return () => {
      alive = false;
    };
  }, []);

  const toggleLogin = async (enabled: boolean) => {
    try {
      setLogin(await setLoginItem(enabled));
      setLoginError(null);
    } catch (err) {
      setLoginError(typeof err === "string" ? err : "Could not change the login item.");
    }
  };

  return (
    <section className="settings-section">
      <div className="settings-section__head">
        <h3 className="settings-section__title">General</h3>
      </div>
      <div className="settings-card">
        <Toggle
          label="Open Dully at login"
          checked={login?.enabled ?? false}
          disabled={!login?.supported}
          onChange={(enabled) => void toggleLogin(enabled)}
        />
        <Toggle
          label="Pin to bottom-right corner"
          checked={settings.edgeActivation}
          onChange={onChangeEdgeActivation}
        />
        <label className="settings-field">
          <span className="settings-field__label">Response style</span>
          <select
            className="settings-field__input"
            value={settings.responseStyle}
            onChange={(event) => onChangeResponseStyle(event.target.value)}
          >
            {settings.availableStyles.map((style) => (
              <option key={style} value={style}>
                {STYLE_LABEL[style] ?? style}
              </option>
            ))}
          </select>
        </label>
      </div>
      {login && !login.supported && (
        <p className="settings-hint">Available when Dully runs from the installed app.</p>
      )}
      {login?.requires_approval && (
        <p className="settings-hint">Waiting for approval in System Settings → General → Login Items.</p>
      )}
      {loginError && <p className="settings-hint">{loginError}</p>}
      {!settings.edgeActivation && <p className="settings-hint">Use the menu bar icon to show Dully.</p>}
    </section>
  );
}
