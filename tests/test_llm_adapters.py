"""Recorded-response tests for the real provider adapters.

The OpenAI/Anthropic SDKs are optional deps and never called over the network in
CI. These tests inject a fake client that replays a canned API response (the
shape each SDK actually returns) so the adapter's response-mapping and cost
accounting are exercised offline — closing the gap that the live paths would
otherwise be untested.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

from triage.llm.anthropic_provider import AnthropicProvider
from triage.llm.base import Message
from triage.llm.openai_provider import OpenAIProvider

# A canned final-answer payload matching the agent loop's JSON contract.
_FINAL = {
    "final": {
        "category": "access_password", "severity": "medium",
        "summary": "Password lockout", "draft_reply": "We'll reset it.",
        "citations": ["kb-password-reset"], "confidence": 0.82,
        "recommended_action": "reset_password",
    }
}
_MSGS = [Message("system", "triage agent"), Message("user", "<<<TICKET\n...\nTICKET>>>")]


def _new(cls):
    """Build a provider without running __init__ (skips SDK import + api key check)."""
    return object.__new__(cls)


def test_openai_adapter_maps_response_and_cost():
    p = _new(OpenAIProvider)
    p.model = "gpt-4.1"

    def create(**kwargs):
        assert kwargs["response_format"] == {"type": "json_object"}
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(_FINAL)))],
            usage=SimpleNamespace(prompt_tokens=1000, completion_tokens=500),
        )

    p._client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))

    resp = p.complete(_MSGS, json_schema={"type": "object"})
    assert resp.raw["final"]["recommended_action"] == "reset_password"
    assert resp.usage.input_tokens == 1000
    assert resp.usage.output_tokens == 500
    # gpt-4.1 pricing: (1000 * 2.00 + 500 * 8.00) / 1e6
    assert resp.usage.usd == round((1000 * 2.00 + 500 * 8.00) / 1_000_000, 8)


def test_anthropic_adapter_extracts_json_from_text():
    p = _new(AnthropicProvider)
    p.model = "claude-opus-4-8"

    # Anthropic has no JSON mode; the adapter must pull the JSON object out of text.
    reply = "Here is the result:\n" + json.dumps(_FINAL) + "\nHope that helps."

    def create(**kwargs):
        assert "single valid JSON object" in kwargs["system"]
        return SimpleNamespace(
            content=[SimpleNamespace(type="text", text=reply)],
            usage=SimpleNamespace(input_tokens=800, output_tokens=400),
        )

    p._client = SimpleNamespace(messages=SimpleNamespace(create=create))

    resp = p.complete(_MSGS, json_schema={"type": "object"})
    assert resp.raw["final"]["category"] == "access_password"
    assert resp.text.startswith("{") and resp.text.endswith("}")  # trimmed to the JSON
    assert resp.usage.input_tokens == 800
    assert resp.usage.usd > 0
