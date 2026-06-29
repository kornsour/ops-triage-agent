"""Provider-agnostic LLM interface.

The rest of the system depends only on `LLMProvider`, so a triage run is
identical whether it is backed by the deterministic mock (offline, used in
tests + CI), OpenAI, or Anthropic. Provider selection is config-driven.
"""

from __future__ import annotations

from triage.config import Settings, get_settings

from .base import LLMProvider, LLMResponse, Message, Usage
from .mock import MockProvider


def get_provider(settings: Settings | None = None) -> LLMProvider:
    settings = settings or get_settings()
    provider = settings.llm_provider.lower()
    model = settings.default_model()

    if provider == "mock":
        return MockProvider(model=model)
    if provider == "openai":
        from .openai_provider import OpenAIProvider

        return OpenAIProvider(model=model, api_key=settings.openai_api_key)
    if provider == "anthropic":
        from .anthropic_provider import AnthropicProvider

        return AnthropicProvider(model=model, api_key=settings.anthropic_api_key)
    raise ValueError(f"Unknown LLM provider: {settings.llm_provider!r}")


__all__ = [
    "LLMProvider",
    "LLMResponse",
    "Message",
    "Usage",
    "MockProvider",
    "get_provider",
]
