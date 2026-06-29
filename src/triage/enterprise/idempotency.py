"""Idempotency keys: the same guarded action requested twice executes once.

Keys are derived from (action, sorted-args) or supplied explicitly. The store
caches the first result and replays it for duplicates, so retried API calls or a
re-run agent never double-charge / double-provision.
"""

from __future__ import annotations

import hashlib
import json
import threading
from typing import Any


def make_key(action: str, args: dict[str, Any]) -> str:
    blob = json.dumps({"action": action, "args": args}, sort_keys=True)
    return hashlib.sha256(blob.encode()).hexdigest()[:32]


class IdempotencyStore:
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
