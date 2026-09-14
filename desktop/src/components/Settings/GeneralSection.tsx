import { useEffect, useState } from "react";
import { Toggle } from "./Toggle";
import { getLoginItem, setLoginItem, type LoginItem } from "../../services/native";

export interface GeneralSectionProps {
  edgeActivation: boolean;
  onChangeEdgeActivation: (enabled: boolean) => void;
}

/**
 * Launch at login is macOS state, read live and written through the system,
 * so it always matches System Settings. Edge activation is a stored setting.
 */
export function GeneralSection({ edgeActivation, onChangeEdgeActivation }: GeneralSectionProps) {
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
      <Toggle
        label="Launch at login"
        checked={login?.enabled ?? false}
        disabled={!login?.supported}
        onChange={(enabled) => void toggleLogin(enabled)}
      />
      {login && !login.supported && (
        <p className="settings-hint">Available when Dully runs from the installed app.</p>
      )}
      {login?.requires_approval && (
        <p className="settings-hint">Waiting for approval in System Settings → General → Login Items.</p>
      )}
      {loginError && <p className="settings-hint">{loginError}</p>}
      <Toggle label="Show at the bottom-right edge" checked={edgeActivation} onChange={onChangeEdgeActivation} />
      {!edgeActivation && <p className="settings-hint">Use the menu bar icon to show Dully.</p>}
    </section>
  );
}
