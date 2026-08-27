"""Guarded-action executor — the single chokepoint every side-effect passes through.

Wires together the enterprise controls so that *no* action can execute without:
    auth          requester is at least an operator; approver is an admin
    rate limit    per-principal token bucket
    idempotency   identical (action, args) executes once, then replays
    approval      medium/high-risk actions need an admin decision first
    sandbox       the effect itself runs inside an execution boundary, not
                  bare in this process — see triage.sandbox and docs/sandbox.md
    retry         bounded backoff around the (flaky) downstream effect
    audit         every request / decision / execution — and every sandbox
                  containment failure — is hash-chained
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
from triage.sandbox import Sandbox, SandboxContainmentError, SandboxEffectError, build_sandbox


class ActionExecutor:
    def __init__(
        self,
        db: TicketDB,
        audit: AuditLog,
        approvals: ApprovalStore,
        *,
        idempotency: IdempotencyStore | None = None,
        buckets: dict[str, TokenBucket] | None = None,
        now_fn: Callable[[], float] = time.time,
        sleep_fn: Callable[[float], None] = lambda _s: None,
        sandbox: Sandbox | None = None,
    ) -> None:
        s = get_settings()
        self.db = db
        self.audit = audit
        self.approvals = approvals
        # Every effect runs through this boundary rather than being called
        # bare — same-process by default (`InProcessSandbox`, wired via
        # `build_sandbox`), a locked-down container when configured. See
        # triage.sandbox and docs/sandbox.md.
        self.sandbox = sandbox if sandbox is not None else build_sandbox(s)
        self._sandbox_timeout_s = s.sandbox_timeout_s
        # Shares `db`'s SQLite file, so every `ActionExecutor` built against
        # the same db_path — a fresh process after a restart, or a sibling
        # replica behind a load balancer — replays the same results.
        self.idempotency = idempotency or IdempotencyStore(db.db_path)
        self._rate_limit_per_min = s.rate_limit_per_min
        # One TokenBucket per principal, keyed on api_key, so one caller's
        # traffic can't exhaust another's allowance. Pre-seeded from the
        # configured API keys — that both gives every known principal its own
        # bucket up front and bounds the dict's size, since `authenticate()`
        # never hands back a `Principal` whose key isn't in that same set.
        self.buckets: dict[str, TokenBucket] = (
            buckets if buckets is not None
            else {api_key: self._new_bucket() for api_key in s.parsed_api_keys()}
        )
        self.now_fn = now_fn
        self.sleep_fn = sleep_fn

    def _new_bucket(self) -> TokenBucket:
        return TokenBucket(
            capacity=self._rate_limit_per_min,
            refill_per_sec=self._rate_limit_per_min / 60.0,
        )

    def _bucket_for(self, principal: Principal) -> TokenBucket:
        # Defensive fallback only: every `Principal` reaching here came from
        # `authenticate()`, so its key is already in `self.buckets`. This
        # avoids a KeyError rather than being a growth path in practice.
        bucket = self.buckets.get(principal.api_key)
        if bucket is None:
            bucket = self._new_bucket()
            self.buckets[principal.api_key] = bucket
        return bucket

    def _run_effect(self, action: str, args: dict[str, Any]) -> dict[str, Any]:
        """Run the action's effect through `self.sandbox`.

        A business-logic exception from the effect itself
        (`SandboxEffectError`, and — for parity with an in-process direct
        call — an unexpected error from the sandbox's own plumbing) is
        retried like any flaky downstream call always has been here. A
        containment failure (`SandboxContainmentError`: the boundary timed
        the action out, killed it, or denied it before it ran) is *not*
        retried — it is a security-relevant event in its own right, not
        transient noise, and the caller (`request` / `execute_approved`)
        turns it into an audited, structured "contained" result rather than
        an unhandled exception.

        `close_ticket` is the one action with genuine host-side state (it
        marks the ticket resolved in `self.db`); the sandboxed effect itself
        only ever sees JSON args, never a database handle (see
        triage.sandbox.effects), so that write is applied here, by the
        trusted host, once the sandboxed call has actually completed —
        never speculatively, and never by the sandboxed code itself.
        """

        def attempt() -> dict[str, Any]:
            result = self.sandbox.run(action=action, args=args, timeout_s=self._sandbox_timeout_s)
            if result.status.value != "completed":
                raise SandboxContainmentError(action, result)
            return result.output or {}

        # Only a business-logic exception from the effect itself is retried
        # (`SandboxEffectError`, matching the old "retry the flaky effect
        # call" behavior). `SandboxContainmentError` is a different type, so
        # `retry_on` never catches it — it propagates on the first attempt.
        output = retry(attempt, attempts=3, sleep=self.sleep_fn, retry_on=(SandboxEffectError,))
        if action == "close_ticket" and args.get("ticket_id"):
            self.db.set_status(args["ticket_id"], "resolved")
        return output

    def _handle_containment_failure(
        self,
        *,
        principal: Principal,
        action: str,
        args: dict[str, Any],
        risk: str,
        exc: SandboxContainmentError,
        run_id: str | None = None,
        approval_id: str | None = None,
    ) -> dict[str, Any]:
        result = exc.result
        metadata: dict[str, Any] = {
            "risk": risk, "sandbox_status": result.status.value,
            "reason": result.error, "duration_ms": round(result.duration_ms, 2),
            **result.detail,
        }
        if run_id is not None:
            metadata["run_id"] = run_id
        if approval_id is not None:
            metadata["approval_id"] = approval_id
        self.audit.record(actor=principal.name, action=action, target=str(args),
                          outcome=f"sandbox_{result.status.value}", metadata=metadata)
        return {"status": "contained", "action": action, "risk": risk,
                "sandbox_status": result.status.value, "reason": result.error}

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
        self._bucket_for(principal).acquire(self.now_fn())

        risk, auto_approve, _approver = policy_for(action)
        key = make_key(action, args)

        if self.idempotency.seen(key):
            return {"status": "replayed", "action": action,
                    "result": self.idempotency.get(key)}

        # A prior request for this exact (action, args) may already have been
        # decided. `approval_id` is derived from `key`, so an identical
        # re-request would otherwise silently no-op the INSERT below and get
        # told "pending" again — even though it was denied, or already
        # executed. Surface the real outcome instead.
        existing = self.approvals.get(key)
        if existing is not None and existing.status == "denied":
            self.audit.record(actor=principal.name, action=action, target=str(args),
                              outcome="denied_replay",
                              metadata={"run_id": run_id, "risk": risk, "approval_id": key,
                                        "reason": existing.reason})
            return {"status": "denied", "action": action, "risk": risk,
                    "approval_id": key, "reason": existing.reason}
        if existing is not None and existing.status == "executed":
            return {"status": "replayed", "action": action,
                    "result": self.idempotency.get(key)}

        if auto_approve and not force_approval:
            try:
                result = self._run_effect(action, args)
            except SandboxContainmentError as exc:
                return self._handle_containment_failure(
                    principal=principal, action=action, args=args, risk=risk,
                    exc=exc, run_id=run_id)
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

        try:
            result = self._run_effect(decision.action, decision.args)
        except SandboxContainmentError as exc:
            return self._handle_containment_failure(
                principal=principal, action=decision.action, args=decision.args,
                risk=decision.risk, exc=exc, approval_id=approval_id)
        self.idempotency.remember(key, result)
        self.approvals.mark_executed(approval_id)
        self.audit.record(actor=principal.name, action=decision.action,
                          target=str(decision.args), outcome="executed",
                          metadata={"approval_id": approval_id, "risk": decision.risk,
                                    "approved_by": decision.decided_by})
        return {"status": "executed", "action": decision.action, "result": result}
