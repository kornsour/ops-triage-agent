"""Append-only, hash-chained audit trail.

Every guarded action, approval decision, and tool side-effect is recorded as a
JSONL line whose ``hash`` covers the previous entry's hash (a tamper-evident
chain). ``verify()`` recomputes the chain and flags any break — the property an
enterprise security review actually asks for.
"""

from __future__ import annotations

import hashlib
import json
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
        self._lock = threading.Lock()

    def _entries(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        with self.path.open() as fh:
            return [json.loads(line) for line in fh if line.strip()]

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
            existing = self._entries()
            seq = len(existing)
            prev_hash = existing[-1]["hash"] if existing else GENESIS
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
            with self.path.open("a") as fh:
                fh.write(json.dumps(asdict(entry)) + "\n")
            return entry

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
