"""Anthropic adapter. Requires `pip install ops-triage-agent[anthropic]` and ANTHROPIC_API_KEY.

Model ids: claude-opus-4-8, claude-sonnet-4-6, claude-haiku-4-5-20251001.
The Messages API has no JSON-mode flag, so we steer with a system instruction and
parse the first JSON object from the reply.
"""

from __future__ import annotations

import json
import re
from typing import Any

from .base import LLMResponse, Message, Usage, estimate_cost

_JSON_RE = re.compile(r"\{.*\}", re.DOTALL)


class AnthropicProvider:
    def __init__(self, model: str, api_key: str = "") -> None:
        try:
            import anthropic
        except ImportError as exc:  # pragma: no cover - optional dep
            raise RuntimeError(
                "anthropic not installed. Run: uv pip install 'ops-triage-agent[anthropic]'"
            ) from exc
        if not api_key:
            raise RuntimeError("ANTHROPIC_API_KEY is required for the anthropic provider.")
        self.model = model
        self._client = anthropic.Anthropic(api_key=api_key)

    def complete(
        self,
        messages: list[Message],
        *,
        temperature: float = 0.0,
        max_tokens: int = 1024,
        json_schema: dict[str, Any] | None = None,
    ) -> LLMResponse:
        system = "\n".join(m.content for m in messages if m.role == "system")
        if json_schema is not None:
            system += "\n\nRespond with a single valid JSON object and nothing else."
        convo = [
            {"role": m.role, "content": m.content}
            for m in messages
            if m.role in ("user", "assistant")
        ]
        resp = self._client.messages.create(
            model=self.model,
            max_tokens=max_tokens,
            temperature=temperature,
            system=system or None,
            messages=convo,
        )
        text = "".join(block.text for block in resp.content if block.type == "text")
        usage = Usage(
            input_tokens=resp.usage.input_tokens,
            output_tokens=resp.usage.output_tokens,
        )
        usage.usd = estimate_cost(self.model, usage.input_tokens, usage.output_tokens)
        raw: dict[str, Any] = {}
        if json_schema is not None:
            match = _JSON_RE.search(text)
            if match:
                raw = json.loads(match.group(0))
                text = match.group(0)
        return LLMResponse(text=text, usage=usage, model=self.model, raw=raw)
