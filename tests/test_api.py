import pytest
from fastapi.testclient import TestClient

from triage.api.server import AppState, create_app

VIEWER = {"X-API-Key": "demo-viewer-key"}
OPERATOR = {"X-API-Key": "demo-operator-key"}
ADMIN = {"X-API-Key": "demo-admin-key"}


@pytest.fixture
def client(seeded):
    return TestClient(create_app(AppState()))


def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_auth_required(client):
    assert client.get("/tickets").status_code == 401


def test_viewer_lists_tickets(client):
    r = client.get("/tickets", headers=VIEWER)
    assert r.status_code == 200
    assert len(r.json()) >= 8


def test_viewer_cannot_triage(client):
    assert client.post("/triage/TCK-1001", headers=VIEWER).status_code == 403


def test_triage_then_approve_flow(client):
    # Operator runs triage on a lockout -> action held for approval.
    r = client.post("/triage/TCK-1001", headers=OPERATOR)
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "needs_approval"
    approval_id = body["action"]["approval_id"]

    # Pending approval is visible.
    pend = client.get("/approvals", params={"status": "pending"}, headers=VIEWER).json()
    assert any(a["approval_id"] == approval_id for a in pend)

    # Viewer cannot decide.
    assert client.post(f"/approvals/{approval_id}/decide", json={"approve": True},
                       headers=VIEWER).status_code == 403

    # Admin approves -> action executes.
    dec = client.post(f"/approvals/{approval_id}/decide",
                      json={"approve": True, "reason": "verified identity"}, headers=ADMIN)
    assert dec.status_code == 200
    assert dec.json()["execution"]["status"] == "executed"

    # Deciding again is a conflict.
    again = client.post(f"/approvals/{approval_id}/decide", json={"approve": True}, headers=ADMIN)
    assert again.status_code == 409


def test_audit_chain_verifies(client):
    client.post("/triage/TCK-1004", headers=OPERATOR)  # generates an audited escalate
    r = client.get("/audit/verify", headers=VIEWER)
    assert r.status_code == 200
    assert r.json()["ok"] is True
