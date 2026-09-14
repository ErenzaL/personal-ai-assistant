"""Groq via its OpenAI-compatible chat completions API. Nothing outside this
module knows that request or response shape."""

from __future__ import annotations

from typing import Any, AsyncIterator

from app.services.llm.base import ChatMessage, HttpLLMService, LLMResponseError

URL = "https://api.groq.com/openai/v1/chat/completions"


class GroqService(HttpLLMService):
    name = "groq"

    def __init__(self, *, api_key: str, model: str, timeout_seconds: float) -> None:
        super().__init__(timeout_seconds=timeout_seconds)
        self._api_key = api_key
        self._model = model

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._api_key}", "Content-Type": "application/json"}

    def _payload(self, messages: list[ChatMessage], *, stream: bool) -> dict[str, Any]:
        return {
            "model": self._model,
            "messages": [{"role": m.role, "content": m.content} for m in messages],
            "temperature": 0.7,
            "max_tokens": 1024,
            "stream": stream,
        }

    async def generate(self, messages: list[ChatMessage]) -> str:
        data = await self._post_json(URL, headers=self._headers(), payload=self._payload(messages, stream=False))
        try:
            text = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as err:
            raise LLMResponseError("groq: unexpected response shape.") from err
        if not isinstance(text, str) or not text.strip():
            raise LLMResponseError("groq: the model returned an empty answer.")
        return text

    async def stream(self, messages: list[ChatMessage]) -> AsyncIterator[str]:
        async for event in self._stream_sse(URL, headers=self._headers(), payload=self._payload(messages, stream=True)):
            choices = event.get("choices") or []
            if not choices:
                continue
            delta = (choices[0].get("delta") or {}).get("content")
            if delta:
                yield delta
