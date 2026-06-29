"""Latency / cost / token metrics for a triage run.

`RunMetrics` accumulates per-step timings and token usage; `percentile` powers
the p50/p95 latency rollups in the eval report.
"""

from __future__ import annotations

import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any


def percentile(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    if len(s) == 1:
        return s[0]
    rank = (p / 100) * (len(s) - 1)
    lo = int(rank)
    hi = min(lo + 1, len(s) - 1)
    frac = rank - lo
    return s[lo] + (s[hi] - s[lo]) * frac


@dataclass
class RunMetrics:
    steps: dict[str, float] = field(default_factory=dict)  # step -> ms
    input_tokens: int = 0
    output_tokens: int = 0
    usd: float = 0.0
    llm_calls: int = 0

    @property
    def total_ms(self) -> float:
        return round(sum(self.steps.values()), 2)

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens

    def add_usage(self, input_tokens: int, output_tokens: int, usd: float) -> None:
        self.input_tokens += input_tokens
        self.output_tokens += output_tokens
        self.usd = round(self.usd + usd, 8)
        self.llm_calls += 1

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_ms": self.total_ms,
            "steps_ms": {k: round(v, 2) for k, v in self.steps.items()},
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "total_tokens": self.total_tokens,
            "usd": round(self.usd, 6),
            "llm_calls": self.llm_calls,
        }


class Timer:
    """Records elapsed wall-clock per named step into a RunMetrics."""

    def __init__(self, metrics: RunMetrics) -> None:
        self.metrics = metrics

    @contextmanager
    def step(self, name: str):
        start = time.perf_counter()
        try:
            yield
        finally:
            self.metrics.steps[name] = (time.perf_counter() - start) * 1000.0
