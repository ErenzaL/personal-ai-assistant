import json
import logging
import sqlite3
from dataclasses import dataclass
from typing import Any, AsyncIterator

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.config import get_settings
from app.database import connect, get_db
from app.services import memory_commands, tools
from app.services.chat import ChatService, ConversationService, Turn
from app.services.context import ToolResult
from app.services.llm import LLMError, get_llm_service

router = APIRouter(tags=["chat"])
log = logging.getLogger("app.chat")

# HTTP status for each LLMError kind. Auth/config failures are 503, not 401:
# the *server* is misconfigured, and the client has no credentials of its own.
_STATUS_FOR_KIND = {
    "llm_not_configured": 503,
    "llm_auth": 503,
    "llm_rate_limit": 429,
    "llm_network": 502,
    "llm_response": 502,
}


def _http_error(err: LLMError) -> HTTPException:
    log.warning("chat failed: %s: %s", err.kind, err.message)
    return HTTPException(
        status_code=_STATUS_FOR_KIND.get(err.kind, 502),
        detail={"code": err.kind, "message": err.message},
    )


class ToolResultIn(BaseModel):
    """A client-side tool's outcome, posted back by the desktop app."""

    name: str = Field(min_length=1, max_length=64)
    result: dict[str, Any]


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    """Conversation to append to. Omitted: the current conversation."""
    conversation_id: str | None = None
    """On retry: id of the already-saved user message, so it is not saved twice."""
    user_message_id: str | None = None
    """Second pass of a client-executed tool: results the app produced. When
    present, no tool is selected again -- these go straight into the prompt."""
    tool_results: list[ToolResultIn] = Field(default_factory=list, max_length=4)


class ChatResponse(BaseModel):
    answer: str
    conversation_id: str
    user_message_id: str
    assistant_message_id: str


def _begin(request: ChatRequest, db: sqlite3.Connection) -> Turn:
    service = ConversationService(db)
    conversation_id = request.conversation_id or service.current().id
    turn = service.begin_turn(conversation_id, request.message, request.user_message_id)
    if turn is None:
        raise HTTPException(status_code=404, detail="conversation not found")
    return turn


def _save_assistant(conversation_id: str, text: str) -> str:
    """Save with a fresh connection: the request-scoped one may already be
    closed by the time a streamed reply completes."""
    conn = connect(get_settings().database_path)
    try:
        return ConversationService(conn).save_assistant_message(conversation_id, text).id
    finally:
        conn.close()


async def _memory_reply(turn: Turn, db: sqlite3.Connection) -> str | None:
    """Answer an explicit remember / recall / forget request, if that is what
    the message is. Composed from the real database outcome, not by the model."""
    text = turn.user_message.content
    handler = memory_commands.MemoryCommandHandler(db)
    pending = handler.pending_choice(turn.conversation.id, text)
    if pending is not None:
        return pending
    if not memory_commands.screen(text):
        return None
    intent = await memory_commands.interpret(get_llm_service(), text)
    if intent.intent == "none":
        return None
    log.info("memory command: %s", intent.intent)
    return handler.execute(intent, text, turn.conversation.id)


@dataclass(frozen=True)
class ClientToolRequest:
    """A tool the desktop app must run, because it needs native access."""

    name: str
    arguments: dict[str, Any]


def _attach(turn: Turn, db: sqlite3.Connection, results: list[tuple[str, str]]) -> Turn:
    return ConversationService.attach_tool_results(
        turn, [ToolResult(name, body) for name, body in results]
    )


async def _with_tools(
    request: ChatRequest, turn: Turn, db: sqlite3.Connection
) -> tuple[Turn, ClientToolRequest | None]:
    """Tool phase, kept separate from answer generation.

    Returns the turn to answer from, plus a tool for the client to run when
    the selected tool needs native access. On the second pass the app posts
    the result back and it is attached directly.
    """
    # Second pass: the desktop app already ran the tool.
    if request.tool_results:
        rendered = []
        for item in request.tool_results:
            body = tools.summarise(item.result) if item.name == tools.CALENDAR_READ else item.result
            rendered.append((item.name, tools.render_outcome(body)))
            log.info("client tool %s: %s", item.name, "ok" if item.result.get("ok") else "failed")
        return _attach(turn, db, rendered), None

    text = turn.user_message.content
    registry = tools.build_registry(db)
    call = await tools.select(get_llm_service(), registry, text, turn.prompt.history)
    if call is None:
        return turn, None

    # Calendar tools run in the desktop app, not here.
    if registry.runs_on_client(call.name):
        checked = registry.validate(call.name, call.arguments)
        if isinstance(checked, tools.ToolOutcome):
            return _attach(turn, db, [(call.name, checked.to_text())]), None
        return turn, ClientToolRequest(call.name, checked)

    outcome = registry.execute(call.name, call.arguments)
    return _attach(turn, db, [(call.name, outcome.to_text())]), None


@router.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest, db: sqlite3.Connection = Depends(get_db)) -> ChatResponse:
    turn = _begin(request, db)
    try:
        answer = await _memory_reply(turn, db)
        if answer is None:
            turn, client_tool = await _with_tools(request, turn, db)
            if client_tool is not None:
                raise HTTPException(
                    status_code=409,
                    detail={
                        "code": "client_tool_required",
                        "message": "This question needs the desktop app to read the calendar.",
                        "tool": {"name": client_tool.name, "arguments": client_tool.arguments},
                    },
                )
            answer = await ChatService(get_llm_service()).reply(turn)
    except LLMError as err:
        raise _http_error(err) from err
    assistant_id = _save_assistant(turn.conversation.id, answer)
    return ChatResponse(
        answer=answer,
        conversation_id=turn.conversation.id,
        user_message_id=turn.user_message.id,
        assistant_message_id=assistant_id,
    )


# --- Streaming ------------------------------------------------------------------
# Server-Sent Events framing over a POST body. Event types, in order:
#   meta   {"conversation_id", "user_message_id"}   the saved user message
#   delta  {"text": "..."}                           a piece of the answer
#   done   {"assistant_message_id"}                  reply complete and saved
#   error  {"code", "message"}                       failed mid-way (in-band,
#                                                    since status is already 200)
# Failures *before* the first token still surface as a normal HTTP error
# status, because we wait for the first chunk before committing to a stream.
# The user message is saved either way; retry with `user_message_id`.
#   client_tool {"name", "arguments"}          the desktop app must run this
#                                              tool and POST again with
#                                              `tool_results`; no answer yet
# Memory commands are answered as a single delta through this stream. Task
# requests run their tool first, then stream a reply written from the result.


def _sse(event: str, data: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


@router.post("/chat/stream")
async def chat_stream(request: ChatRequest, db: sqlite3.Connection = Depends(get_db)) -> StreamingResponse:
    turn = _begin(request, db)
    meta = _sse("meta", {"conversation_id": turn.conversation.id, "user_message_id": turn.user_message.id})
    headers = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}

    client_tool: ClientToolRequest | None = None
    try:
        command_reply = await _memory_reply(turn, db)
        if command_reply is None:
            turn, client_tool = await _with_tools(request, turn, db)
    except LLMError as err:
        raise _http_error(err) from err

    # The desktop app has to run this one and post the result back; the reply
    # is written on that second request. Nothing is saved in the meantime.
    if client_tool is not None:

        async def tool_events() -> AsyncIterator[str]:
            yield meta
            yield _sse(
                "client_tool",
                {"name": client_tool.name, "arguments": client_tool.arguments},
            )

        return StreamingResponse(tool_events(), media_type="text/event-stream", headers=headers)

    if command_reply is not None:

        async def command_events() -> AsyncIterator[str]:
            yield meta
            yield _sse("delta", {"text": command_reply})
            assistant_id = _save_assistant(turn.conversation.id, command_reply)
            yield _sse("done", {"assistant_message_id": assistant_id})

        return StreamingResponse(command_events(), media_type="text/event-stream", headers=headers)

    chunks = ChatService(get_llm_service()).stream_reply(turn)
    try:
        first: str | None = await anext(chunks)
    except StopAsyncIteration:
        first = None
    except LLMError as err:
        await chunks.aclose()
        raise _http_error(err) from err

    async def events() -> AsyncIterator[str]:
        parts: list[str] = []
        try:
            yield meta
            if first is not None:
                parts.append(first)
                yield _sse("delta", {"text": first})
            async for chunk in chunks:
                parts.append(chunk)
                yield _sse("delta", {"text": chunk})
            assistant_id = _save_assistant(turn.conversation.id, "".join(parts))
            yield _sse("done", {"assistant_message_id": assistant_id})
        except LLMError as err:
            log.warning("chat stream failed: %s: %s", err.kind, err.message)
            yield _sse("error", {"code": err.kind, "message": err.message})
        finally:
            # Also runs when the client disconnects and Starlette closes the
            # generator, so the upstream provider request is cancelled too.
            await chunks.aclose()

    return StreamingResponse(events(), media_type="text/event-stream", headers=headers)
