import asyncio
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
from app.services.llm import ChatMessage, LLMError, get_llm_service
from app.services.memory import MemoryService
from app.services.memory_extraction import extract as extract_memory
from app.services.preferences import PreferencesService

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


class AssistantActionOut(BaseModel):
    """A single button the desktop app may show under this reply. Computed
    deterministically from the executed tool's own structured result --
    never inferred by parsing the reply's own text (a markdown-looking
    button in prose is not application logic)."""

    type: str
    label: str
    filter: str | None = None


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
    """Set when this message taught the assistant something new (or updated
    an existing memory); the content to show as brief "Remembered: ..."
    feedback. None the great majority of the time -- most messages contain
    nothing durable to keep."""
    memory_saved: str | None = None
    """True when `answer` is a Gmail reply draft (nothing else): the desktop
    app shows it as a labelled draft card with a Copy button instead of an
    ordinary chat bubble. Never true for anything actually sent or saved --
    this app cannot do either."""
    is_draft: bool = False
    """Set only for an explicit "open my tasks" navigation command (never for
    an ordinary question about tasks): which tab the desktop app should open
    immediately, with no button and no summary needed."""
    open_tasks_tab: str | None = None
    """Optional buttons under this reply -- at most one for an ordinary task
    question, shown only when opening the panel would add real value (never
    for an empty result, and never for a question the answer already
    settles). The panel never opens itself for these; the user has to tap."""
    actions: list[AssistantActionOut] = Field(default_factory=list)
    """True when some task or checklist item was created, changed, or had
    its status flipped this turn -- the desktop app refreshes the Tasks
    panel's data (if it's showing) rather than assuming it's still current."""
    tasks_changed: bool = False


async def _begin(request: ChatRequest, db: sqlite3.Connection) -> Turn:
    service = ConversationService(db)
    conversation_id = request.conversation_id or service.current().id
    turn = await service.begin_turn(conversation_id, request.message, request.user_message_id)
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


# Holds strong references to detached extraction tasks so they are never
# garbage-collected mid-flight (a known asyncio gotcha for a task nothing
# awaits), and removes each once it finishes. This is the only place a
# memory-extraction task is *not* awaited by the request that started it --
# the case where the same message also needs a client-side tool, and the
# request has to return before the tool's result comes back. See
# `_spawn_extraction`.
_background_tasks: set[asyncio.Task] = set()


def _spawn_extraction(turn: Turn, db: sqlite3.Connection) -> "asyncio.Task[tuple[bool, str | None]] | None":
    """Passive memory extraction for a freshly-received user message (see
    `memory_extraction.py`), started as early as possible so it runs
    concurrently with tool selection and answer generation rather than
    adding to the visible reply time.

    Never runs twice for the same message: `turn.is_new_message` is False on
    a retry (reused message) and on the second pass of a client-tool round
    trip, so this only ever fires once per thing the user actually typed.
    Uses its own database connection, the same reason `_save_assistant`
    does: on the client-tool path the request returns *before* this
    finishes, so it must not depend on the request-scoped connection.
    """
    if not turn.is_new_message:
        return None
    if not PreferencesService(db).get().memory_enabled:
        return None

    history = list(turn.prompt.history)
    text = turn.user_message.content
    conversation_id = turn.conversation.id

    async def run() -> tuple[bool, str | None]:
        conn = connect(get_settings().database_path)
        try:
            result = await extract_memory(get_llm_service(), MemoryService(conn), text, history, conversation_id)
            return result.saved, result.content
        except Exception:
            log.exception("memory extraction task failed")
            return False, None
        finally:
            conn.close()

    task = asyncio.create_task(run())
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)
    return task


async def _collect_memory_saved(task: "asyncio.Task[tuple[bool, str | None]] | None") -> str | None:
    """The content to show as "Remembered: ..." feedback, or None. Awaiting
    a failed task here would surface its exception at the call site, but
    `run()` above already turns every failure into `(False, None)`, so this
    can never raise."""
    if task is None:
        return None
    saved, content = await task
    return content if saved else None


def _attach(turn: Turn, db: sqlite3.Connection, results: list[tuple[str, str]]) -> Turn:
    return ConversationService.attach_tool_results(
        turn, [ToolResult(name, body) for name, body in results]
    )


# Every task tool whose success means the panel's data may have moved --
# a fresh task, a status flip, a due-date change, a completed checklist item.
_TASK_MUTATIONS = {tools.TASKS_CREATE, tools.TASKS_UPDATE, tools.TASKS_COMPLETE, tools.TASKS_CANCEL, tools.TASKS_COMPLETE_ITEM}

# Which Tasks-panel tab a given tasks.list/tasks.open_panel filter maps to.
_TASKS_TAB_FOR_FILTER = {"today": "today", "overdue": "today", "completed": "completed"}

# A label per tab, kept to exactly these three so the button never grows a
# new variant per phrasing -- "Open tasks" covers every non-today/completed
# filter (open, all, upcoming, week, tomorrow, cancelled).
_TASKS_ACTION_LABEL = {"today": "Open today's tasks", "completed": "Open completed tasks", "upcoming": "Open tasks"}


def _tasks_tab(filter_used: str) -> str:
    return _TASKS_TAB_FOR_FILTER.get(filter_used, "upcoming")


def _task_hints(call: "tools.ToolCall", outcome: tools.ToolOutcome) -> dict[str, Any]:
    if not outcome.ok:
        return {}
    if call.name == tools.TASKS_OPEN_PANEL:
        # An explicit "open my tasks" command: opens immediately, no button.
        return {"open_tasks_tab": _tasks_tab(str(call.arguments.get("filter", "open")))}
    if call.name == tools.TASKS_LIST:
        # An ordinary question about tasks: never opens anything itself.
        # A button is offered only when the model judged it useful to see
        # the list (offer_panel) AND there is something to see (count > 0):
        # an empty result already has nothing more to show, and a question
        # the answer already settled (a count, a specific due date) doesn't
        # need one either.
        offer_panel = bool(call.arguments.get("offer_panel", True))
        count = outcome.data.get("count", 0) if isinstance(outcome.data.get("count"), int) else 0
        if not offer_panel or count == 0:
            return {}
        tab = _tasks_tab(str(call.arguments.get("filter", "open")))
        return {"actions": [{"type": "open_task_panel", "label": _TASKS_ACTION_LABEL[tab], "filter": tab}]}
    if call.name in _TASK_MUTATIONS:
        return {"tasks_changed": True}
    return {}


async def _with_tools(
    request: ChatRequest, turn: Turn, db: sqlite3.Connection
) -> tuple[Turn, ClientToolRequest | None, dict[str, Any]]:
    """Tool phase, kept separate from answer generation.

    Returns the turn to answer from, a tool for the client to run when the
    selected tool needs native access, and a small dict of UI hints for the
    desktop app -- "is_draft" (gmail.draft_reply found a source email: the
    app renders a labelled "Draft reply" card with a Copy button instead of
    an ordinary bubble, since the whole answer *is* the reply text with
    nothing else added -- see the identity prompt's draft rule); for task
    tools, "open_tasks_tab" (an explicit "open my tasks" command: opens the
    panel immediately, no button needed), "actions" (an ordinary tasks.list
    question judged worth a button: the panel stays closed until the user
    taps it -- see `_task_hints`), and "tasks_changed" (some task or
    checklist item was created or changed: refresh the panel's data if it's
    open). Empty on an ambiguous/not-found/error outcome: there, the answer
    is an ordinary clarifying or error message. On the second pass the app
    posts a client tool's result back and it is attached directly; that path
    never carries hints (draft_reply and the task tools are never
    client-executed).
    """
    # Second pass: the desktop app already ran the tool.
    if request.tool_results:
        rendered = []
        for item in request.tool_results:
            body = tools.summarise(item.result) if item.name == tools.CALENDAR_READ else item.result
            rendered.append((item.name, tools.render_outcome(body)))
            log.info("client tool %s: %s", item.name, "ok" if item.result.get("ok") else "failed")
        return _attach(turn, db, rendered), None, {}

    text = turn.user_message.content
    registry = tools.build_registry(db)
    call = await tools.select(get_llm_service(), registry, text, turn.prompt.history)
    if call is None:
        return turn, None, {}

    # Calendar tools run in the desktop app, not here.
    if registry.runs_on_client(call.name):
        checked = registry.validate(call.name, call.arguments)
        if isinstance(checked, tools.ToolOutcome):
            return _attach(turn, db, [(call.name, checked.to_text())]), None, {}
        return turn, ClientToolRequest(call.name, checked), {}

    outcome = registry.execute(call.name, call.arguments)
    hints: dict[str, Any] = _task_hints(call, outcome)
    if call.name == tools.GMAIL_DRAFT_REPLY and outcome.ok:
        hints["is_draft"] = True
    return _attach(turn, db, [(call.name, outcome.to_text())]), None, hints


@router.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest, db: sqlite3.Connection = Depends(get_db)) -> ChatResponse:
    turn = await _begin(request, db)
    memory_task = _spawn_extraction(turn, db)
    hints: dict[str, Any] = {}
    try:
        answer = await _memory_reply(turn, db)
        if answer is None:
            turn, client_tool, hints = await _with_tools(request, turn, db)
            if client_tool is not None:
                # The extraction task keeps running in the background (see
                # `_background_tasks`); this response has no "done" moment
                # to attach its feedback to, so it surfaces on the next call.
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
        memory_saved=await _collect_memory_saved(memory_task),
        is_draft=hints.get("is_draft", False),
        open_tasks_tab=hints.get("open_tasks_tab"),
        actions=hints.get("actions", []),
        tasks_changed=hints.get("tasks_changed", False),
    )


# --- Streaming ------------------------------------------------------------------
# Server-Sent Events framing over a POST body. Event types, in order:
#   meta   {"conversation_id", "user_message_id"}   the saved user message
#   delta  {"text": "..."}                           a piece of the answer
#   done   {"assistant_message_id", "memory_saved"?, "is_draft"?,
#           "open_tasks_tab"?, "actions"?, "tasks_changed"?}  reply complete and saved
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
    turn = await _begin(request, db)
    memory_task = _spawn_extraction(turn, db)
    meta = _sse("meta", {"conversation_id": turn.conversation.id, "user_message_id": turn.user_message.id})
    headers = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}

    client_tool: ClientToolRequest | None = None
    hints: dict[str, Any] = {}
    try:
        command_reply = await _memory_reply(turn, db)
        if command_reply is None:
            turn, client_tool, hints = await _with_tools(request, turn, db)
    except LLMError as err:
        raise _http_error(err) from err

    # The desktop app has to run this one and post the result back; the reply
    # is written on that second request. Nothing is saved in the meantime.
    # `memory_task` keeps running in the background (see `_spawn_extraction`)
    # and its feedback, if any, surfaces whenever a "done" is next emitted.
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
            memory_saved = await _collect_memory_saved(memory_task)
            done: dict[str, Any] = {"assistant_message_id": assistant_id}
            if memory_saved:
                done["memory_saved"] = memory_saved
            yield _sse("done", done)

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
            # Extraction has been running concurrently with the whole reply
            # above, so this rarely adds a visible wait: most of the time it
            # finished well before the last token did.
            memory_saved = await _collect_memory_saved(memory_task)
            done: dict[str, Any] = {"assistant_message_id": assistant_id}
            if memory_saved:
                done["memory_saved"] = memory_saved
            if hints.get("is_draft"):
                done["is_draft"] = True
            if hints.get("open_tasks_tab"):
                done["open_tasks_tab"] = hints["open_tasks_tab"]
            if hints.get("actions"):
                done["actions"] = hints["actions"]
            if hints.get("tasks_changed"):
                done["tasks_changed"] = True
            yield _sse("done", done)
        except LLMError as err:
            log.warning("chat stream failed: %s: %s", err.kind, err.message)
            yield _sse("error", {"code": err.kind, "message": err.message})
        finally:
            # Also runs when the client disconnects and Starlette closes the
            # generator, so the upstream provider request is cancelled too.
            await chunks.aclose()

    return StreamingResponse(events(), media_type="text/event-stream", headers=headers)
