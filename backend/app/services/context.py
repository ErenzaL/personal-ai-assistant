"""Assembly of the messages sent to the LLM for one turn.

Five kinds of context are kept apart and combined in a fixed order:

    1. system instructions        SYSTEM_PROMPT (identity, rules)
    2. relevant personal memory   system message, only when non-empty   <- future
    3. recent conversation        user/assistant turns under a size policy
    4. tool results               system message, only when non-empty   <- future
    5. current user message       last

Memory and tool results are rendered as separate system messages so the
model can tell where each fact came from, and so their *absence* is
meaningful: the identity prompt tells the model that no section means no
memory / no lookup. Providers that accept a single system instruction
(Gemini) merge all system messages in order; providers that accept several
(Groq/OpenAI-style) receive them as-is.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace

from app.database.models import Message
from app.services.llm import ChatMessage
from app.services.llm.prompts import MEMORY_SECTION_TITLE, SYSTEM_PROMPT, TOOL_RESULTS_SECTION_TITLE

# --- Conversation history policy --------------------------------------------------
# Only the current conversation is ever sent, and only its tail: the most recent
# messages until either cap is hit. 20 messages is ~10 turns; 12k characters
# (~3k tokens) keeps requests small even for long chats.
HISTORY_MAX_MESSAGES = 20
HISTORY_MAX_CHARS = 12_000


def select_history(messages: list[Message]) -> list[ChatMessage]:
    """Apply the history policy to a conversation's messages (oldest first)."""
    picked: list[ChatMessage] = []
    chars = 0
    for message in reversed(messages):
        if message.role == "system":
            continue
        if len(picked) >= HISTORY_MAX_MESSAGES or chars + len(message.content) > HISTORY_MAX_CHARS:
            break
        picked.append(ChatMessage(message.role, message.content))
        chars += len(message.content)
    picked.reverse()
    return picked


@dataclass(frozen=True)
class ToolResult:
    """Outcome of a lookup made for the current message (future use)."""

    source: str  # human-readable, e.g. "calendar", "tasks"
    content: str  # already formatted for the model


@dataclass(frozen=True)
class PromptContext:
    """Everything the model sees for one turn, by kind."""

    instructions: str
    history: list[ChatMessage]
    user_message: str
    memory: list[str] = field(default_factory=list)  # facts about the user, one per entry
    tool_results: list[ToolResult] = field(default_factory=list)

    def messages(self) -> list[ChatMessage]:
        out: list[ChatMessage] = [ChatMessage("system", self.instructions)]
        if self.memory:
            facts = "\n".join(f"- {fact}" for fact in self.memory)
            out.append(ChatMessage("system", f"{MEMORY_SECTION_TITLE}:\n{facts}"))
        out.extend(self.history)
        if self.tool_results:
            results = "\n\n".join(f"[{r.source}]\n{r.content}" for r in self.tool_results)
            out.append(ChatMessage("system", f"{TOOL_RESULTS_SECTION_TITLE}:\n{results}"))
        out.append(ChatMessage("user", self.user_message))
        return out


def build_context(
    history: list[Message],
    user_message: str,
    *,
    memory: list[str] | None = None,
    tool_results: list[ToolResult] | None = None,
    instructions: str | None = None,
) -> PromptContext:
    """Assemble a turn. `history` is the conversation so far, oldest first,
    *excluding* the current user message. `instructions` defaults to the
    identity prompt; the chat service passes one built from the user's
    assistant preferences."""
    return PromptContext(
        instructions=instructions or SYSTEM_PROMPT,
        history=select_history(history),
        user_message=user_message,
        memory=list(memory or []),
        tool_results=list(tool_results or []),
    )


def with_tool_results(prompt: PromptContext, results: list[ToolResult]) -> PromptContext:
    """Same turn, now carrying tool output. Avoids redoing memory retrieval."""
    return replace(prompt, tool_results=list(results))
