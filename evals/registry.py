"""Benchmark registry.

A benchmark is a directory under `evals/benchmarks/<name>/` containing a
`benchmark.toml` that declares:

  - `name`     — benchmark id (defaults to the directory name)
  - `dataset`  — path to a JSONL file of cases, relative to the benchmark dir
  - `[metrics.<metric_name>]` — for each reported metric, which registered
    scorer produces its per-case value and how to aggregate those values
    (`rate`, `mean`, `p50`, or `p95`)
  - `[gates.<metric_name>]` — for each metric that should block a release,
    the gate `kind` (`min` / `max` / `eq`) and `threshold`

Adding a benchmark is a new directory + config; nothing in `evals/*.py` needs
to change. See docs/evals.md for the full format and a worked example.
"""

from __future__ import annotations

import json
import tomllib
from dataclasses import dataclass
from pathlib import Path

HERE = Path(__file__).resolve().parent
BENCHMARKS_DIR = HERE / "benchmarks"

_VALID_AGGREGATES = {"rate", "mean", "p50", "p95"}
_VALID_GATE_KINDS = {"min", "max", "eq"}


@dataclass(frozen=True)
class MetricSpec:
    name: str
    scorer: str
    aggregate: str  # "rate" | "mean" | "p50" | "p95"


@dataclass(frozen=True)
class GateSpec:
    name: str
    kind: str  # "min" | "max" | "eq"
    threshold: float


@dataclass(frozen=True)
class Benchmark:
    name: str
    dataset: Path
    metrics: tuple[MetricSpec, ...]
    gates: tuple[GateSpec, ...]
    config_path: Path

    def load_cases(self) -> list[dict]:
        if not self.dataset.exists():
            raise FileNotFoundError(
                f"benchmark {self.name!r}: dataset not found at {self.dataset}")
        return [json.loads(line) for line in self.dataset.read_text().splitlines()
                if line.strip()]


class BenchmarkConfigError(ValueError):
    """A benchmark.toml is missing a required field or references an unknown scorer."""


def _load_benchmark(config_path: Path) -> Benchmark:
    data = tomllib.loads(config_path.read_text())
    name = data.get("name", config_path.parent.name)

    if "dataset" not in data:
        raise BenchmarkConfigError(f"{config_path}: missing required key 'dataset'")
    dataset = (config_path.parent / data["dataset"]).resolve()

    metrics = []
    for metric_name, conf in data.get("metrics", {}).items():
        if "scorer" not in conf:
            raise BenchmarkConfigError(
                f"{config_path}: metrics.{metric_name} is missing 'scorer'")
        aggregate = conf.get("aggregate", "mean")
        if aggregate not in _VALID_AGGREGATES:
            raise BenchmarkConfigError(
                f"{config_path}: metrics.{metric_name}.aggregate={aggregate!r} "
                f"must be one of {sorted(_VALID_AGGREGATES)}")
        metrics.append(MetricSpec(name=metric_name, scorer=conf["scorer"], aggregate=aggregate))

    gates = []
    for gate_name, conf in data.get("gates", {}).items():
        kind = conf.get("kind")
        if kind not in _VALID_GATE_KINDS:
            raise BenchmarkConfigError(
                f"{config_path}: gates.{gate_name}.kind={kind!r} "
                f"must be one of {sorted(_VALID_GATE_KINDS)}")
        if "threshold" not in conf:
            raise BenchmarkConfigError(
                f"{config_path}: gates.{gate_name} is missing 'threshold'")
        gates.append(GateSpec(name=gate_name, kind=kind, threshold=float(conf["threshold"])))

    return Benchmark(name=name, dataset=dataset, metrics=tuple(metrics),
                      gates=tuple(gates), config_path=config_path)


def discover_benchmarks(root: Path = BENCHMARKS_DIR) -> list[Benchmark]:
    """Find and load every `<root>/*/benchmark.toml`, sorted by directory name."""
    return [_load_benchmark(p) for p in sorted(root.glob("*/benchmark.toml"))]
