import { useEffect, useLayoutEffect, useRef } from "react";
import { MessageBubble } from "./MessageBubble";
import type { Message } from "../../types/chat";
import "./MessageList.css";

export interface MessageListProps {
  messages: Message[];
  /** Shown centered when there are no messages. */
  emptyHint?: string;
  /** Show the "..." indicator (waiting for the first token). */
  showTyping?: boolean;
  /** When set, a Retry button is shown under the last (failed) message. */
  onRetry?: () => void;
}

/** How close to the bottom (px) the user must be for auto-follow to stay on. */
const FOLLOW_THRESHOLD = 48;

/**
 * Scrollable transcript. Follows new content while the user is at the bottom;
 * if they scroll up to read, streaming text no longer yanks them down. A new
 * message count (the user just sent something) always re-engages follow.
 */
export function MessageList({ messages, emptyHint, showTyping = false, onRetry }: MessageListProps) {
  const listRef = useRef<HTMLDivElement>(null);
  const follow = useRef(true);

  const last = messages[messages.length - 1];
  const lastText = last?.text ?? "";

  const onScroll = () => {
    const el = listRef.current;
    if (!el) return;
    follow.current = el.scrollHeight - el.scrollTop - el.clientHeight <= FOLLOW_THRESHOLD;
  };

  // A new message always snaps to the bottom.
  useEffect(() => {
    follow.current = true;
  }, [messages.length]);

  // Streamed text, typing indicator, and retry button all grow the list;
  // keep the bottom in view when following. Layout effect avoids a visible
  // one-frame lag behind fast token streams.
  useLayoutEffect(() => {
    const el = listRef.current;
    if (el && follow.current) el.scrollTop = el.scrollHeight;
  }, [messages.length, lastText, showTyping, onRetry]);

  return (
    <div className="message-list" role="log" aria-live="polite" ref={listRef} onScroll={onScroll}>
      {messages.length === 0 && emptyHint && <p className="message-list__empty">{emptyHint}</p>}
      {messages.map((message) => (
        <MessageBubble key={message.id} message={message} />
      ))}
      {onRetry && (
        <button type="button" className="message-list__retry" onClick={onRetry}>
          Retry
        </button>
      )}
      {showTyping && (
        <div className="message-list__typing" aria-label="Assistant is thinking">
          <span />
          <span />
          <span />
        </div>
      )}
    </div>
  );
}
