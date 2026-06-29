"""Human-in-the-loop approval gates for guarded actions.

Each guarded action carries a risk policy. Low-risk actions can auto-approve;
medium/high-risk actions create a *pending* approval that an admin must decide
before the action executes. Pending approvals are persisted (SQLite) so the
web UI and API share state.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import UTC
from pathlib import Path
from typing import Any

# action -> (risk, auto_approve, approver_role)
ACTION_POLICY: dict[str, tuple[str, bool, str]] = {
    "reset_password": ("medium", False, "admin"),
    "grant_access": ("high", False, "admin"),
    "escalate": ("low", True, "admin"),
    "post_reply": ("low", True, "admin"),
    "close_ticket": ("low", True, "admin"),
}


class ApprovalRequired(Exception):
    """Raised when a guarded action needs a human decision before executing."""

    def __init__(self, approval_id: str, action: str):
        super().__init__(f"action {action!r} requires approval ({approval_id})")
        self.approval_id = approval_id
        self.action = action


@dataclass
class Decision:
    approval_id: str
    status: str  # pending | approved | denied | executed
    action: str
    args: dict[str, Any]
    risk: str
    requested_by: str
    decided_by: str | None = None
    reason: str | None = None


def _now() -> str:
    from datetime import datetime

    return datetime.now(UTC).isoformat()


class ApprovalStore:
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
                """
                CREATE TABLE IF NOT EXISTS approvals (
                    approval_id   TEXT PRIMARY KEY,
                    run_id        TEXT,
                    action        TEXT NOT NULL,
                    args          TEXT NOT NULL,
                    risk          TEXT NOT NULL,
                    status        TEXT NOT NULL,
                    requested_by  TEXT NOT NULL,
                    decided_by    TEXT,
                    reason        TEXT,
                    created_at    TEXT NOT NULL,
                    decided_at    TEXT
                )
                """
            )

    def create(
        self,
        *,
        approval_id: str,
        run_id: str,
        action: str,
        args: dict[str, Any],
        risk: str,
        requested_by: str,
    ) -> Decision:
        with self._conn() as c:
            c.execute(
                "INSERT OR IGNORE INTO approvals "
                "(approval_id, run_id, action, args, risk, status, requested_by, created_at) "
                "VALUES (?,?,?,?,?,?,?,?)",
                (approval_id, run_id, action, json.dumps(args), risk, "pending",
                 requested_by, _now()),
            )
        return self.get(approval_id)  # type: ignore[return-value]

    def get(self, approval_id: str) -> Decision | None:
        with self._conn() as c:
            row = c.execute(
                "SELECT * FROM approvals WHERE approval_id=?", (approval_id,)
            ).fetchone()
        return _to_decision(row) if row else None

    def list(self, status: str | None = None) -> list[Decision]:
        q = "SELECT * FROM approvals"
        params: tuple = ()
        if status:
            q += " WHERE status=?"
            params = (status,)
        q += " ORDER BY created_at DESC"
        with self._conn() as c:
            rows = c.execute(q, params).fetchall()
        return [_to_decision(r) for r in rows]

    def decide(self, approval_id: str, *, approve: bool, decided_by: str,
               reason: str | None = None) -> Decision:
        status = "approved" if approve else "denied"
        with self._conn() as c:
            cur = c.execute(
                "UPDATE approvals SET status=?, decided_by=?, reason=?, decided_at=? "
                "WHERE approval_id=? AND status='pending'",
                (status, decided_by, reason, _now(), approval_id),
            )
            if cur.rowcount == 0:
                existing = self.get(approval_id)
                if existing is None:
                    raise KeyError(approval_id)
                raise ValueError(f"approval {approval_id} already {existing.status}")
        return self.get(approval_id)  # type: ignore[return-value]

    def mark_executed(self, approval_id: str) -> None:
        with self._conn() as c:
            c.execute(
                "UPDATE approvals SET status='executed' WHERE approval_id=?",
                (approval_id,),
            )


def policy_for(action: str) -> tuple[str, bool, str]:
    return ACTION_POLICY.get(action, ("high", False, "admin"))


def _to_decision(row: sqlite3.Row) -> Decision:
    return Decision(
        approval_id=row["approval_id"],
        status=row["status"],
        action=row["action"],
        args=json.loads(row["args"]),
        risk=row["risk"],
        requested_by=row["requested_by"],
        decided_by=row["decided_by"],
        reason=row["reason"],
    )
