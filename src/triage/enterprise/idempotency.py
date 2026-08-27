"""Idempotency keys: the same guarded action requested twice executes once.

Keys are derived from (action, sorted-args) or supplied explicitly.
`IdempotencyStore` is the production store: it persists the first result for a
key to SQLite and replays it for duplicates, so a retried API call, a re-run
agent, a process restart, or a second replica behind a load balancer never
double-applies an effect. `InMemoryIdempotencyStore` keeps the original
process-local behavior and exists purely as a lightweight test double.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
from datetime import UTC
from pathlib import Path
from typing import Any


def make_key(action: str, args: dict[str, Any]) -> str:
    blob = json.dumps({"action": action, "args": args}, sort_keys=True)
    return hashlib.sha256(blob.encode()).hexdigest()[:32]


def _now() -> str:
    from datetime import datetime

    return datetime.now(UTC).isoformat()


class IdempotencyStore:
    """SQLite-backed idempotency store, keyed on the same `db_path` as the
    rest of the persisted state (tickets, approvals). Every `ActionExecutor`
    constructed against that path — a fresh process after a restart, or a
    sibling replica behind a load balancer — sees the same rows.
    """

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
                """CREATE TABLE IF NOT EXISTS idempotency (
                    key TEXT PRIMARY KEY, result TEXT, created_at TEXT
                )"""
            )

    def seen(self, key: str) -> bool:
        with self._conn() as c:
            row = c.execute("SELECT 1 FROM idempotency WHERE key=?", (key,)).fetchone()
        return row is not None

    def get(self, key: str) -> Any:
        with self._conn() as c:
            row = c.execute(
                "SELECT result FROM idempotency WHERE key=?", (key,)
            ).fetchone()
        return json.loads(row["result"]) if row else None

    def remember(self, key: str, result: Any) -> None:
        # ON CONFLICT DO NOTHING: first writer wins, matching the in-memory
        # store's `setdefault` semantics — a losing concurrent writer's result
        # is discarded in favor of whatever is already stored.
        with self._conn() as c:
            c.execute(
                "INSERT INTO idempotency (key, result, created_at) VALUES (?,?,?) "
                "ON CONFLICT(key) DO NOTHING",
                (key, json.dumps(result), _now()),
            )

    def run_once(self, key: str, fn) -> tuple[Any, bool]:
        """Execute fn() unless key was seen. Return (result, was_replayed)."""
        existing = self.get(key)
        if existing is not None:
            return existing, True
        result = fn()
        with self._conn() as c:
            cur = c.execute(
                "INSERT INTO idempotency (key, result, created_at) VALUES (?,?,?) "
                "ON CONFLICT(key) DO NOTHING",
                (key, json.dumps(result), _now()),
            )
            if cur.rowcount == 0:
                # Lost the race to another process/replica; replay its result
                # rather than the one just computed here.
                row = c.execute(
                    "SELECT result FROM idempotency WHERE key=?", (key,)
                ).fetchone()
                return json.loads(row["result"]), True
        return result, False


class InMemoryIdempotencyStore:
    """Process-local idempotency store. Test double only — production code
    should use `IdempotencyStore`, which survives restarts and is shared
    across replicas via SQLite.
    """

    def __init__(self) -> None:
        self._seen: dict[str, Any] = {}
        self._lock = threading.Lock()

    def seen(self, key: str) -> bool:
        with self._lock:
            return key in self._seen

    def get(self, key: str) -> Any:
        with self._lock:
            return self._seen.get(key)

    def remember(self, key: str, result: Any) -> None:
        with self._lock:
            self._seen.setdefault(key, result)

    def run_once(self, key: str, fn) -> tuple[Any, bool]:
        """Execute fn() unless key was seen. Return (result, was_replayed)."""
        with self._lock:
            if key in self._seen:
                return self._seen[key], True
        result = fn()
        with self._lock:
            self._seen.setdefault(key, result)
        return result, False
