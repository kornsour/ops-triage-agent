"""Token-bucket rate limiting per principal.

Deterministic: time is injected (``now``) so tests don't sleep. The agent and
MCP server use this to protect downstream tools from runaway loops.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field


class RateLimitExceeded(Exception):
    pass


@dataclass
class TokenBucket:
    capacity: int
    refill_per_sec: float
    _tokens: float = field(default=0.0, init=False)
    _last: float | None = field(default=None, init=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, init=False)

    def __post_init__(self) -> None:
        self._tokens = float(self.capacity)

    def allow(self, now: float, cost: float = 1.0) -> bool:
        with self._lock:
            if self._last is None:
                self._last = now
            elapsed = max(0.0, now - self._last)
            self._tokens = min(self.capacity, self._tokens + elapsed * self.refill_per_sec)
            self._last = now
            if self._tokens >= cost:
                self._tokens -= cost
                return True
            return False

    def acquire(self, now: float, cost: float = 1.0) -> None:
        if not self.allow(now, cost):
            raise RateLimitExceeded(
                f"rate limit exceeded (capacity={self.capacity}/min-equiv)"
            )
