"""SQLite ticket store and run records.

Small on purpose: the point is that the agent reads/writes a *real* database
(history lookups, status transitions) rather than only chatting.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import UTC
from pathlib import Path
from typing import Any


def _now() -> str:
    from datetime import datetime

    return datetime.now(UTC).isoformat()


@dataclass
class Ticket:
    id: str
    subject: str
    body: str
    requester: str
    status: str = "open"
    category: str | None = None
    severity: str | None = None
    created_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return self.__dict__.copy()


class TicketDB:
    def __init__(self, db_path: Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init()

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init(self) -> None:
        with self._conn() as c:
            c.execute(
                """CREATE TABLE IF NOT EXISTS tickets (
                    id TEXT PRIMARY KEY, subject TEXT, body TEXT, requester TEXT,
                    status TEXT, category TEXT, severity TEXT, created_at TEXT
                )"""
            )
            c.execute(
                """CREATE TABLE IF NOT EXISTS runs (
                    run_id TEXT PRIMARY KEY, ticket_id TEXT, status TEXT,
                    result TEXT, created_at TEXT
                )"""
            )
            c.execute(
                """CREATE TABLE IF NOT EXISTS users (
                    email TEXT PRIMARY KEY, name TEXT, department TEXT, manager TEXT
                )"""
            )

    # --- tickets ---
    def upsert_ticket(self, t: Ticket) -> None:
        with self._conn() as c:
            c.execute(
                "INSERT OR REPLACE INTO tickets VALUES (?,?,?,?,?,?,?,?)",
                (t.id, t.subject, t.body, t.requester, t.status, t.category,
                 t.severity, t.created_at or _now()),
            )

    def get_ticket(self, ticket_id: str) -> Ticket | None:
        with self._conn() as c:
            row = c.execute("SELECT * FROM tickets WHERE id=?", (ticket_id,)).fetchone()
        return Ticket(**dict(row)) if row else None

    def list_tickets(self, status: str | None = None) -> list[Ticket]:
        q, p = "SELECT * FROM tickets", ()
        if status:
            q, p = "SELECT * FROM tickets WHERE status=?", (status,)
        with self._conn() as c:
            rows = c.execute(q + " ORDER BY created_at", p).fetchall()
        return [Ticket(**dict(r)) for r in rows]

    def history_for(self, requester: str, exclude_id: str | None = None) -> list[Ticket]:
        with self._conn() as c:
            rows = c.execute(
                "SELECT * FROM tickets WHERE requester=? ORDER BY created_at DESC",
                (requester,),
            ).fetchall()
        out = [Ticket(**dict(r)) for r in rows]
        return [t for t in out if t.id != exclude_id]

    def set_status(self, ticket_id: str, status: str) -> None:
        with self._conn() as c:
            c.execute("UPDATE tickets SET status=? WHERE id=?", (status, ticket_id))

    # --- users ---
    def upsert_user(self, email: str, name: str, department: str, manager: str) -> None:
        with self._conn() as c:
            c.execute("INSERT OR REPLACE INTO users VALUES (?,?,?,?)",
                      (email, name, department, manager))

    def get_user(self, email: str) -> dict[str, Any] | None:
        with self._conn() as c:
            row = c.execute("SELECT * FROM users WHERE email=?", (email,)).fetchone()
        return dict(row) if row else None

    # --- runs ---
    def save_run(self, run_id: str, ticket_id: str, status: str, result: dict[str, Any]) -> None:
        with self._conn() as c:
            c.execute(
                "INSERT OR REPLACE INTO runs VALUES (?,?,?,?,?)",
                (run_id, ticket_id, status, json.dumps(result), _now()),
            )

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        with self._conn() as c:
            row = c.execute("SELECT * FROM runs WHERE run_id=?", (run_id,)).fetchone()
        if not row:
            return None
        d = dict(row)
        d["result"] = json.loads(d["result"])
        return d

    def list_runs(self) -> list[dict[str, Any]]:
        with self._conn() as c:
            rows = c.execute("SELECT * FROM runs ORDER BY created_at DESC").fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["result"] = json.loads(d["result"])
            out.append(d)
        return out
