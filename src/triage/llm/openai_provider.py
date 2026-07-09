"""OpenAI adapter. Requires `pip install ops-triage-agent[openai]` and OPENAI_API_KEY.

Uses JSON-mode so each turn of the tool-calling loop reliably receives structured
output. The rest of the system is identical to the mock path.
"""

from __future__ import annotations

import json
from typing import Any

from .base import LLMResponse, Message, Usage, estimate_cost


class OpenAIProvider:
    def __init__(self, model: str, api_key: str = "") -> None:
        try:
            from openai import OpenAI
        except ImportError as exc:  # pragma: no cover - optional dep
            raise RuntimeError(
                "openai not installed. Run: uv pip install 'ops-triage-agent[openai]'"
            ) from exc
        if not api_key:
            raise RuntimeError("OPENAI_API_KEY is required for the openai provider.")
        self.model = model
        self._client = OpenAI(api_key=api_key)

    def complete(
        self,
        messages: list[Message],
        *,
        temperature: float = 0.0,
        max_tokens: int = 1024,
        json_schema: dict[str, Any] | None = None,
    ) -> LLMResponse:
        kwargs: dict[str, Any] = {
            "model": self.model,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "messages": [{"role": m.role, "content": m.content} for m in messages],
        }
        if json_schema is not None:
            kwargs["response_format"] = {"type": "json_object"}
        resp = self._client.chat.completions.create(**kwargs)
        text = resp.choices[0].message.content or "{}"
        u = resp.usage
        usage = Usage(
            input_tokens=getattr(u, "prompt_tokens", 0),
            output_tokens=getattr(u, "completion_tokens", 0),
        )
        usage.usd = estimate_cost(self.model, usage.input_tokens, usage.output_tokens)
        raw = json.loads(text) if json_schema is not None else {}
        return LLMResponse(text=text, usage=usage, model=self.model, raw=raw)
