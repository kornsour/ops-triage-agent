"""Scoring: apply a benchmark's declared scorers to each case, then aggregate
per-case values into the benchmark's reported metrics.

This module knows nothing about triage-specific semantics (category, severity,
safety, ...) — that lives in `scorers.py`, keyed by name. A benchmark's
`benchmark.toml` picks which registered scorers feed which metrics and how
each metric aggregates; this module just executes that wiring.
"""

from __future__ import annotations

from typing import Any

from registry import Benchmark
from scorers import SCORERS

from triage.observability.metrics import percentile


def score_case(case: dict[str, Any], result: Any) -> dict[str, float | bool | None]:
    """Run every registered scorer once per case. Cheap, and lets a benchmark's
    metric list change without re-running the agent."""
    return {name: fn(case, result) for name, fn in SCORERS.items()}


def aggregate(benchmark: Benchmark, per_case: list[dict[str, float | bool | None]]) -> dict[str, float]:
    """Reduce per-case scorer output into the metrics `benchmark` declares."""
    n = len(per_case)
    metrics: dict[str, float] = {"n": n}
    if n == 0:
        return metrics

    for spec in benchmark.metrics:
        if spec.scorer not in SCORERS:
            raise KeyError(
                f"benchmark {benchmark.name!r}: metric {spec.name!r} references "
                f"unknown scorer {spec.scorer!r} (available: {sorted(SCORERS)})")
        raw = [row[spec.scorer] for row in per_case]
        applicable = [float(v) for v in raw if v is not None]

        if spec.aggregate == "rate":
            # A metric with no applicable cases (e.g. no risky/injection cases
            # in this run) aggregates to a clean pass, not an empty-set 0.0.
            metrics[spec.name] = round(sum(applicable) / len(applicable), 4) if applicable else 1.0
        elif spec.aggregate == "mean":
            metrics[spec.name] = round(sum(applicable) / len(applicable), 6) if applicable else 0.0
        else:  # "p50" | "p95"
            pct = 50 if spec.aggregate == "p50" else 95
            metrics[spec.name] = round(percentile(applicable, pct), 2) if applicable else 0.0

    return metrics
