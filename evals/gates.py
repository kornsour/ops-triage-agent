"""Quality gates. CI fails if any registered benchmark's gate is not met.

`min` gates require value >= threshold; `max` gates require value <= threshold;
`eq` gates require exact equality (used for hard safety invariants). Gates are
declared per-benchmark in `benchmark.toml` — see `registry.py` and
docs/evals.md — not hardcoded here.
"""

from __future__ import annotations

from dataclasses import dataclass

from registry import Benchmark


@dataclass
class GateResult:
    benchmark: str
    name: str
    value: float
    kind: str
    threshold: float
    ok: bool


def evaluate_gates(benchmark: Benchmark, metrics: dict[str, float]) -> list[GateResult]:
    results: list[GateResult] = []
    for gate in benchmark.gates:
        value = float(metrics.get(gate.name, 0.0))
        if gate.kind == "min":
            ok = value >= gate.threshold
        elif gate.kind == "max":
            ok = value <= gate.threshold
        else:  # eq
            ok = abs(value - gate.threshold) < 1e-9
        results.append(GateResult(benchmark.name, gate.name, value, gate.kind, gate.threshold, ok))
    return results


def all_passed(results: list[GateResult]) -> bool:
    return all(r.ok for r in results)
