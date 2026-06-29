"""An MCP server that exposes the triage tools — with enterprise controls.

This is the differentiator for an enterprise AI platform: a standard Model
Context Protocol server, but every tool call is mediated by the same controls the
agent uses. Read tools require a `viewer`; guarded actions require an `operator`
and return *pending_approval* for medium/high-risk actions rather than executing;
an `admin` completes them via the `approve_action` tool. Everything is audited.

The protocol-facing async handlers are thin wrappers over the sync, fully
unit-testable `MCPCore` below.

Run the server (stdio transport):
    TRIAGE_MCP_API_KEY=demo-operator-key uv run python -m mcp_server.server
"""

from __future__ import annotations

import json
import os
from typing import Any

from triage.agent.actions import ActionExecutor
from triage.agent.tools import ACTION_TOOLS, READ_TOOLS, ReadTools, tool_catalog
from triage.config import get_settings
from triage.data.db import TicketDB
from triage.enterprise.approvals import ApprovalStore
from triage.enterprise.audit import AuditLog
from triage.enterprise.auth import Principal, authenticate, require_role
from triage.rag.retriever import Retriever

APPROVE_TOOL = {
    "name": "approve_action",
    "kind": "action",
    "description": "Admin-only: approve and execute a pending guarded action.",
    "params": {"approval_id": "string", "reason": "string"},
}


class MCPCore:
    """Transport-independent core: build once, call `call_tool` per request."""

    def __init__(self, principal: Principal) -> None:
        s = get_settings()
        self.principal = principal
        self.db = TicketDB(s.db_path)
        self.read = ReadTools(self.db, Retriever.from_settings(s))
        self.executor = ActionExecutor(
            self.db, AuditLog(s.audit_path), ApprovalStore(s.db_path)
        )

    # -- discovery --
    @staticmethod
    def list_tools() -> list[dict[str, Any]]:
        return [*tool_catalog(), APPROVE_TOOL]

    # -- dispatch --
    def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        arguments = arguments or {}
        if name in READ_TOOLS:
            require_role(self.principal, "viewer")
            fn = getattr(self.read, name)
            return {"tool": name, "result": fn(**arguments)}

        if name in ACTION_TOOLS:
            require_role(self.principal, "operator")
            return self.executor.request(
                run_id=arguments.pop("run_id", "mcp"),
                principal=self.principal, action=name, args=arguments,
            )

        if name == "approve_action":
            require_role(self.principal, "admin")
            approval_id = arguments["approval_id"]
            self.executor.approvals.decide(
                approval_id, approve=True, decided_by=self.principal.name,
                reason=arguments.get("reason"),
            )
            return self.executor.execute_approved(
                approval_id=approval_id, principal=self.principal
            )

        raise ValueError(f"unknown tool {name!r}")


def _principal_from_env() -> Principal:
    return authenticate(os.getenv("TRIAGE_MCP_API_KEY", "demo-operator-key"))


def build_async_server():  # pragma: no cover - exercised via the stdio entrypoint
    from mcp.server import Server
    from mcp.types import TextContent, Tool

    core = MCPCore(_principal_from_env())
    server = Server("ops-triage")

    @server.list_tools()
    async def _list() -> list[Tool]:
        tools = []
        for t in core.list_tools():
            props = {k: {"type": "string", "description": v} for k, v in t["params"].items()}
            tools.append(Tool(
                name=t["name"],
                description=f"[{t['kind']}] {t['description']}",
                inputSchema={"type": "object", "properties": props},
            ))
        return tools

    @server.call_tool()
    async def _call(name: str, arguments: dict[str, Any]) -> list[TextContent]:
        try:
            result = core.call_tool(name, arguments)
        except Exception as exc:  # surface controlled errors to the client
            result = {"error": type(exc).__name__, "message": str(exc)}
        return [TextContent(type="text", text=json.dumps(result, indent=2))]

    return server


async def _main() -> None:  # pragma: no cover
    from mcp.server.stdio import stdio_server

    server = build_async_server()
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


if __name__ == "__main__":  # pragma: no cover
    import asyncio

    asyncio.run(_main())
