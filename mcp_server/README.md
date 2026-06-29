# MCP server — `ops-triage`

A [Model Context Protocol](https://modelcontextprotocol.io) server that exposes
the triage tools to any MCP-compatible client (Claude Desktop, IDEs, other
agents) — but unlike a typical MCP demo, **every call goes through the
enterprise-controls layer**.

## Tools

| Tool | Kind | Min role | Behavior |
| --- | --- | --- | --- |
| `retrieve_runbook` | read | viewer | Semantic search over the knowledge base |
| `lookup_ticket_history` | read | viewer | Prior tickets for a requester |
| `lookup_user` | read | viewer | Directory record |
| `reset_password` | action | operator | **medium-risk → returns `pending_approval`** |
| `grant_access` | action | operator | **high-risk → returns `pending_approval`** |
| `escalate` | action | operator | low-risk → auto-executes (notifies a human) |
| `post_reply` / `close_ticket` | action | operator | low-risk → auto-executes |
| `approve_action` | action | **admin** | approve + execute a pending action |

Every action — request, approval, and execution — is written to the hash-chained
audit trail.

## Run it

```bash
# operator session (default): can request actions, sees them held for approval
TRIAGE_MCP_API_KEY=demo-operator-key uv run python -m mcp_server.server

# admin session: can also approve_action
TRIAGE_MCP_API_KEY=demo-admin-key uv run python -m mcp_server.server
```

Requires the seeded DB + index first (`make seed`). Install the optional SDK with
`uv pip install -e ".[mcp]"`.

## Claude Desktop config

```json
{
  "mcpServers": {
    "ops-triage": {
      "command": "uv",
      "args": ["run", "python", "-m", "mcp_server.server"],
      "cwd": "/path/to/ops-triage-agent",
      "env": { "TRIAGE_MCP_API_KEY": "demo-operator-key" }
    }
  }
}
```

## Design

The protocol handlers are thin async wrappers over `MCPCore`, a synchronous,
fully unit-tested class (see `tests/test_mcp.py`). That keeps the enterprise-
control logic — auth, approval gating, idempotency, audit — testable without
spinning up a transport.
