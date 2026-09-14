"""Response shapes shared by routers."""

from __future__ import annotations

from pydantic import BaseModel

from app.database.models import Conversation, Message


class ConversationOut(BaseModel):
    id: str
    title: str | None
    created_at: str
    updated_at: str

    @classmethod
    def from_model(cls, c: Conversation) -> "ConversationOut":
        return cls(id=c.id, title=c.title, created_at=c.created_at, updated_at=c.updated_at)


class MessageOut(BaseModel):
    id: str
    conversation_id: str
    role: str
    content: str
    created_at: str

    @classmethod
    def from_model(cls, m: Message) -> "MessageOut":
        return cls(
            id=m.id, conversation_id=m.conversation_id, role=m.role, content=m.content, created_at=m.created_at
        )


class ConversationWithMessages(BaseModel):
    conversation: ConversationOut
    messages: list[MessageOut]
