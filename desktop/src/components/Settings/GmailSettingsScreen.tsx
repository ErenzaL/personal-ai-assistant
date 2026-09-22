import { useGmail } from "../../hooks/useGmail";

/**
 * Connect/disconnect only, read-only Gmail access. No inbox content lives
 * in this app -- this screen exists purely to establish and show the
 * connection, matching the current scope of the Gmail integration itself.
 */
export function GmailSettingsScreen() {
  const { status, isBusy, error, connect, disconnect } = useGmail(true);
  const connected = status?.connected ?? false;

  return (
    <div className="settings-panel">
      {connected ? (
        <>
          <div className="settings-account-card">
            <span className="settings-avatar" aria-hidden="true">
              {(status?.email ?? "G").charAt(0).toUpperCase()}
            </span>
            <div className="settings-account-card__body">
              <span className="settings-account-card__title">{status?.email ?? "Connected account"}</span>
              <span className="calendar-status calendar-status--allowed">Connected</span>
            </div>
          </div>

          <div className="settings-section">
            <div className="settings-card settings-card--danger">
              <button
                type="button"
                className="settings-link settings-link--danger settings-link--block"
                onClick={() => void disconnect()}
                disabled={isBusy}
              >
                {isBusy ? "Working…" : "Disconnect Gmail"}
              </button>
            </div>
            <p className="settings-hint">Dully will stop reading your inbox. You can reconnect anytime.</p>
          </div>
        </>
      ) : (
        <div className="settings-section">
          <div className="settings-card">
            <div className="settings-card__head">
              <span className="settings-card__title">Gmail</span>
              <span className="calendar-status calendar-status--blocked">
                {status ? "Not connected" : "Checking…"}
              </span>
            </div>
            <button type="button" className="settings-button" onClick={() => void connect()} disabled={isBusy}>
              {isBusy ? "Working…" : "Connect Gmail"}
            </button>
          </div>
          {status?.detail && <p className="settings-hint">{status.detail}</p>}
        </div>
      )}
      {error && <p className="settings-error">{error}</p>}
    </div>
  );
}
