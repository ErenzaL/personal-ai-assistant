"""Chat use case: persistent conversations, context assembly, LLM calls.

Persistence rules:
- The user message is saved *before* the LLM is called, so it survives a
  failed reply; a retry passes `user_message_id` so it is reused, not duplicated.
- The assistant message is saved only once the full reply has arrived.
- Which conversation is "current" is a row in `settings`.

Context assembly lives in `services/context.py`.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import AsyncIterator

from app.database.models import Conversation, Message
from app.database.repositories import ConversationRepository, SettingsRepository
from app.services.context import PromptContext, ToolResult, build_context, with_tool_results
from app.services.llm import LLMService, get_llm_service
from app.services.llm.prompts import build_system_prompt
from app.services.preferences import PreferencesService
from app.services.retrieval import MemoryRetriever, format_memories, get_retriever

CURRENT_CONVERSATION_KEY = "current_conversation_id"

# How many messages the UI receives when it loads a conversation.
DISPLAY_MESSAGE_LIMIT = 200

TITLE_MAX_CHARS = 60


@dataclass(frozen=True)
class Turn:
    conversation: Conversation
    user_message: Message
    prompt: PromptContext
    """True only when `user_message` was just created by this call, never on
    a retry (which reuses the existing row). Passive memory extraction reads
    this so a retried message is never re-extracted."""
    is_new_message: bool = True


class ConversationService:
    """Database-only operations, plus the one step that needs the LLM
    (embedding the message for retrieval). One instance per request."""

    def __init__(self, db: sqlite3.Connection, retriever: MemoryRetriever | None = None) -> None:
        self._db = db
        self.conversations = ConversationRepository(db)
        self.settings = SettingsRepository(db)
        self.preferences = PreferencesService(db)
        # Built lazily (only `begin_turn` needs it), so every other use of
        # this class -- listing, starting, clearing conversations -- costs
        # nothing extra and never touches the LLM service.
        self._retriever = retriever

    def current(self) -> Conversation:
        """The conversation the UI should show; created on first use."""
        current_id = self.settings.get(CURRENT_CONVERSATION_KEY)
        if current_id:
            existing = self.conversations.get(current_id)
            if existing:
                return existing
        return self.start_new()

    def start_new(self) -> Conversation:
        conversation = self.conversations.create()
        self.settings.set(CURRENT_CONVERSATION_KEY, conversation.id)
        return conversation

    def clear_all(self) -> int:
        """Delete every conversation and its messages. The next request
        starts a fresh one. Confirmed in the UI before it is called."""
        deleted = 0
        while True:
            batch = self.conversations.list(limit=200)
            if not batch:
                break
            removed = sum(1 for c in batch if self.conversations.delete(c.id))
            if removed == 0:
                break
            deleted += removed
        self.settings.delete(CURRENT_CONVERSATION_KEY)
        return deleted

    def get(self, conversation_id: str) -> Conversation | None:
        return self.conversations.get(conversation_id)

    def list(self, limit: int = 50) -> list[Conversation]:
        return self.conversations.list(limit)

    def messages(self, conversation_id: str, limit: int = DISPLAY_MESSAGE_LIMIT) -> list[Message]:
        return self.conversations.list_messages(conversation_id, limit=limit)

    async def begin_turn(
        self, conversation_id: str, text: str, user_message_id: str | None = None
    ) -> Turn | None:
        """Save the user message (or reuse `user_message_id` on retry) and
        assemble the prompt. Returns None if the conversation does not exist.

        Personal memory is retrieved here (an embedding call, hence async)
        and passed to `build_context`; tool lookups plug in the same way.
        """
        conversation = self.conversations.get(conversation_id)
        if conversation is None:
            return None

        history = self.conversations.list_messages(conversation_id)
        user_message = next((m for m in history if m.id == user_message_id), None) if user_message_id else None
        is_new_message = user_message is None
        if user_message is None:
            user_message = self.conversations.add_message(conversation_id, "user", text)
            if conversation.title is None:
                self.conversations.rename(conversation_id, _title_from(text))
        else:
            # Retry: history is everything before the message being retried.
            history = history[: history.index(user_message)]

        retriever = self._retriever or get_retriever(self._db, get_llm_service())
        memories = await retriever.retrieve(user_message.content)
        prefs = self.preferences.get()
        prompt = build_context(
            history,
            user_message.content,
            memory=format_memories(memories),
            instructions=build_system_prompt(prefs.assistant_name, prefs.style_instruction),
        )
        return Turn(conversation, user_message, prompt, is_new_message=is_new_message)

    @staticmethod
    def attach_tool_results(turn: Turn, results: list[ToolResult]) -> Turn:
        """A copy of the turn whose prompt carries the tool output."""
        return Turn(
            turn.conversation, turn.user_message, with_tool_results(turn.prompt, results),
            is_new_message=turn.is_new_message,
        )

    def save_assistant_message(self, conversation_id: str, text: str) -> Message:
        return self.conversations.add_message(conversation_id, "assistant", text)


def _title_from(text: str) -> str:
    first_line = text.strip().splitlines()[0] if text.strip() else "New chat"
    return first_line if len(first_line) <= TITLE_MAX_CHARS else first_line[: TITLE_MAX_CHARS - 1] + "…"


class ChatService:
    """LLM side of a turn. Persistence happens through `ConversationService`."""

    def __init__(self, llm: LLMService) -> None:
        self._llm = llm

    async def reply(self, turn: Turn) -> str:
        return await self._llm.generate(turn.prompt.messages())

    def stream_reply(self, turn: Turn) -> AsyncIterator[str]:
        return self._llm.stream(turn.prompt.messages())
