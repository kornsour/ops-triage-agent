"""Core LLM types and the provider protocol.

The interface is a single `complete()` that takes messages plus an optional JSON
schema for structured output, and returns text + token usage + a computed USD
cost. The tool-calling loop (see agent/runner.py) is driven by structured JSON the
model emits rather than provider-native function calling, which keeps the loop
identical across the mock, OpenAI, and Anthropic providers.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

# Indicative public per-1M-token prices (USD). Kept here so cost tracking works
# offline; override per provider as pricing changes. Not authoritative.
PRICING_USD_PER_1M = {
    # model substring -> (input, output)
    "gpt-4.1": (2.00, 8.00),
    "gpt-4o-mini": (0.15, 0.60),
    "gpt-4o": (2.50, 10.00),
    "claude-opus": (15.00, 75.00),
    "claude-sonnet": (3.00, 15.00),
    "claude-haiku": (0.80, 4.00),
    "mock": (0.0, 0.0),
}


@dataclass
class Message:
    role: str  # system | user | assistant
    content: str


@dataclass
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    usd: float = 0.0

    def __add__(self, other: Usage) -> Usage:
        return Usage(
            self.input_tokens + other.input_tokens,
            self.output_tokens + other.output_tokens,
            round(self.usd + other.usd, 8),
        )


@dataclass
class LLMResponse:
    text: str
    usage: Usage
    model: str
    raw: dict[str, Any] = field(default_factory=dict)


def price_for(model: str) -> tuple[float, float]:
    for key, price in PRICING_USD_PER_1M.items():
        if key in model:
            return price
    return (0.0, 0.0)


def estimate_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    pin, pout = price_for(model)
    return round((input_tokens * pin + output_tokens * pout) / 1_000_000, 8)


def approx_tokens(text: str) -> int:
    """Cheap, provider-independent token estimate (~4 chars/token)."""
    return max(1, len(text) // 4)


@runtime_checkable
class LLMProvider(Protocol):
    model: str

    def complete(
        self,
        messages: list[Message],
        *,
        temperature: float = 0.0,
        max_tokens: int = 1024,
        json_schema: dict[str, Any] | None = None,
    ) -> LLMResponse: ...
