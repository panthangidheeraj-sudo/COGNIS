"""Provider selection from configuration (Groq, any OpenAI-compatible endpoint, or the fake)."""
from __future__ import annotations

from ..config import Settings, get_settings
from ..net.http import HttpClient
from .fake_provider import FakeProvider
from .llm_base import LLMProvider
from .openai_compat import OpenAICompatibleProvider


def build_provider(http: HttpClient, settings: Settings | None = None) -> LLMProvider | None:
    s = settings or get_settings()
    if not s.llm_enabled:
        return None
    if s.llm_provider == "fake":
        return FakeProvider()
    if s.llm_provider == "groq":
        return OpenAICompatibleProvider(name="groq", base_url=s.groq_base_url, api_key=s.groq_api_key, model=s.groq_model or "", http=http, settings=s)
    if s.llm_provider == "openai_compatible":
        return OpenAICompatibleProvider(name="openai_compatible", base_url=s.llm_base_url or "", api_key=s.llm_api_key, model=s.llm_model or "", http=http, settings=s)
    return None


def describe(settings: Settings | None = None) -> dict[str, str | bool | None]:
    s = settings or get_settings()
    model = s.groq_model if s.llm_provider == "groq" else s.llm_model if s.llm_provider == "openai_compatible" else ("fake-deterministic-1" if s.llm_provider == "fake" else None)
    return {"provider": s.llm_provider, "model": model, "enabled": s.llm_enabled}
