"""TriageRunner — orchestrates one end-to-end triage run and emits a trace."""

from __future__ import annotations

import json
import logging
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any

from triage.agent.actions import ActionExecutor
from triage.agent.prompts import PROMPT_VERSION, plan_messages, respond_messages
from triage.agent.tools import ACTION_EFFECTS, ReadTools
from triage.config import Settings, get_settings
from triage.data.db import Ticket, TicketDB
from triage.enterprise.approvals import ApprovalStore
from triage.enterprise.audit import AuditLog
from triage.enterprise.auth import AuthError, Principal
from triage.llm import get_provider
from triage.llm.base import LLMProvider, LLMResponse
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
    status: str  # completed | needs_approval | auth_error | budget_exceeded
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

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        return d


def _parse(resp: LLMResponse) -> dict[str, Any]:
    if resp.raw:
        return resp.raw
    try:
        return json.loads(resp.text)
    except json.JSONDecodeError:
        return {}


def _action_args(action: str, ticket: Ticket, plan: dict[str, Any], draft: str) -> dict[str, Any]:
    if action == "reset_password":
        return {"email": ticket.requester}
    if action == "grant_access":
        return {"email": ticket.requester, "resource": ticket.subject}
    if action == "escalate":
        team = "sre-on-call" if plan.get("category") == "incident" else "it-field-team"
        return {"ticket_id": ticket.id, "team": team}
    if action == "post_reply":
        return {"ticket_id": ticket.id, "text": draft}
    if action == "close_ticket":
        return {"ticket_id": ticket.id}
    return {}


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

    def run(self, ticket: Ticket, principal: Principal, run_id: str | None = None) -> TriageResult:
        run_id = run_id or f"run-{uuid.uuid4().hex[:12]}"
        metrics = RunMetrics()
        timer = Timer(metrics)
        trace: list[TraceStep] = []
        ticket_text = f"{ticket.subject}\n{ticket.body}"

        # 1) Retrieve candidate runbooks.
        with timer.step("retrieve"):
            hits = self.retriever.retrieve(ticket_text, k=3)
            context = Retriever.format_context(hits)
            titles = "\n".join(f"[{h.doc_id}] {h.title} (score={h.score})" for h in hits) or "(none)"
        retrieved_ids = [h.doc_id for h in hits]
        trace.append(TraceStep("retrieve", metrics.steps["retrieve"],
                               {"hits": retrieved_ids, "top_score": hits[0].score if hits else 0.0}))

        # 2) Plan (LLM call #1).
        with timer.step("plan"):
            presp = self.provider.complete(plan_messages(ticket_text, titles), json_schema={"type": "object"})
            plan = _parse(presp)
            metrics.add_usage(presp.usage.input_tokens, presp.usage.output_tokens, presp.usage.usd)
        category = plan.get("category", "general")
        severity = plan.get("severity", "low")
        recommended_action = plan.get("recommended_action")
        trace.append(TraceStep("plan", metrics.steps["plan"],
                               {"category": category, "severity": severity,
                                "recommended_action": recommended_action,
                                "plan": plan.get("plan", [])}))

        # 3) Gather context with read tools (real DB reads).
        with timer.step("gather"):
            history = self.read.lookup_ticket_history(ticket.requester, ticket.id)
            user = None
            if category in {"access_password", "access_request"}:
                user = self.read.lookup_user(ticket.requester)
        trace.append(TraceStep("gather", metrics.steps["gather"],
                               {"prior_tickets": len(history),
                                "user_found": user is not None,
                                "repeat_requester": len(history) > 0}))

        # 4) Respond (LLM call #2).
        with timer.step("respond"):
            rresp = self.provider.complete(respond_messages(ticket_text, context), json_schema={"type": "object"})
            rdata = _parse(rresp)
            metrics.add_usage(rresp.usage.input_tokens, rresp.usage.output_tokens, rresp.usage.usd)
        draft_reply = rdata.get("draft_reply", "")
        citations = rdata.get("citations", [])
        confidence = float(rdata.get("confidence", 0.0))
        grounded = bool(citations) and set(citations).issubset(set(retrieved_ids))
        trace.append(TraceStep("respond", metrics.steps["respond"],
                               {"citations": citations, "confidence": confidence,
                                "grounded": grounded}))

        # 5) Act — route any guarded action through the enterprise-controls executor.
        action: dict[str, Any] = {"name": recommended_action, "status": "none"}
        status = "completed"
        if recommended_action in ACTION_EFFECTS:
            args = _action_args(recommended_action, ticket, plan, draft_reply)
            action["args"] = args
            with timer.step("act"):
                try:
                    res = self.executor.request(
                        run_id=run_id, principal=principal,
                        action=recommended_action, args=args,
                    )
                    action.update(res)
                    if res["status"] == "pending_approval":
                        status = "needs_approval"
                except AuthError as exc:
                    action.update({"status": "blocked", "reason": str(exc)})
                    status = "auth_error"
            trace.append(TraceStep("act", metrics.steps.get("act", 0.0),
                                   {"action": recommended_action, "status": action["status"]}))

        # 6) Budget enforcement.
        if metrics.usd > self.settings.max_usd_per_run or metrics.total_ms > self.settings.max_latency_ms:
            status = "budget_exceeded"

        result = TriageResult(
            run_id=run_id, ticket_id=ticket.id, status=status,
            category=category, severity=severity, summary=plan.get("summary", ""),
            plan=plan.get("plan", []), draft_reply=draft_reply, citations=citations,
            confidence=confidence, grounded=grounded, action=action,
            metrics=metrics.to_dict(), trace=trace,
        )
        self.db.save_run(run_id, ticket.id, status, result.to_dict())
        log_event(logger, logging.INFO, "triage_run_complete", run_id=run_id,
                  ticket_id=ticket.id, status=status, category=category,
                  severity=severity, grounded=grounded, usd=metrics.usd,
                  total_ms=metrics.total_ms)
        return result
