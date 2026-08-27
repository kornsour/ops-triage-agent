"""Pure guarded-action business logic — the code that actually crosses the
sandbox boundary.

Deliberately dependency-free (stdlib only, no import of anything else under
`triage.*`): `InProcessSandbox` imports this module directly, and
`ContainerSandbox` bind-mounts *this exact file* read-only into the
container and runs it there via `runtime/runner_main.py` — one source of
truth for both runtimes, so they can never drift apart.

Each function takes only JSON-serializable keyword arguments and returns a
JSON-serializable dict — no database handle, no file, no other shared state.
That is the whole contract: what crosses the boundary is `(action, args) ->
output`, nothing else. The one action with genuine host-side state
(`close_ticket` marking a ticket resolved) applies that write back on the
trusted host side, in `triage.agent.actions.ActionExecutor`, after the
sandboxed call returns — see the note there.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any


def pure_reset_password(*, email: str = "", **_: Any) -> dict[str, Any]:
    return {"effect": "password_reset_link_sent", "email": email, "lockout_cleared": True}


def pure_grant_access(*, email: str = "", resource: str = "", **_: Any) -> dict[str, Any]:
    return {"effect": "access_granted", "email": email, "resource": resource}


def pure_escalate(*, ticket_id: str = "", team: str = "on-call", **_: Any) -> dict[str, Any]:
    return {"effect": "escalated", "ticket_id": ticket_id, "team": team}


def pure_post_reply(*, ticket_id: str = "", text: str = "", **_: Any) -> dict[str, Any]:
    return {"effect": "reply_posted", "ticket_id": ticket_id, "chars": len(text)}


def pure_close_ticket(*, ticket_id: str = "", **_: Any) -> dict[str, Any]:
    return {"effect": "ticket_closed", "ticket_id": ticket_id}


PURE_ACTION_EFFECTS: dict[str, Callable[..., dict[str, Any]]] = {
    "reset_password": pure_reset_password,
    "grant_access": pure_grant_access,
    "escalate": pure_escalate,
    "post_reply": pure_post_reply,
    "close_ticket": pure_close_ticket,
}
