import { useGmail } from "../../hooks/useGmail";

/**
 * Connect/disconnect only, read-only Gmail access. No inbox content lives
 * in this app yet -- this section exists purely to establish and show the
 * connection, matching the current scope of the Gmail integration itself.
 */
export function GmailSection() {
  const { status, isBusy, error, connect, disconnect } = useGmail(true);

  const connected = status?.connected ?? false;
  const label = status ? (connected ? "Connected" : "Not connected") : "Checking…";
  const tone = status ? (connected ? "allowed" : "blocked") : "unknown";

  return (
    <section className="settings-section">
      <div className="settings-section__head">
        <h3 className="settings-section__title">Gmail</h3>
      </div>

      <div className="settings-field">
        <span className="settings-field__label">Status</span>
        <span className={`calendar-status calendar-status--${tone}`}>{label}</span>
      </div>

      {status?.detail && <p className="settings-hint">{status.detail}</p>}
      {error && <p className="settings-error">{error}</p>}

      <button
        type="button"
        className="settings-button settings-section__footer"
        onClick={() => void (connected ? disconnect() : connect())}
        disabled={isBusy}
      >
        {isBusy ? "Working…" : connected ? "Disconnect Gmail" : "Connect Gmail"}
      </button>
    </section>
  );
}
