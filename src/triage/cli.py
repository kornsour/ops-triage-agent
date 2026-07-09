"""Command-line entry point.

    triage demo            Run triage on a representative seeded ticket, print trace.
    triage run <ticket>    Run triage on a specific ticket id.
    triage list            List the seeded ticket queue.

Operates entirely offline with the mock provider by default.
"""

from __future__ import annotations

import argparse
import json
import sys

from triage.agent.runner import TriageRunner
from triage.config import get_settings
from triage.data.db import TicketDB
from triage.data.seed import seed
from triage.enterprise.auth import authenticate
from triage.rag.ingest import ingest
from triage.rag.store import VectorStore


def _ensure_ready() -> None:
    s = get_settings()
    if not s.db_path.exists():
        seed()
    if not VectorStore.exists(s.index_dir):
        ingest(verbose=False)


def _operator():
    return authenticate("demo-operator-key")


def cmd_list(_args) -> int:
    _ensure_ready()
    db = TicketDB(get_settings().db_path)
    for t in db.list_tickets():
        print(f"{t.id}  [{t.status:8}]  {t.requester:18}  {t.subject}")
    return 0


def _print_run(result) -> None:
    print(f"\n=== Triage {result.run_id} -> ticket {result.ticket_id} ===")
    print(f"status      : {result.status}")
    print(f"category    : {result.category}   severity: {result.severity}")
    print(f"summary     : {result.summary}")
    print(f"grounded    : {result.grounded}   citations: {result.citations}")
    print(f"action      : {result.action.get('name')} -> {result.action.get('status')}", end="")
    if result.action.get("approval_id"):
        print(f"  (approval {result.action['approval_id'][:12]})", end="")
    print()
    print(f"metrics     : {result.metrics['total_ms']} ms, "
          f"{result.metrics['total_tokens']} tok, ${result.metrics['usd']}")
    print("\n-- trace --")
    for s in result.trace:
        print(f"  {s.step:9} {s.ms:7.2f}ms  {json.dumps(s.detail)}")
    print("\n-- draft reply --")
    print(f"  {result.draft_reply}")


def cmd_run(args) -> int:
    _ensure_ready()
    db = TicketDB(get_settings().db_path)
    ticket = db.get_ticket(args.ticket_id)
    if ticket is None:
        print(f"No such ticket: {args.ticket_id}", file=sys.stderr)
        return 1
    runner = TriageRunner(db=db)
    _print_run(runner.run(ticket, _operator()))
    return 0


def cmd_demo(_args) -> int:
    _ensure_ready()
    db = TicketDB(get_settings().db_path)
    runner = TriageRunner(db=db)
    # One of each interesting shape: lockout (needs approval), outage
    # (auto-escalate), access request (approval), and an injection attempt (gated).
    for tid in ("TCK-1001", "TCK-1004", "TCK-1002", "TCK-1009"):
        ticket = db.get_ticket(tid)
        if ticket:
            _print_run(runner.run(ticket, _operator()))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="triage", description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list").set_defaults(fn=cmd_list)
    sub.add_parser("demo").set_defaults(fn=cmd_demo)
    p_run = sub.add_parser("run")
    p_run.add_argument("ticket_id")
    p_run.set_defaults(fn=cmd_run)
    args = parser.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    raise SystemExit(main())
