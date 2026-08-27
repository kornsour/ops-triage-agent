"""Append-only, hash-chained audit trail.

Every guarded action, approval decision, and tool side-effect is recorded as a
JSONL line whose ``hash`` covers the previous entry's hash (a tamper-evident
chain). ``verify()`` recomputes the chain and flags any break — the property an
enterprise security review actually asks for.

The chain alone anchors nothing: an internally consistent prefix of the log
(e.g. the first N entries with the tail dropped) still re-verifies cleanly,
because nothing records how long the chain is *supposed* to be. To close that
gap, ``record()`` also writes a small sidecar "head" file — ``{expected_length,
last_hash}`` — next to the log, updated under the same lock as the append.
``verify()`` compares the log it actually reads against that anchor, so
truncating entries from the end (not just the middle) is detected.
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
        self.head_path = self.path.with_name(self.path.name + ".head")
        # Serializes record() calls from *this* instance across threads. Cross
        # -process serialization (e.g. the API server and an MCP server both
        # holding an AuditLog on the same path, per
        # docs/reference-architecture.md) is handled separately by an
        # fcntl.flock on the log file itself in record() — the head file is
        # written under that same flock, so the anchor and the log tail can
        # never desync under concurrent writers.
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

    def _read_head(self) -> dict[str, Any] | None:
        """Return the persisted {expected_length, last_hash} anchor, if any.

        Missing or unreadable is treated as "no anchor yet" (e.g. a log written
        before this feature existed) rather than an error — ``verify()`` falls
        back to structural-only checks in that case.
        """
        if not self.head_path.exists():
            return None
        try:
            data = json.loads(self.head_path.read_text())
        except (json.JSONDecodeError, OSError):
            return None
        if not isinstance(data, dict):
            return None
        return data

    def _write_head(self, expected_length: int, last_hash: str) -> None:
        tmp = self.head_path.with_name(self.head_path.name + ".tmp")
        tmp.write_text(
            json.dumps({"expected_length": expected_length, "last_hash": last_hash})
        )
        tmp.replace(self.head_path)

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
            # whole read-compute-append-anchor critical section against every
            # other process (and thread) touching this same path. The head
            # file is written inside this same lock, not after releasing it —
            # otherwise a second process could interleave its own append
            # between our log write and our head write, and the anchor would
            # describe a length/hash the log never actually held.
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
                    self._write_head(seq + 1, entry.hash)
                    return entry
                finally:
                    fcntl.flock(fh.fileno(), fcntl.LOCK_UN)

    def entries(self) -> list[dict[str, Any]]:
        return self._entries()

    def verify(self) -> tuple[bool, str]:
        """Return (ok, message).

        Detects reordering, edits, and deletions anywhere in the log (via the
        seq/prev_hash/hash chain), plus truncation from the *end* of the log
        (via the persisted head anchor written by ``record()``): a chain that
        re-verifies internally but is shorter than the anchor's expected
        length has had entries removed from its tail.
        """
        entries = self._entries()
        prev = GENESIS
        for i, raw in enumerate(entries):
            if raw.get("seq") != i:
                return False, f"sequence gap at index {i}"
            if raw.get("prev_hash") != prev:
                return False, f"broken chain at seq {i}"
            entry = AuditEntry(**{k: raw[k] for k in raw if k != "hash"})
            if entry.compute_hash() != raw.get("hash"):
                return False, f"tampered entry at seq {i}"
            prev = raw["hash"]

        head = self._read_head()
        if head is not None:
            expected = head.get("expected_length")
            if isinstance(expected, int) and len(entries) < expected:
                return False, f"log truncated: {len(entries)} entries, expected {expected}"
            last_hash = head.get("last_hash")
            if (
                entries
                and last_hash is not None
                and isinstance(expected, int)
                and len(entries) == expected
                and entries[-1].get("hash") != last_hash
            ):
                return False, f"log truncated: {len(entries)} entries, expected {expected}"

        return True, "audit chain intact"
