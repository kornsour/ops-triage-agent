"""Guarded-action executor — the single chokepoint every side-effect passes through.

Wires together the enterprise controls so that *no* action can execute without:
    auth          requester is at least an operator; approver is an admin
    rate limit    per-principal token bucket
    idempotency   identical (action, args) executes once, then replays
    approval      medium/high-risk actions need an admin decision first
    retry         bounded backoff around the (flaky) downstream effect
    audit         every request / decision / execution is hash-chained
"""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

from triage.agent.tools import ACTION_EFFECTS
from triage.config import get_settings
from triage.data.db import TicketDB
from triage.enterprise.approvals import ApprovalStore, policy_for
from triage.enterprise.audit import AuditLog
from triage.enterprise.auth import Principal, require_role
from triage.enterprise.idempotency import IdempotencyStore, make_key
from triage.enterprise.ratelimit import TokenBucket
from triage.enterprise.retry import retry


class ActionExecutor:
    def __init__(
        self,
        db: TicketDB,
        audit: AuditLog,
        approvals: ApprovalStore,
        *,
        idempotency: IdempotencyStore | None = None,
        bucket: TokenBucket | None = None,
        now_fn: Callable[[], float] = time.time,
        sleep_fn: Callable[[float], None] = lambda _s: None,
    ) -> None:
        s = get_settings()
        self.db = db
        self.audit = audit
        self.approvals = approvals
        self.idempotency = idempotency or IdempotencyStore()
        self.bucket = bucket or TokenBucket(
            capacity=s.rate_limit_per_min, refill_per_sec=s.rate_limit_per_min / 60.0
        )
        self.now_fn = now_fn
        self.sleep_fn = sleep_fn

    def _run_effect(self, action: str, args: dict[str, Any]) -> dict[str, Any]:
        effect = ACTION_EFFECTS[action]
        return retry(lambda: effect(self.db, **args), attempts=3, sleep=self.sleep_fn)

    def request(
        self, *, run_id: str, principal: Principal, action: str, args: dict[str, Any],
        force_approval: bool = False,
    ) -> dict[str, Any]:
        """Route a guarded action through the controls.

        `force_approval` holds even a normally auto-approved action for human
        review — used when the triage input was flagged as untrusted (e.g. a
        prompt-injection attempt), so nothing can auto-execute off tainted input.
        """
        if action not in ACTION_EFFECTS:
            raise ValueError(f"unknown action {action!r}")
        require_role(principal, "operator")
        self.bucket.acquire(self.now_fn())

        risk, auto_approve, _approver = policy_for(action)
        key = make_key(action, args)

        if self.idempotency.seen(key):
            return {"status": "replayed", "action": action,
                    "result": self.idempotency.get(key)}

        if auto_approve and not force_approval:
            result = self._run_effect(action, args)
            self.idempotency.remember(key, result)
            self.audit.record(actor=principal.name, action=action, target=str(args),
                              outcome="executed",
                              metadata={"run_id": run_id, "risk": risk, "auto_approved": True})
            return {"status": "executed", "action": action, "risk": risk, "result": result}

        held_reason = "untrusted_content" if (force_approval and auto_approve) else None
        self.approvals.create(approval_id=key, run_id=run_id, action=action,
                              args=args, risk=risk, requested_by=principal.name)
        self.audit.record(actor=principal.name, action=action, target=str(args),
                          outcome="approval_requested",
                          metadata={"run_id": run_id, "risk": risk, "approval_id": key,
                                    "held_reason": held_reason})
        out = {"status": "pending_approval", "action": action, "risk": risk,
               "approval_id": key}
        if held_reason:
            out["held_reason"] = held_reason
        return out

    def execute_approved(self, *, approval_id: str, principal: Principal) -> dict[str, Any]:
        require_role(principal, "admin")
        decision = self.approvals.get(approval_id)
        if decision is None:
            raise KeyError(approval_id)
        if decision.status != "approved":
            raise ValueError(f"approval {approval_id} is {decision.status}, not approved")

        key = approval_id
        if self.idempotency.seen(key):
            return {"status": "replayed", "result": self.idempotency.get(key)}

        result = self._run_effect(decision.action, decision.args)
        self.idempotency.remember(key, result)
        self.approvals.mark_executed(approval_id)
        self.audit.record(actor=principal.name, action=decision.action,
                          target=str(decision.args), outcome="executed",
                          metadata={"approval_id": approval_id, "risk": decision.risk,
                                    "approved_by": decision.decided_by})
        return {"status": "executed", "action": decision.action, "result": result}
