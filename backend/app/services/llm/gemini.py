"""Google Gemini via the Generative Language REST API. Nothing outside this
module knows Gemini's request or response shapes."""

from __future__ import annotations

from typing import Any, AsyncIterator

from app.services.embeddings import EXPECTED_DIMENSIONS
from app.services.llm.base import ChatMessage, EmbeddingTask, HttpLLMService, LLMResponseError

BASE_URL = "https://generativelanguage.googleapis.com/v1beta/models"

# A separate, cheaper model from the chat model: embeddings are billed and
# rate-limited independently of `generateContent`, so calling this on every
# message does not compete with the chat quota.
EMBEDDING_MODEL = "gemini-embedding-001"
# RETRIEVAL_DOCUMENT for memory content being stored, RETRIEVAL_QUERY for a
# message being searched with -- Gemini's asymmetric embeddings are tuned
# for exactly this document/query split and retrieve better than embedding
# both sides the same way.
_TASK_TYPE: dict[EmbeddingTask, str] = {"document": "RETRIEVAL_DOCUMENT", "query": "RETRIEVAL_QUERY"}


class GeminiService(HttpLLMService):
    name = "gemini"

    def __init__(self, *, api_key: str, model: str, timeout_seconds: float) -> None:
        super().__init__(timeout_seconds=timeout_seconds)
        self._api_key = api_key
        self._model = model

    # Gemini answers 400 (not 401) for a malformed or revoked key.
    def _is_auth_failure(self, status: int, body: str) -> bool:
        return status in (401, 403) or (status == 400 and "API key" in body)

    def _headers(self) -> dict[str, str]:
        # Key goes in a header, never in the URL, so it can't end up in logs.
        return {"x-goog-api-key": self._api_key, "Content-Type": "application/json"}

    @staticmethod
    def _payload(messages: list[ChatMessage]) -> dict[str, Any]:
        system_parts = [m.content for m in messages if m.role == "system"]
        contents = [
            {"role": "model" if m.role == "assistant" else "user", "parts": [{"text": m.content}]}
            for m in messages
            if m.role != "system"
        ]
        payload: dict[str, Any] = {
            "contents": contents,
            "generationConfig": {"temperature": 0.7, "maxOutputTokens": 1024},
        }
        if system_parts:
            payload["system_instruction"] = {"parts": [{"text": "\n\n".join(system_parts)}]}
        return payload

    @staticmethod
    def _extract_text(data: Any) -> str:
        candidates = data.get("candidates") or []
        if not candidates:
            reason = (data.get("promptFeedback") or {}).get("blockReason")
            suffix = f" (blocked: {reason})" if reason else ""
            raise LLMResponseError(f"gemini: the model returned no answer{suffix}.")
        parts = (candidates[0].get("content") or {}).get("parts") or []
        # Skip "thought" parts some models emit when reasoning is enabled.
        return "".join(p.get("text", "") for p in parts if not p.get("thought"))

    async def generate(self, messages: list[ChatMessage]) -> str:
        url = f"{BASE_URL}/{self._model}:generateContent"
        data = await self._post_json(url, headers=self._headers(), payload=self._payload(messages))
        text = self._extract_text(data)
        if not text.strip():
            raise LLMResponseError("gemini: the model returned an empty answer.")
        return text

    async def stream(self, messages: list[ChatMessage]) -> AsyncIterator[str]:
        url = f"{BASE_URL}/{self._model}:streamGenerateContent?alt=sse"
        async for event in self._stream_sse(url, headers=self._headers(), payload=self._payload(messages)):
            candidates = event.get("candidates") or []
            if not candidates:
                continue
            for part in (candidates[0].get("content") or {}).get("parts") or []:
                if part.get("text") and not part.get("thought"):
                    yield part["text"]

    async def embed(self, text: str, *, task: EmbeddingTask) -> list[float] | None:
        text = text.strip()
        if not text:
            return None
        url = f"{BASE_URL}/{EMBEDDING_MODEL}:embedContent"
        payload = {
            "content": {"parts": [{"text": text}]},
            "taskType": _TASK_TYPE[task],
            "outputDimensionality": EXPECTED_DIMENSIONS,
        }
        try:
            data = await self._post_json(url, headers=self._headers(), payload=payload)
        except Exception:
            # Embedding failures must never take the chat request down: every
            # caller already treats None as "fall back to keyword matching."
            return None
        values = (data.get("embedding") or {}).get("values")
        if not isinstance(values, list) or not values:
            return None
        return [float(v) for v in values]
