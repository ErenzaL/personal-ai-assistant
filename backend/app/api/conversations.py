import sqlite3

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.api.schemas import ConversationOut, ConversationWithMessages, MessageOut
from app.database import get_db
from app.services.chat import ConversationService

router = APIRouter(prefix="/conversations", tags=["conversations"])


@router.get("/current", response_model=ConversationWithMessages)
def current_conversation(db: sqlite3.Connection = Depends(get_db)) -> ConversationWithMessages:
    """The conversation the UI shows on open, with its recent messages."""
    service = ConversationService(db)
    conversation = service.current()
    return ConversationWithMessages(
        conversation=ConversationOut.from_model(conversation),
        messages=[MessageOut.from_model(m) for m in service.messages(conversation.id)],
    )


@router.post("", response_model=ConversationOut, status_code=201)
def new_conversation(db: sqlite3.Connection = Depends(get_db)) -> ConversationOut:
    """Start a fresh conversation and make it current."""
    return ConversationOut.from_model(ConversationService(db).start_new())


@router.get("", response_model=list[ConversationOut])
def list_conversations(db: sqlite3.Connection = Depends(get_db)) -> list[ConversationOut]:
    return [ConversationOut.from_model(c) for c in ConversationService(db).list()]


@router.get("/{conversation_id}", response_model=ConversationWithMessages)
def get_conversation(conversation_id: str, db: sqlite3.Connection = Depends(get_db)) -> ConversationWithMessages:
    service = ConversationService(db)
    conversation = service.get(conversation_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail="conversation not found")
    return ConversationWithMessages(
        conversation=ConversationOut.from_model(conversation),
        messages=[MessageOut.from_model(m) for m in service.messages(conversation.id)],
    )


class ClearedCount(BaseModel):
    deleted: int


@router.delete("", response_model=ClearedCount)
def clear_conversations(db: sqlite3.Connection = Depends(get_db)) -> ClearedCount:
    """Remove every conversation and message. The UI confirms first."""
    return ClearedCount(deleted=ConversationService(db).clear_all())
