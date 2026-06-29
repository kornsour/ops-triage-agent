"""Prompt construction for the planner and responder steps.

The TICKET/CONTEXT delimiters and [[TASK:*]] tags give the offline mock provider
a stable contract to parse, while reading as ordinary instructions to a real LLM.
Prompt text is versioned (PROMPT_VERSION) so eval reports can attribute quality
changes to prompt changes.
"""

from __future__ import annotations

from triage.llm.base import Message

PROMPT_VERSION = "2026-06-29.1"

_CATEGORIES = (
    "incident, access_password, access_request, network, hardware, productivity, general"
)
_SEVERITIES = "high, medium, low"

_PLAN_SYSTEM = (
    "You are the planner in an IT/Ops support-triage agent. Classify the ticket, "
    "assess severity, and produce a short ordered plan of tool calls. "
    f"Categories: {_CATEGORIES}. Severities: {_SEVERITIES}. "
    "Recommend at most one guarded action from: reset_password, grant_access, "
    "escalate, post_reply, close_ticket (or null). "
    "[[TASK:plan]] Return JSON: {category, severity, summary, plan[], "
    "recommended_action, matched_signals[]}."
)

_RESPOND_SYSTEM = (
    "You are the responder in an IT/Ops support-triage agent. Using ONLY the "
    "retrieved runbook context, draft a concise, helpful reply to the requester "
    "and cite the runbook ids you used. Do not invent steps not in the context. "
    "[[TASK:respond]] Return JSON: {draft_reply, citations[], confidence}."
)


def plan_messages(ticket_text: str, runbook_titles: str) -> list[Message]:
    user = (
        f"<<<TICKET\n{ticket_text}\nTICKET>>>\n\n"
        f"Candidate runbooks:\n{runbook_titles}"
    )
    return [Message("system", _PLAN_SYSTEM), Message("user", user)]


def respond_messages(ticket_text: str, context: str) -> list[Message]:
    user = (
        f"<<<TICKET\n{ticket_text}\nTICKET>>>\n\n"
        f"<<<CONTEXT\n{context}\nCONTEXT>>>"
    )
    return [Message("system", _RESPOND_SYSTEM), Message("user", user)]
