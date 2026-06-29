"""FastAPI backend.

Auth is via the `X-API-Key` header → role. The same shared `ActionExecutor` and
`ApprovalStore` back both triage runs and approval decisions, so idempotency and
the audit chain are consistent across the whole API. The React dashboard talks
to these endpoints.
"""

from __future__ import annotations

from typing import Any

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from triage.agent.actions import ActionExecutor
from triage.agent.runner import TriageRunner
from triage.agent.tools import tool_catalog
from triage.config import get_settings
from triage.data.db import TicketDB
from triage.data.seed import seed
from triage.enterprise.approvals import ApprovalStore
from triage.enterprise.audit import AuditLog
from triage.enterprise.auth import AuthError, Principal, authenticate, require_role
from triage.rag.ingest import ingest
from triage.rag.retriever import Retriever
from triage.rag.store import VectorStore


class AppState:
    def __init__(self) -> None:
        s = get_settings()
        if not s.db_path.exists():
            seed()
        if not VectorStore.exists(s.index_dir):
            ingest(verbose=False)
        self.settings = s
        self.db = TicketDB(s.db_path)
        self.retriever = Retriever.from_settings(s)
        self.audit = AuditLog(s.audit_path)
        self.approvals = ApprovalStore(s.db_path)
        self.executor = ActionExecutor(self.db, self.audit, self.approvals)
        self.runner = TriageRunner(settings=s, db=self.db, retriever=self.retriever,
                                   executor=self.executor)


class DecideBody(BaseModel):
    approve: bool
    reason: str | None = None


def create_app(state: AppState | None = None) -> FastAPI:
    state = state or AppState()
    app = FastAPI(title="ops-triage-agent", version="0.1.0",
                  description="Enterprise agentic IT/Ops support triage.")
    app.add_middleware(
        CORSMiddleware, allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
        allow_methods=["*"], allow_headers=["*"],
    )
    app.state.app_state = state

    def principal_dep(x_api_key: str | None = Header(default=None)) -> Principal:
        try:
            return authenticate(x_api_key, state.settings)
        except AuthError as exc:
            raise HTTPException(status_code=401, detail=str(exc)) from exc

    def require(principal: Principal, role: str) -> None:
        try:
            require_role(principal, role)
        except AuthError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc

    @app.get("/health")
    def health() -> dict[str, Any]:
        return {"status": "ok", "provider": state.settings.llm_provider,
                "tickets": len(state.db.list_tickets()), "runbooks": len(state.retriever.store)}

    @app.get("/tools")
    def tools() -> list[dict[str, Any]]:
        return tool_catalog()

    @app.get("/tickets")
    def list_tickets(p: Principal = Depends(principal_dep)) -> list[dict[str, Any]]:
        require(p, "viewer")
        return [t.to_dict() for t in state.db.list_tickets()]

    @app.get("/tickets/{ticket_id}")
    def get_ticket(ticket_id: str, p: Principal = Depends(principal_dep)) -> dict[str, Any]:
        require(p, "viewer")
        t = state.db.get_ticket(ticket_id)
        if t is None:
            raise HTTPException(404, "ticket not found")
        return t.to_dict()

    @app.post("/triage/{ticket_id}")
    def triage(ticket_id: str, p: Principal = Depends(principal_dep)) -> dict[str, Any]:
        require(p, "operator")
        t = state.db.get_ticket(ticket_id)
        if t is None:
            raise HTTPException(404, "ticket not found")
        return state.runner.run(t, p).to_dict()

    @app.get("/runs")
    def list_runs(p: Principal = Depends(principal_dep)) -> list[dict[str, Any]]:
        require(p, "viewer")
        return state.db.list_runs()

    @app.get("/runs/{run_id}")
    def get_run(run_id: str, p: Principal = Depends(principal_dep)) -> dict[str, Any]:
        require(p, "viewer")
        r = state.db.get_run(run_id)
        if r is None:
            raise HTTPException(404, "run not found")
        return r

    @app.get("/approvals")
    def list_approvals(status: str | None = None,
                       p: Principal = Depends(principal_dep)) -> list[dict[str, Any]]:
        require(p, "viewer")
        return [d.__dict__ for d in state.approvals.list(status)]

    @app.post("/approvals/{approval_id}/decide")
    def decide(approval_id: str, body: DecideBody,
               p: Principal = Depends(principal_dep)) -> dict[str, Any]:
        require(p, "admin")
        try:
            decision = state.approvals.decide(
                approval_id, approve=body.approve, decided_by=p.name, reason=body.reason)
        except KeyError as exc:
            raise HTTPException(404, "approval not found") from exc
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc
        out: dict[str, Any] = {"decision": decision.__dict__}
        if body.approve:
            out["execution"] = state.executor.execute_approved(
                approval_id=approval_id, principal=p)
        return out

    @app.get("/audit")
    def audit(p: Principal = Depends(principal_dep)) -> list[dict[str, Any]]:
        require(p, "viewer")
        return state.audit.entries()

    @app.get("/audit/verify")
    def audit_verify(p: Principal = Depends(principal_dep)) -> dict[str, Any]:
        require(p, "viewer")
        ok, msg = state.audit.verify()
        return {"ok": ok, "message": msg, "entries": len(state.audit.entries())}

    @app.get("/evals/latest")
    def evals_latest(p: Principal = Depends(principal_dep)) -> dict[str, Any]:
        require(p, "viewer")
        import json
        from pathlib import Path

        reports = sorted((Path.cwd() / "evals" / "reports").glob("*.json"))
        if not reports:
            raise HTTPException(404, "no eval reports yet — run `make eval`")
        return json.loads(reports[-1].read_text())

    return app


app = create_app()
