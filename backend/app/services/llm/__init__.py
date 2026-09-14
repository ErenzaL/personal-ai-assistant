"""LLM access.

`base.py` defines the provider-agnostic interface (`LLMService`) and error
types. Each provider lives in its own module and is the only place that knows
that provider's HTTP API. `factory.py` picks one from settings.
"""

from app.services.llm.base import (
    ChatMessage,
    LLMAuthError,
    LLMConfigError,
    LLMError,
    LLMNetworkError,
    LLMRateLimitError,
    LLMResponseError,
    LLMService,
)
from app.services.llm.factory import close_llm_service, get_llm_service

__all__ = [
    "ChatMessage",
    "LLMAuthError",
    "LLMConfigError",
    "LLMError",
    "LLMNetworkError",
    "LLMRateLimitError",
    "LLMResponseError",
    "LLMService",
    "close_llm_service",
    "get_llm_service",
]
