import { useState } from "react";
import type { Message } from "../../types/chat";
import "./DraftEmailCard.css";

export interface DraftEmailCardProps {
  message: Message;
}

/** How long the "Copied" confirmation stays before reverting to "Copy". */
const COPIED_RESET_MS = 1800;

/**
 * A Gmail reply draft: the assistant's whole reply, shown as its own text --
 * never sent, never saved to Gmail. Copy is the only action there is.
 */
export function DraftEmailCard({ message }: DraftEmailCardProps) {
  const [copied, setCopied] = useState(false);

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(message.text);
      setCopied(true);
      window.setTimeout(() => setCopied(false), COPIED_RESET_MS);
    } catch {
      // Clipboard access can be denied by the OS; nothing to recover into,
      // the text is still fully selectable and copyable by hand below.
    }
  };

  return (
    <section className="draft-email" aria-label="Draft email reply">
      <span className="draft-email__heading">Draft reply</span>
      <p className="draft-email__body">{message.text}</p>
      <div className="draft-email__actions">
        <button type="button" className="settings-button" onClick={() => void copy()}>
          {copied ? "Copied" : "Copy"}
        </button>
      </div>
    </section>
  );
}
