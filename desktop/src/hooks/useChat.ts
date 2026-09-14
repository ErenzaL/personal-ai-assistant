import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { BackendStatus, Conversation, Message, MessageRole, QuickAction } from "../types/chat";
import {
  ApiError,
  createConversation,
  describeApiError,
  getCurrentConversation,
  streamChatMessage,
  type ChatToolResult,
  type MessageDto,
} from "../services/api";
import { CALENDAR_PROPOSE, canRun, proposeEvent, runClientTool } from "../services/clientTools";
import { createEvent, isCalendarError } from "../services/calendar";
import type { EventProposal } from "../types/calendar";
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
/** How long to wait for a backend that is still starting: 12 tries, 1.5 s apart
 *  (the packaged backend unpacks itself first). */
const STARTUP_RETRIES = 12;
const STARTUP_RETRY_MS = 1500;

export function useChat(defaultCalendarId: string | null = null) {
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
    let attempts = 0;
    let retry: number | undefined;
    const load = async () => {
      try {
        const { conversation: c, messages: m } = await getCurrentConversation();
        if (!mounted.current) return;
        setConversation({ id: c.id, title: c.title });
        setMessages(m.length > 0 ? m.map(fromDto) : [greetingMessage()]);
        setStatus("online");
        setIsLoading(false);
      } catch (error) {
        if (!mounted.current) return;
        // The backend is started with the app and takes a few seconds to
        // answer; keep trying quietly before calling it offline.
        if (error instanceof ApiError && error.kind === "offline" && attempts < STARTUP_RETRIES) {
          attempts += 1;
          retry = window.setTimeout(() => void load(), STARTUP_RETRY_MS);
          return;
        }
        setStatus("offline");
        setMessages([makeMessage("system", describeApiError(error), { local: true })]);
        setIsLoading(false);
      }
    };
    void load();
    return () => {
      mounted.current = false;
      window.clearTimeout(retry);
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
    // Attached to the assistant message once it finishes, so the card appears
    // under the sentence that introduces it.
    let pendingProposal: EventProposal | null = null;
    const finish = (finalId?: string) => {
      if (assistantId === null) return;
      const id = assistantId;
      setMessages((prev) =>
        prev.map((m) =>
          m.id === id
            ? {
                ...m,
                id: finalId || m.id,
                streaming: false,
                ...(pendingProposal ? { proposal: pendingProposal } : {}),
              }
            : m,
        ),
      );
    };

    const options = {
      signal: controller.signal,
      onMeta: ({ userMessageId }: { userMessageId: string }) => {
        if (!mounted.current) return;
        serverUserId = userMessageId;
        // Swap the optimistic id for the stored one.
        setMessages((prev) => prev.map((m) => (m.id === turn.userId ? { ...m, id: userMessageId } : m)));
      },
      onDelta: (delta: string) => {
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
    };

    try {
      let outcome = await streamChatMessage(
        { message: turn.text, conversationId: turn.conversationId, userMessageId: turn.serverUserId },
        options,
      );

      // The backend can ask this app to run a tool it cannot reach itself
      // (the calendar lives in the native layer). Run it, then ask again
      // with the result. One round trip only, so this cannot loop.
      // A proposed event is prepared here, then sent back so the assistant
      // can introduce it in its own words. The card renders under that
      // message; nothing is written until Confirm.
      if (outcome.kind === "client_tool" && outcome.name === CALENDAR_PROPOSE) {
        const prepared = await proposeEvent(outcome.arguments, defaultCalendarId);
        if (!mounted.current) return;
        if ("error" in prepared) {
          pendingProposal = null;
          outcome = await streamChatMessage(
            {
              message: turn.text,
              conversationId: turn.conversationId,
              userMessageId: serverUserId ?? turn.serverUserId,
              toolResults: [
                {
                  name: outcome.name,
                  result: {
                    ok: false,
                    tool: outcome.name,
                    error: { code: "proposal_failed", message: prepared.error },
                  },
                },
              ],
            },
            options,
          );
        } else {
          pendingProposal = prepared.proposal;
          outcome = await streamChatMessage(
            {
              message: turn.text,
              conversationId: turn.conversationId,
              userMessageId: serverUserId ?? turn.serverUserId,
              toolResults: [
                {
                  name: outcome.name,
                  result: {
                    ok: true,
                    tool: outcome.name,
                    data: { proposal: prepared.proposal } as unknown as Record<string, unknown>,
                  },
                },
              ],
            },
            options,
          );
        }
      } else if (outcome.kind === "client_tool") {
        const result = canRun(outcome.name)
          ? await runClientTool(outcome.name, outcome.arguments)
          : {
              ok: false,
              tool: outcome.name,
              error: { code: "unknown_tool", message: "This app cannot run that." },
            };
        if (!mounted.current) return;
        const toolResults: ChatToolResult[] = [
          { name: outcome.name, result: result as unknown as Record<string, unknown> },
        ];
        outcome = await streamChatMessage(
          {
            message: turn.text,
            conversationId: turn.conversationId,
            userMessageId: serverUserId ?? turn.serverUserId,
            toolResults,
          },
          options,
        );
      }

      if (!mounted.current) return;
      if (outcome.kind !== "answer") {
        throw new ApiError("invalid", "the backend asked for a tool twice");
      }
      finish(outcome.assistantMessageId);
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

  /**
   * Write a confirmed proposal, then let the backend record what happened so
   * the confirmation survives in the conversation.
   */
  const confirmProposal = useCallback(
    async (messageId: string, proposal: EventProposal) => {
      setMessages((prev) =>
        prev.map((m) => (m.id === messageId ? { ...m, proposalResolved: true } : m)),
      );
      try {
        const created = await createEvent({
          title: proposal.title,
          start: proposal.start,
          end: proposal.end,
          calendarId: proposal.calendarId,
          location: proposal.location,
          notes: proposal.notes,
        });
        if (!mounted.current) return;
        // Stated from the event that was actually written, not from the
        // request, so the wording can never overstate what happened.
        setMessages((prev) => [
          ...prev,
          makeMessage("assistant", `Added ${created.title} to ${created.calendar_title}.`, {
            local: true,
          }),
        ]);
      } catch (error) {
        if (!mounted.current) return;
        // A calendar refusal (no access, read-only calendar) says why in
        // plain words; anything else goes through the usual wording.
        const text = isCalendarError(error) ? error.message : describeApiError(error);
        setMessages((prev) => [...prev, makeMessage("system", text, { local: true })]);
      }
    },
    [],
  );

  const cancelProposal = useCallback((messageId: string) => {
    setMessages((prev) => [
      ...prev.map((m) => (m.id === messageId ? { ...m, proposalResolved: true } : m)),
      makeMessage("assistant", "Okay, I won't add it.", { local: true }),
    ]);
  }, []);

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
    confirmProposal,
    cancelProposal,
  };
}
