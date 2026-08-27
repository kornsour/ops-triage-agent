"""TriageRunner — orchestrates one end-to-end triage run and emits a trace.

The agent runs a tool-calling loop: the model decides which read tools to call,
the runner executes them and feeds the observations back, and the loop repeats
until the model returns a final answer (or the step budget is hit). Any
recommended guarded action is then routed through the enterprise-controls
executor. Untrusted-content detection forces every action through human approval.
"""

from __future__ import annotations

import json
import logging
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any

from triage.agent.actions import ActionExecutor
from triage.agent.prompts import PROMPT_VERSION, agent_messages, observation_message
from triage.agent.tools import ACTION_EFFECTS, ReadTools
from triage.config import Settings, get_settings
from triage.data.db import Ticket, TicketDB
from triage.enterprise.approvals import ApprovalStore
from triage.enterprise.audit import AuditLog
from triage.enterprise.auth import AuthError, Principal
from triage.enterprise.guardrails import scan as scan_injection
from triage.llm import get_provider
from triage.llm.base import LLMProvider, LLMResponse, Message
from triage.observability.logging import get_logger, log_event
from triage.observability.metrics import RunMetrics, Timer
from triage.rag.retriever import Retriever

logger = get_logger("triage.runner")


@dataclass
class TraceStep:
    step: str
    ms: float
    detail: dict[str, Any]


@dataclass
class TriageResult:
    run_id: str
    ticket_id: str
    # completed | needs_approval | denied | auth_error | budget_exceeded | step_budget_exceeded
    status: str
    category: str
    severity: str
    summary: str
    plan: list[str]
    draft_reply: str
    citations: list[str]
    confidence: float
    grounded: bool
    action: dict[str, Any]
    metrics: dict[str, Any]
    trace: list[TraceStep] = field(default_factory=list)
    prompt_version: str = PROMPT_VERSION
    injection_detected: bool = False
    injection_signals: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _parse(resp: LLMResponse) -> dict[str, Any]:
    if resp.raw:
        return resp.raw
    try:
        return json.loads(resp.text)
    except json.JSONDecodeError:
        return {}


def _action_args(action: str, ticket: Ticket, category: str, draft: str) -> dict[str, Any]:
    if action == "reset_password":
        return {"email": ticket.requester}
    if action == "grant_access":
        return {"email": ticket.requester, "resource": ticket.subject}
    if action == "escalate":
        team = "sre-on-call" if category == "incident" else "it-field-team"
        return {"ticket_id": ticket.id, "team": team}
    if action == "post_reply":
        return {"ticket_id": ticket.id, "text": draft}
    if action == "close_ticket":
        return {"ticket_id": ticket.id}
    return {}


def _short(args: dict[str, Any]) -> str:
    return ", ".join(f"{k}={v}" for k, v in args.items())[:60]


class TriageRunner:
    def __init__(
        self,
        *,
        settings: Settings | None = None,
        provider: LLMProvider | None = None,
        db: TicketDB | None = None,
        retriever: Retriever | None = None,
        executor: ActionExecutor | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.provider = provider or get_provider(self.settings)
        self.db = db or TicketDB(self.settings.db_path)
        self.retriever = retriever or Retriever.from_settings(self.settings)
        self.read = ReadTools(self.db, self.retriever)
        if executor is None:
            audit = AuditLog(self.settings.audit_path)
            approvals = ApprovalStore(self.settings.db_path)
            executor = ActionExecutor(self.db, audit, approvals)
        self.executor = executor

    def _dispatch(self, name: str, args: dict[str, Any], ticket: Ticket) -> tuple[Any, list[str]]:
        """Execute one read tool. Returns (observation, retrieved_runbook_ids)."""
        if name == "search_runbooks":
            hits = self.retriever.retrieve(args.get("query", ""), k=3)
            ids = [h.doc_id for h in hits]
            return Retriever.format_context(hits), ids
        if name == "lookup_ticket_history":
            requester = args.get("requester") or ticket.requester
            history = self.read.lookup_ticket_history(requester, ticket.id)
            return {"prior_tickets": len(history),
                    "subjects": [h["subject"] for h in history]}, []
        if name == "lookup_user":
            email = args.get("email") or ticket.requester
            return {"user": self.read.lookup_user(email)}, []
        return {"error": f"unknown tool {name!r}"}, []

    def run(self, ticket: Ticket, principal: Principal, run_id: str | None = None) -> TriageResult:
        run_id = run_id or f"run-{uuid.uuid4().hex[:12]}"
        metrics = RunMetrics()
        timer = Timer(metrics)
        trace: list[TraceStep] = []

        # 0) Guardrail — scan the untrusted ticket for prompt-injection attempts.
        with timer.step("guard"):
            signals = scan_injection(f"{ticket.subject}\n{ticket.body}")
        injection = bool(signals)
        trace.append(TraceStep("guard", metrics.steps["guard"],
                               {"injection_detected": injection, "signals": signals}))

        # 1) Tool-calling loop — the model chooses read tools until it finalizes.
        messages: list[Message] = agent_messages(ticket)
        retrieved_ids: list[str] = []
        plan: list[str] = []
        final: dict[str, Any] = {}
        finalized = False
        for i in range(self.settings.max_agent_steps):
            key = f"llm_{i}"
            with timer.step(key):
                resp = self.provider.complete(messages, json_schema={"type": "object"})
            metrics.add_usage(resp.usage.input_tokens, resp.usage.output_tokens, resp.usage.usd)
            data = _parse(resp)
            calls = data.get("tool_calls") or []

            if calls and "final" not in data:
                observations: list[dict[str, Any]] = []
                for call in calls:
                    name, args = call.get("name", ""), call.get("args", {}) or {}
                    obs, ids = self._dispatch(name, args, ticket)
                    retrieved_ids.extend(ids)
                    observations.append({"tool": name, "args": args, "result": obs})
                    plan.append(f"{name}({_short(args)})")
                trace.append(TraceStep("reason", metrics.steps[key],
                                       {"reasoning": data.get("reasoning", ""),
                                        "tools": [c.get("name") for c in calls]}))
                messages.append(Message("assistant", resp.text))
                messages.append(observation_message(observations))
                continue

            final = data.get("final", data)
            plan.append("draft_response")
            trace.append(TraceStep("respond", metrics.steps[key],
                                   {"citations": final.get("citations", []),
                                    "confidence": final.get("confidence", 0.0)}))
            finalized = True
            break

        category = final.get("category", "general")
        severity = final.get("severity", "low")
        draft_reply = final.get("draft_reply", "")
        citations = final.get("citations", [])
        confidence = float(final.get("confidence", 0.0))
        recommended_action = final.get("recommended_action")
        grounded = bool(citations) and set(citations).issubset(set(retrieved_ids))

        # 2) Act — route any guarded action through the enterprise-controls executor.
        # An agent that exhausted its step budget without emitting `final` never
        # answered, so it gets its own status and never reaches the act phase —
        # it has no vetted recommendation to act on.
        action: dict[str, Any] = {"name": recommended_action, "status": "none"}
        status = "completed" if finalized else "step_budget_exceeded"
        if finalized and recommended_action in ACTION_EFFECTS:
            args = _action_args(recommended_action, ticket, category, draft_reply)
            action["args"] = args
            with timer.step("act"):
                try:
                    res = self.executor.request(
                        run_id=run_id, principal=principal,
                        action=recommended_action, args=args,
                        force_approval=injection,
                    )
                    action.update(res)
                    if res["status"] == "pending_approval":
                        status = "needs_approval"
                    elif res["status"] == "denied":
                        status = "denied"
                except AuthError as exc:
                    action.update({"status": "blocked", "reason": str(exc)})
                    status = "auth_error"
            trace.append(TraceStep("act", metrics.steps.get("act", 0.0),
                                   {"action": recommended_action, "status": action["status"]}))

        # 3) Budget enforcement.
        if metrics.usd > self.settings.max_usd_per_run or metrics.total_ms > self.settings.max_latency_ms:
            status = "budget_exceeded"

        result = TriageResult(
            run_id=run_id, ticket_id=ticket.id, status=status,
            category=category, severity=severity, summary=final.get("summary", ""),
            plan=plan, draft_reply=draft_reply, citations=citations,
            confidence=confidence, grounded=grounded, action=action,
            metrics=metrics.to_dict(), trace=trace,
            injection_detected=injection, injection_signals=signals,
        )
        self.db.save_run(run_id, ticket.id, status, result.to_dict())
        log_event(logger, logging.INFO, "triage_run_complete", run_id=run_id,
                  ticket_id=ticket.id, status=status, category=category,
                  severity=severity, grounded=grounded, injection=injection,
                  usd=metrics.usd, total_ms=metrics.total_ms)
        return result
