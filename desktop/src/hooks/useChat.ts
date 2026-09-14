import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { BackendStatus, Conversation, Message, MessageRole, QuickAction } from "../types/chat";
import {
  ApiError,
  createConversation,
  describeApiError,
  getCurrentConversation,
  streamChatMessage,
  type MessageDto,
} from "../services/api";
import { greeting } from "../stores/chatSeed";

function makeMessage(role: MessageRole, text: string, extra: Partial<Message> = {}): Message {
  return {
    id: crypto.randomUUID(),
    role,
    text,
    sentAt: new Date().toISOString(),
    ...extra,
  };
}

function fromDto(dto: MessageDto): Message {
  return { id: dto.id, role: dto.role, text: dto.content, sentAt: dto.created_at };
}

/** Local-only assistant greeting for an empty conversation. */
function greetingMessage(): Message {
  return makeMessage("assistant", greeting(), { local: true });
}

interface PendingTurn {
  text: string;
  conversationId: string;
  /** Local id of the optimistic user bubble; replaced by the server id on `meta`. */
  userId: string;
  /** Server id once known; sent on retry so the backend doesn't save it twice. */
  serverUserId?: string;
}

/**
 * Chat state persisted through the backend.
 *
 * - On mount, loads the current conversation (survives app restarts); an
 *   empty one opens with a local greeting from the assistant.
 * - `send` shows the user message at once, streams the reply into an
 *   assistant bubble, and relies on the backend to store both.
 * - On failure the partial text stays, a local notice explains, and `retry`
 *   re-sends the same turn (with the saved user message id) after discarding
 *   the partial reply, so nothing is stored or shown twice.
 * - `newConversation` starts a fresh one and makes it current.
 * - Context sent to the LLM is chosen on the backend (recent tail only).
 */
export function useChat() {
  const [conversation, setConversation] = useState<Conversation | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [isReplying, setIsReplying] = useState(false);
  const [status, setStatus] = useState<BackendStatus>("unknown");
  const [failed, setFailed] = useState<PendingTurn | null>(null);
  const mounted = useRef(true);
  const inFlight = useRef<AbortController | null>(null);

  useEffect(() => {
    mounted.current = true;
    void (async () => {
      try {
        const { conversation: c, messages: m } = await getCurrentConversation();
        if (!mounted.current) return;
        setConversation({ id: c.id, title: c.title });
        setMessages(m.length > 0 ? m.map(fromDto) : [greetingMessage()]);
        setStatus("online");
      } catch (error) {
        if (!mounted.current) return;
        setStatus("offline");
        setMessages([makeMessage("system", describeApiError(error), { local: true })]);
      } finally {
        if (mounted.current) setIsLoading(false);
      }
    })();
    return () => {
      mounted.current = false;
      inFlight.current?.abort();
    };
  }, []);

  const isThinking = useMemo(
    () => isReplying && !messages.some((m) => m.streaming),
    [isReplying, messages],
  );

  const deliver = useCallback(async (turn: PendingTurn) => {
    const controller = new AbortController();
    inFlight.current = controller;
    setIsReplying(true);
    setFailed(null);

    let assistantId: string | null = null;
    let serverUserId = turn.serverUserId;
    const finish = (finalId?: string) => {
      if (assistantId === null) return;
      const id = assistantId;
      setMessages((prev) =>
        prev.map((m) => (m.id === id ? { ...m, id: finalId || m.id, streaming: false } : m)),
      );
    };

    try {
      const { assistantMessageId } = await streamChatMessage(
        { message: turn.text, conversationId: turn.conversationId, userMessageId: turn.serverUserId },
        {
          signal: controller.signal,
          onMeta: ({ userMessageId }) => {
            if (!mounted.current) return;
            serverUserId = userMessageId;
            // Swap the optimistic id for the stored one.
            setMessages((prev) => prev.map((m) => (m.id === turn.userId ? { ...m, id: userMessageId } : m)));
          },
          onDelta: (delta) => {
            if (!mounted.current) return;
            if (assistantId === null) {
              const created = makeMessage("assistant", delta, { streaming: true });
              assistantId = created.id;
              setMessages((prev) => [...prev, created]);
            } else {
              const id = assistantId;
              setMessages((prev) => prev.map((m) => (m.id === id ? { ...m, text: m.text + delta } : m)));
            }
          },
        },
      );
      if (!mounted.current) return;
      finish(assistantMessageId);
      setStatus("online");
    } catch (error) {
      if (!mounted.current) return;
      if (error instanceof ApiError && error.kind === "aborted") return;
      finish();
      setMessages((prev) => [...prev, makeMessage("system", describeApiError(error), { local: true })]);
      setFailed({ ...turn, userId: serverUserId ?? turn.userId, serverUserId });
      if (error instanceof ApiError && error.kind === "offline") setStatus("offline");
    } finally {
      if (inFlight.current === controller) inFlight.current = null;
      if (mounted.current) setIsReplying(false);
    }
  }, []);

  const send = useCallback(
    (text: string) => {
      const trimmed = text.trim();
      if (!trimmed || isReplying || isLoading || !conversation) return;
      const user = makeMessage("user", trimmed);
      // Drop stale local notices (errors); the greeting bubble stays.
      setMessages((prev) => [...prev.filter((m) => !(m.local && m.role === "system")), user]);
      void deliver({ text: trimmed, conversationId: conversation.id, userId: user.id });
    },
    [conversation, deliver, isLoading, isReplying],
  );

  const sendQuickAction = useCallback((action: QuickAction) => send(action.prompt), [send]);

  /** Re-send the failed turn. Drops the partial reply and the notice first. */
  const retry = useCallback(() => {
    if (!failed || isReplying) return;
    setMessages((prev) => {
      const idx = prev.findIndex((m) => m.id === failed.userId);
      return idx === -1 ? prev : prev.slice(0, idx + 1);
    });
    void deliver(failed);
  }, [deliver, failed, isReplying]);

  /** Start a fresh conversation. Any in-flight reply is cancelled. */
  const newConversation = useCallback(async () => {
    inFlight.current?.abort();
    setFailed(null);
    try {
      const created = await createConversation();
      if (!mounted.current) return;
      setConversation({ id: created.id, title: created.title });
      setMessages([greetingMessage()]);
      setStatus("online");
    } catch (error) {
      if (!mounted.current) return;
      setMessages((prev) => [...prev, makeMessage("system", describeApiError(error), { local: true })]);
      if (error instanceof ApiError && error.kind === "offline") setStatus("offline");
    } finally {
      if (mounted.current) setIsReplying(false);
    }
  }, []);

  return {
    conversation,
    messages,
    isLoading,
    isReplying,
    isThinking,
    status,
    canRetry: failed !== null && !isReplying,
    send,
    sendQuickAction,
    retry,
    newConversation,
  };
}
