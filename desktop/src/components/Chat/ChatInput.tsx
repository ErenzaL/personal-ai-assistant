import { useEffect, useRef, useState, type KeyboardEvent } from "react";
import "./ChatInput.css";

export interface ChatInputProps {
  onSend: (text: string) => void;
  disabled?: boolean;
}

/** Tallest the textarea grows before it scrolls internally, in px. */
const MAX_HEIGHT = 120;

/**
 * Multi-line input. Enter sends, Shift+Enter inserts a newline. Enter is
 * ignored while an IME composition (e.g. Korean input) is in progress.
 */
export function ChatInput({ onSend, disabled = false }: ChatInputProps) {
  const [value, setValue] = useState("");
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    textareaRef.current?.focus();
  }, []);

  // Grow with content up to MAX_HEIGHT, then scroll.
  useEffect(() => {
    const el = textareaRef.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, MAX_HEIGHT)}px`;
  }, [value]);

  const canSend = value.trim().length > 0 && !disabled;

  const submit = () => {
    if (!canSend) return;
    onSend(value);
    setValue("");
    textareaRef.current?.focus();
  };

  const onKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key !== "Enter" || event.shiftKey || event.nativeEvent.isComposing) return;
    event.preventDefault();
    submit();
  };

  return (
    <form
      className="chat-input"
      onSubmit={(event) => {
        event.preventDefault();
        submit();
      }}
    >
      <textarea
        ref={textareaRef}
        className="chat-input__textarea"
        value={value}
        onChange={(event) => setValue(event.target.value)}
        onKeyDown={onKeyDown}
        placeholder="Type a message…"
        title="Enter to send, Shift+Enter for a new line"
        rows={1}
        aria-label="Message"
      />
      <button type="submit" className="chat-input__send" disabled={!canSend} aria-label="Send">
        ↑
      </button>
    </form>
  );
}
