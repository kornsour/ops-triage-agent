import pytest
from mcp_server.server import MCPCore

from triage.enterprise.auth import AuthError, authenticate


def test_catalog_includes_actions_and_approve(seeded):
    core = MCPCore(authenticate("demo-operator-key"))
    names = {t["name"] for t in core.list_tools()}
    assert {"search_runbooks", "reset_password", "grant_access", "approve_action"} <= names


def test_read_tool_via_mcp(seeded):
    core = MCPCore(authenticate("demo-operator-key"))
    out = core.call_tool("search_runbooks", {"query": "locked out password"})
    assert out["result"][0]["doc_id"] == "kb-password-reset"


def test_action_via_mcp_requires_approval(seeded):
    core = MCPCore(authenticate("demo-operator-key"))
    out = core.call_tool("reset_password", {"email": "dana@acme.com"})
    assert out["status"] == "pending_approval"


def test_viewer_cannot_call_action(seeded):
    core = MCPCore(authenticate("demo-viewer-key"))
    with pytest.raises(AuthError):
        core.call_tool("reset_password", {"email": "dana@acme.com"})


def test_admin_can_approve_via_mcp(seeded):
    op = MCPCore(authenticate("demo-operator-key"))
    pending = op.call_tool("grant_access", {"email": "jordan@acme.com", "resource": "billing"})
    approval_id = pending["approval_id"]

    admin = MCPCore(authenticate("demo-admin-key"))
    out = admin.call_tool("approve_action", {"approval_id": approval_id, "reason": "ok"})
    assert out["status"] == "executed"
