"""Build the configured provider. The only place provider names are compared."""

from __future__ import annotations

from app.config import Settings, get_settings
from app.services.llm.base import LLMConfigError, LLMService

_instance: LLMService | None = None


def build_llm_service(settings: Settings) -> LLMService:
    if settings.llm_provider == "gemini":
        if not settings.gemini_api_key:
            raise LLMConfigError("GEMINI_API_KEY is not set. Add it to backend/.env and restart the backend.")
        from app.services.llm.gemini import GeminiService

        return GeminiService(
            api_key=settings.gemini_api_key,
            model=settings.gemini_model,
            timeout_seconds=settings.llm_timeout_seconds,
        )

    if settings.llm_provider == "groq":
        if not settings.groq_api_key:
            raise LLMConfigError("GROQ_API_KEY is not set. Add it to backend/.env and restart the backend.")
        from app.services.llm.groq import GroqService

        return GroqService(
            api_key=settings.groq_api_key,
            model=settings.groq_model,
            timeout_seconds=settings.llm_timeout_seconds,
        )

    raise LLMConfigError(f"Unknown LLM_PROVIDER '{settings.llm_provider}'. Use 'gemini' or 'groq'.")


def get_llm_service() -> LLMService:
    """Process-wide singleton, created on first use so a missing key does not
    stop the app from starting (health stays green; /chat reports the problem)."""
    global _instance
    if _instance is None:
        _instance = build_llm_service(get_settings())
    return _instance


async def close_llm_service() -> None:
    global _instance
    if _instance is not None:
        await _instance.aclose()
        _instance = None
