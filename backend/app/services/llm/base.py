"""Provider-agnostic LLM interface, errors, and a shared HTTP base class."""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, AsyncIterator, Literal

import httpx

Role = Literal["system", "user", "assistant"]
EmbeddingTask = Literal["document", "query"]


@dataclass(frozen=True)
class ChatMessage:
    role: Role
    content: str


# --- Errors -----------------------------------------------------------------
# `kind` is a stable machine-readable code the API layer maps to HTTP status.
# `message` is safe to show to the user; it never contains secrets.


class LLMError(Exception):
    kind = "llm_error"

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class LLMConfigError(LLMError):
    """No provider configured or API key missing."""

    kind = "llm_not_configured"


class LLMAuthError(LLMError):
    """The provider rejected the API key."""

    kind = "llm_auth"


class LLMRateLimitError(LLMError):
    """Quota or rate limit exceeded at the provider."""

    kind = "llm_rate_limit"


class LLMNetworkError(LLMError):
    """Could not reach the provider, it timed out, or it returned a 5xx."""

    kind = "llm_network"


class LLMResponseError(LLMError):
    """The provider answered, but not with a usable completion."""

    kind = "llm_response"


# --- Interface ----------------------------------------------------------------


class LLMService(ABC):
    """What the rest of the app depends on. Swap providers by swapping this."""

    name: str = "abstract"

    @abstractmethod
    async def generate(self, messages: list[ChatMessage]) -> str:
        """Return the full assistant reply for the conversation."""

    @abstractmethod
    def stream(self, messages: list[ChatMessage]) -> AsyncIterator[str]:
        """Yield the assistant reply as text chunks."""

    async def embed(self, text: str, *, task: EmbeddingTask) -> list[float] | None:
        """A semantic vector for `text`, or None if this provider has no
        embedding model. `task` distinguishes text being stored ("document")
        from text being searched with ("query"); providers that support
        asymmetric embeddings (Gemini does) give better results when told
        which is which. Callers must already treat None as "fall back to
        keyword matching," so the default here -- meaning "unsupported" --
        needs no separate capability check."""
        return None

    async def aclose(self) -> None:
        """Release network resources. Called at app shutdown."""


# --- Shared HTTP plumbing -------------------------------------------------------


class HttpLLMService(LLMService):
    """Base for providers that speak JSON over HTTPS.

    Subclasses implement request building and response parsing; this class
    owns the client, timeouts, SSE parsing, and mapping HTTP failures to the
    error types above.
    """

    def __init__(self, *, timeout_seconds: float) -> None:
        self._client = httpx.AsyncClient(timeout=httpx.Timeout(timeout_seconds, connect=10.0))

    async def aclose(self) -> None:
        await self._client.aclose()

    # Subclasses may override to recognise provider-specific auth failures
    # that don't use 401/403 (Gemini uses 400 for a bad key).
    def _is_auth_failure(self, status: int, body: str) -> bool:
        return status in (401, 403)

    def _raise_for_status(self, response: httpx.Response, body: str) -> None:
        status = response.status_code
        if status < 400:
            return
        detail = _short_error_text(body)
        if self._is_auth_failure(status, body):
            raise LLMAuthError(f"{self.name}: API key was rejected. Check the key in backend/.env.")
        if status == 429:
            raise LLMRateLimitError(f"{self.name}: rate limit or quota exceeded. Try again shortly.")
        if status >= 500:
            raise LLMNetworkError(f"{self.name}: provider error (HTTP {status}). Try again shortly.")
        raise LLMResponseError(f"{self.name}: request rejected (HTTP {status}). {detail}".rstrip())

    async def _post_json(self, url: str, *, headers: dict[str, str], payload: dict[str, Any]) -> Any:
        try:
            response = await self._client.post(url, headers=headers, json=payload)
        except httpx.TimeoutException as err:
            raise LLMNetworkError(f"{self.name}: request timed out.") from err
        except httpx.HTTPError as err:
            raise LLMNetworkError(f"{self.name}: network error. Check your connection.") from err
        self._raise_for_status(response, response.text)
        try:
            return response.json()
        except ValueError as err:
            raise LLMResponseError(f"{self.name}: response was not JSON.") from err

    async def _stream_sse(
        self, url: str, *, headers: dict[str, str], payload: dict[str, Any]
    ) -> AsyncIterator[Any]:
        """POST and yield each parsed `data:` JSON object from an SSE response."""
        try:
            async with self._client.stream("POST", url, headers=headers, json=payload) as response:
                if response.status_code >= 400:
                    body = (await response.aread()).decode("utf-8", "replace")
                    self._raise_for_status(response, body)
                async for line in response.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    data = line[5:].strip()
                    if not data or data == "[DONE]":
                        continue
                    try:
                        yield json.loads(data)
                    except ValueError:
                        continue
        except httpx.TimeoutException as err:
            raise LLMNetworkError(f"{self.name}: stream timed out.") from err
        except httpx.HTTPError as err:
            raise LLMNetworkError(f"{self.name}: network error during stream.") from err


def _short_error_text(body: str, limit: int = 300) -> str:
    """Pull a provider's human-readable error message out of its JSON body."""
    try:
        data = json.loads(body)
        err = data.get("error", data)
        text = err.get("message") if isinstance(err, dict) else None
    except (ValueError, AttributeError):
        text = None
    text = (text or body or "").strip().replace("\n", " ")
    return text[:limit]
