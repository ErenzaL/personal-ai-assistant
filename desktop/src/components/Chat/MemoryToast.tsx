import { useEffect, useState } from "react";
import "./MemoryToast.css";

export interface MemoryToastProps {
  /** The fact that was saved. Changing this value (even to the same text
   *  again) restarts the fade-out timer. */
  content: string;
  /** How long the toast stays before fading, in ms. */
  durationMs?: number;
}

/**
 * The subtle "✓ Remembered: ..." confirmation for requirement 9: a small
 * pill above the input, not a chat message, so it never reads like part of
 * the conversation. Disappears on its own; nothing to dismiss.
 */
export function MemoryToast({ content, durationMs = 4000 }: MemoryToastProps) {
  const [visible, setVisible] = useState(true);

  useEffect(() => {
    setVisible(true);
    const timer = window.setTimeout(() => setVisible(false), durationMs);
    return () => window.clearTimeout(timer);
  }, [content, durationMs]);

  return (
    <div className={visible ? "memory-toast memory-toast--visible" : "memory-toast"} role="status" aria-live="polite">
      <span className="memory-toast__check" aria-hidden="true">
        ✓
      </span>
      <span className="memory-toast__text">
        Remembered: <strong>{content}</strong>
      </span>
    </div>
  );
}
