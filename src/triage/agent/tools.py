"""Tool registry: read tools and guarded-action effects.

Read tools (retrieve, history/user lookups) execute freely. Action effects
simulate the *downstream system* (the identity provider, ticketing system, etc.)
and are never called directly by the planner — they are invoked only through the
enterprise-controls executor (see actions.py), which adds auth, approvals,
idempotency, retries, and audit.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from triage.data.db import TicketDB
from triage.rag.retriever import Retriever


@dataclass
class ToolSpec:
    name: str
    description: str
    kind: str  # "read" | "action"
    params: dict[str, str]


# --- Read tools -------------------------------------------------------------

READ_TOOLS = {
    "search_runbooks": ToolSpec(
        "search_runbooks", "Semantic search over the runbook knowledge base.",
        "read", {"query": "free text"}),
    "lookup_ticket_history": ToolSpec(
        "lookup_ticket_history", "Prior tickets from the same requester.",
        "read", {"requester": "email", "exclude_id": "ticket id"}),
    "lookup_user": ToolSpec(
        "lookup_user", "Directory record (name, department, manager).",
        "read", {"email": "email"}),
}


class ReadTools:
    def __init__(self, db: TicketDB, retriever: Retriever) -> None:
        self.db = db
        self.retriever = retriever

    def search_runbooks(self, query: str, k: int = 3) -> list[dict[str, Any]]:
        return [h.__dict__ for h in self.retriever.retrieve(query, k=k)]

    def lookup_ticket_history(self, requester: str, exclude_id: str | None = None) -> list[dict[str, Any]]:
        return [t.to_dict() for t in self.db.history_for(requester, exclude_id)]

    def lookup_user(self, email: str) -> dict[str, Any] | None:
        return self.db.get_user(email)


# --- Guarded-action effects (the simulated downstream system) ---------------

ACTION_TOOLS = {
    "reset_password": ToolSpec(
        "reset_password", "Send a password-reset link and clear the lockout counter.",
        "action", {"email": "email"}),
    "grant_access": ToolSpec(
        "grant_access", "Grant access to a resource/group (least privilege).",
        "action", {"email": "email", "resource": "string"}),
    "escalate": ToolSpec(
        "escalate", "Notify a downstream human team. Notifies only; changes nothing.",
        "action", {"ticket_id": "id", "team": "string"}),
    "post_reply": ToolSpec(
        "post_reply", "Post a reply to the requester on the ticket.",
        "action", {"ticket_id": "id", "text": "string"}),
    "close_ticket": ToolSpec(
        "close_ticket", "Mark the ticket resolved.",
        "action", {"ticket_id": "id"}),
}


def _effect_reset_password(db: TicketDB, email: str, **_: Any) -> dict[str, Any]:
    return {"effect": "password_reset_link_sent", "email": email, "lockout_cleared": True}


def _effect_grant_access(db: TicketDB, email: str, resource: str = "", **_: Any) -> dict[str, Any]:
    return {"effect": "access_granted", "email": email, "resource": resource}


def _effect_escalate(db: TicketDB, ticket_id: str = "", team: str = "on-call", **_: Any) -> dict[str, Any]:
    return {"effect": "escalated", "ticket_id": ticket_id, "team": team}


def _effect_post_reply(db: TicketDB, ticket_id: str = "", text: str = "", **_: Any) -> dict[str, Any]:
    return {"effect": "reply_posted", "ticket_id": ticket_id, "chars": len(text)}


def _effect_close_ticket(db: TicketDB, ticket_id: str = "", **_: Any) -> dict[str, Any]:
    if ticket_id:
        db.set_status(ticket_id, "resolved")
    return {"effect": "ticket_closed", "ticket_id": ticket_id}


ACTION_EFFECTS: dict[str, Callable[..., dict[str, Any]]] = {
    "reset_password": _effect_reset_password,
    "grant_access": _effect_grant_access,
    "escalate": _effect_escalate,
    "post_reply": _effect_post_reply,
    "close_ticket": _effect_close_ticket,
}


def tool_catalog() -> list[dict[str, Any]]:
    """Machine-readable catalog (used by the MCP server and docs)."""
    out = []
    for spec in {**READ_TOOLS, **ACTION_TOOLS}.values():
        out.append({"name": spec.name, "kind": spec.kind,
                    "description": spec.description, "params": spec.params})
    return out
