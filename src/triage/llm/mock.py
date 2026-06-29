"""Deterministic, offline mock provider.

This is not a toy stub: it implements genuine keyword/heuristic triage logic so
that the demo, the test suite, and the eval harness all produce *meaningful* and
*reproducible* results with zero API keys. Swapping in a real provider (OpenAI /
Anthropic) is a one-line config change; the agent loop is unchanged.

The mock recognizes two structured tasks emitted by the planner, tagged in the
prompt with ``[[TASK:plan]]`` and ``[[TASK:respond]]``, and returns JSON that
conforms to the requested schema.
"""

from __future__ import annotations

import json
import re
from typing import Any

from .base import LLMResponse, Message, Usage, approx_tokens, estimate_cost

# (keyword set, category, default severity, recommended action)
_RULES: list[tuple[set[str], str, str, str | None]] = [
    ({"outage", "down", "503", "500", "everyone", "all users", "cannot access", "unavailable"},
     "incident", "high", "escalate"),
    ({"password", "locked out", "can't log in", "cannot log in", "reset", "mfa", "2fa"},
     "access_password", "medium", "reset_password"),
    ({"access", "permission", "grant", "role", "repo", "repository", "group", "provision"},
     "access_request", "medium", "grant_access"),
    ({"vpn", "network", "wifi", "wi-fi", "connect", "dns", "proxy"},
     "network", "medium", None),
    ({"laptop", "hardware", "screen", "battery", "keyboard", "device", "monitor"},
     "hardware", "low", "escalate"),
    ({"email", "outlook", "mailbox", "calendar", "smtp", "distribution list"},
     "productivity", "low", None),
]

_HIGH_SEV = {"urgent", "critical", "p1", "asap", "production", "outage", "all users", "everyone"}
_LOW_SEV = {"how do i", "how to", "question", "whenever", "no rush", "nice to have"}
# Negations are checked first so "not urgent" / "no rush" never reads as high.
_NEGATED_URGENCY = ("not urgent", "no rush", "low priority", "whenever you can")


def _extract(prompt: str, tag: str) -> str:
    m = re.search(rf"<<<{tag}\n(.*?)\n{tag}>>>", prompt, re.DOTALL)
    return (m.group(1) if m else "").strip()


def _contains(haystack: str, phrase: str) -> bool:
    """Word-boundary match so 'urgent' does not fire inside 'not urgent'."""
    return re.search(rf"(?<!\w){re.escape(phrase)}(?!\w)", haystack) is not None


def _classify(text: str) -> tuple[str, str, str | None, list[str]]:
    low = text.lower()
    matched: list[str] = []
    category, severity, action = "general", "low", None
    for keywords, cat, sev, act in _RULES:
        hits = [k for k in keywords if _contains(low, k)]
        if hits:
            category, severity, action = cat, sev, act
            matched = hits
            break
    deprioritized = any(neg in low for neg in _NEGATED_URGENCY)
    if not deprioritized and any(_contains(low, k) for k in _HIGH_SEV):
        severity = "high"
    elif (deprioritized or any(_contains(low, k) for k in _LOW_SEV)) and severity != "high":
        severity = "low"
    return category, severity, action, matched


class MockProvider:
    """Deterministic provider implementing the LLMProvider protocol."""

    def __init__(self, model: str = "mock-1") -> None:
        self.model = model

    def complete(
        self,
        messages: list[Message],
        *,
        temperature: float = 0.0,
        max_tokens: int = 1024,
        json_schema: dict[str, Any] | None = None,
    ) -> LLMResponse:
        prompt = "\n".join(m.content for m in messages)
        ticket = _extract(prompt, "TICKET")
        category, severity, action, matched = _classify(ticket)

        if "[[TASK:plan]]" in prompt:
            payload: dict[str, Any] = {
                "category": category,
                "severity": severity,
                "summary": _summary(ticket),
                "plan": _plan_steps(category, action),
                "recommended_action": action,
                "matched_signals": matched,
            }
        elif "[[TASK:respond]]" in prompt:
            context = _extract(prompt, "CONTEXT")
            citations = re.findall(r"\[(kb-[a-z0-9-]+)\]", context)
            payload = {
                "draft_reply": _draft_reply(ticket, context, category, citations),
                "citations": citations[:3],
                "confidence": 0.82 if citations else 0.4,
            }
        else:
            payload = {"text": "ok"}

        text = json.dumps(payload, indent=2)
        usage = Usage(
            input_tokens=approx_tokens(prompt),
            output_tokens=approx_tokens(text),
        )
        usage.usd = estimate_cost(self.model, usage.input_tokens, usage.output_tokens)
        return LLMResponse(text=text, usage=usage, model=self.model, raw=payload)


def _summary(ticket: str) -> str:
    first = ticket.strip().splitlines()[0] if ticket.strip() else "support request"
    return (first[:117] + "...") if len(first) > 120 else first


def _plan_steps(category: str, action: str | None) -> list[str]:
    steps = ["retrieve_runbook", "lookup_ticket_history"]
    if category in {"access_password", "access_request"}:
        steps.append("lookup_user")
    if action:
        steps.append(f"propose:{action}")
    steps.append("draft_response")
    return steps


def _draft_reply(ticket: str, context: str, category: str, citations: list[str]) -> str:
    cite = f" (see {', '.join(citations[:2])})" if citations else ""
    openings = {
        "incident": "Thanks for flagging this — we're treating it as a potential incident and have escalated to the on-call engineer.",
        "access_password": "Thanks for reaching out. I can help restore your access.",
        "access_request": "Thanks for the request. I've routed it for the required approval.",
        "network": "Thanks for reaching out about the connectivity issue.",
        "hardware": "Thanks for reporting the hardware issue.",
        "productivity": "Happy to help with that.",
        "general": "Thanks for contacting support.",
    }
    body = openings.get(category, openings["general"])
    return (
        f"{body} Based on our runbook{cite}, here are the next steps. "
        "I'll follow up once the action above is completed or approved."
    )
