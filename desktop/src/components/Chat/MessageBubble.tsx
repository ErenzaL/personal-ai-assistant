import Markdown, { type Components } from "react-markdown";
import type { Message } from "../../types/chat";
import "./MessageBubble.css";

export interface MessageBubbleProps {
  message: Message;
}

function formatTime(iso: string): string {
  return new Date(iso).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

/**
 * Markdown elements allowed in assistant replies. Anything else (headings,
 * tables, images, raw HTML) is unwrapped to plain text so the small bubble
 * never gets oversized structure.
 */
const ALLOWED = ["p", "strong", "em", "del", "code", "pre", "ul", "ol", "li", "a", "br", "blockquote", "hr"];

const components: Components = {
  // Links: show as a link but don't navigate the panel. Opening in the
  // system browser needs Tauri's opener plugin (later).
  a: ({ href, children }) => (
    <a href={href} title={href} onClick={(event) => event.preventDefault()}>
      {children}
    </a>
  ),
};

/**
 * One message. Assistant text is rendered as Markdown; user and system text
 * stay verbatim with line breaks preserved. While streaming, a blinking caret
 * follows the text and the timestamp is hidden.
 */
export function MessageBubble({ message }: MessageBubbleProps) {
  const streaming = message.streaming === true;
  const isMarkdown = message.role === "assistant";
  return (
    <div className={`bubble bubble--${message.role}${streaming ? " bubble--streaming" : ""}`}>
      {isMarkdown ? (
        <div className="bubble__text bubble__markdown">
          <Markdown allowedElements={ALLOWED} unwrapDisallowed components={components}>
            {message.text}
          </Markdown>
        </div>
      ) : (
        <p className="bubble__text">{message.text}</p>
      )}
      {!streaming && (
        <time className="bubble__time" dateTime={message.sentAt}>
          {formatTime(message.sentAt)}
        </time>
      )}
    </div>
  );
}
