"""Append-only, hash-chained audit trail.

Every guarded action, approval decision, and tool side-effect is recorded as a
JSONL line whose ``hash`` covers the previous entry's hash (a tamper-evident
chain). ``verify()`` recomputes the chain and flags any break — the property an
enterprise security review actually asks for.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import threading
from dataclasses import asdict, dataclass, field
from datetime import UTC
from pathlib import Path
from typing import Any

GENESIS = "0" * 64


def _now() -> str:
    # Imported lazily so the module stays import-time pure.
    from datetime import datetime

    return datetime.now(UTC).isoformat()


@dataclass
class AuditEntry:
    seq: int
    ts: str
    actor: str
    action: str
    target: str
    outcome: str
    metadata: dict[str, Any] = field(default_factory=dict)
    prev_hash: str = GENESIS
    hash: str = ""

    def compute_hash(self) -> str:
        body = {k: v for k, v in asdict(self).items() if k != "hash"}
        blob = json.dumps(body, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(blob.encode()).hexdigest()


class AuditLog:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # Serializes record() calls from *this* instance across threads. Cross
        # -process serialization (e.g. the API server and an MCP server both
        # holding an AuditLog on the same path, per
        # docs/reference-architecture.md) is handled separately by an
        # fcntl.flock on the log file itself in record().
        self._lock = threading.Lock()
        # In-memory cache of (file size in bytes, entry count, last hash) as
        # last observed by this instance. record() re-validates it cheaply
        # (via file size) every time it acquires the file lock, so it stays
        # correct even when another process appended in the meantime — it
        # just avoids the O(n) full re-parse on the common case where this
        # instance is the only writer.
        self._tail_cache: tuple[int, int, str] | None = None

    def _entries(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        with self.path.open() as fh:
            return [json.loads(line) for line in fh if line.strip()]

    def _tail_locked(self) -> tuple[int, str]:
        """Return (seq for the next entry, prev_hash), assuming the caller
        already holds both the in-process lock and the cross-process file
        lock."""
        size = self.path.stat().st_size if self.path.exists() else 0
        if self._tail_cache is not None and self._tail_cache[0] == size:
            _, count, last_hash = self._tail_cache
            return count, last_hash
        existing = self._entries()
        count = len(existing)
        last_hash = existing[-1]["hash"] if existing else GENESIS
        self._tail_cache = (size, count, last_hash)
        return count, last_hash

    def record(
        self,
        *,
        actor: str,
        action: str,
        target: str,
        outcome: str,
        metadata: dict[str, Any] | None = None,
    ) -> AuditEntry:
        with self._lock:
            # "a+" both creates the file if missing and lets flock guard the
            # whole read-compute-append critical section against every other
            # process (and thread) touching this same path.
            with self.path.open("a+") as fh:
                fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
                try:
                    seq, prev_hash = self._tail_locked()
                    entry = AuditEntry(
                        seq=seq,
                        ts=_now(),
                        actor=actor,
                        action=action,
                        target=target,
                        outcome=outcome,
                        metadata=metadata or {},
                        prev_hash=prev_hash,
                    )
                    entry.hash = entry.compute_hash()
                    fh.write(json.dumps(asdict(entry)) + "\n")
                    fh.flush()
                    os.fsync(fh.fileno())
                    new_size = os.fstat(fh.fileno()).st_size
                    self._tail_cache = (new_size, seq + 1, entry.hash)
                    return entry
                finally:
                    fcntl.flock(fh.fileno(), fcntl.LOCK_UN)

    def entries(self) -> list[dict[str, Any]]:
        return self._entries()

    def verify(self) -> tuple[bool, str]:
        """Return (ok, message). Detects reordering, edits, and deletions."""
        prev = GENESIS
        for i, raw in enumerate(self._entries()):
            if raw.get("seq") != i:
                return False, f"sequence gap at index {i}"
            if raw.get("prev_hash") != prev:
                return False, f"broken chain at seq {i}"
            entry = AuditEntry(**{k: raw[k] for k in raw if k != "hash"})
            if entry.compute_hash() != raw.get("hash"):
                return False, f"tampered entry at seq {i}"
            prev = raw["hash"]
        return True, "audit chain intact"
