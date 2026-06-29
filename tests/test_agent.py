import pytest

from triage.enterprise.approvals import ApprovalStore
from triage.enterprise.auth import AuthError


def _ticket(db, tid):
    return db.get_ticket(tid)


def test_lockout_is_classified_and_gated(runner, operator):
    result = runner.run(_ticket(runner.db, "TCK-1001"), operator)
    assert result.category == "access_password"
    assert result.action["name"] == "reset_password"
    assert result.status == "needs_approval"
    assert result.action["status"] == "pending_approval"
    assert result.grounded is True
    assert "kb-password-reset" in result.citations


def test_outage_auto_escalates(runner, operator):
    result = runner.run(_ticket(runner.db, "TCK-1004"), operator)
    assert result.category == "incident"
    assert result.severity == "high"
    assert result.action["name"] == "escalate"
    assert result.action["status"] == "executed"
    assert result.status == "completed"


def test_run_emits_full_trace(runner, operator):
    result = runner.run(_ticket(runner.db, "TCK-1002"), operator)
    steps = [s.step for s in result.trace]
    assert steps[:4] == ["retrieve", "plan", "gather", "respond"]
    assert result.metrics["llm_calls"] == 2
    assert result.metrics["total_ms"] >= 0


def test_viewer_cannot_request_action(runner, viewer):
    with pytest.raises(AuthError):
        runner.executor.request(run_id="t", principal=viewer,
                                action="reset_password", args={"email": "a@b.com"})


def test_idempotent_action_request(runner, operator):
    args = {"ticket_id": "TCK-1004", "team": "sre-on-call"}
    r1 = runner.executor.request(run_id="t", principal=operator, action="escalate", args=args)
    r2 = runner.executor.request(run_id="t", principal=operator, action="escalate", args=args)
    assert r1["status"] == "executed"
    assert r2["status"] == "replayed"


def test_full_approval_flow(runner, operator, admin, settings):
    # operator requests a high-risk action -> pending
    req = runner.executor.request(run_id="r1", principal=operator,
                                  action="grant_access",
                                  args={"email": "jordan@acme.com", "resource": "billing"})
    assert req["status"] == "pending_approval"
    approval_id = req["approval_id"]

    # admin approves, then executes
    store = ApprovalStore(settings.db_path)
    store.decide(approval_id, approve=True, decided_by=admin.name, reason="ok")
    out = runner.executor.execute_approved(approval_id=approval_id, principal=admin)
    assert out["status"] == "executed"
    assert out["result"]["effect"] == "access_granted"

    # audit chain stays intact
    ok, _ = runner.executor.audit.verify()
    assert ok


def test_operator_cannot_approve(runner, operator):
    req = runner.executor.request(run_id="r2", principal=operator, action="reset_password",
                                  args={"email": "dana@acme.com"})
    with pytest.raises(AuthError):
        runner.executor.execute_approved(approval_id=req["approval_id"], principal=operator)
