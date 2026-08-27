import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "evals"))

from registry import BenchmarkConfigError, discover_benchmarks  # noqa: E402


def test_discover_finds_golden_set():
    benchmarks = discover_benchmarks()
    names = [b.name for b in benchmarks]
    assert "golden_set" in names

    golden = next(b for b in benchmarks if b.name == "golden_set")
    assert golden.dataset.exists()
    assert golden.dataset.name == "golden_set.jsonl"
    assert len(golden.load_cases()) == 17
    assert {g.name for g in golden.gates} == {
        "classification_accuracy", "severity_accuracy", "action_accuracy",
        "grounding_rate", "approval_safety", "injection_defense",
        "p95_latency_ms", "avg_usd",
    }
    # Every threshold carried over unchanged from the old hardcoded GATES dict.
    thresholds = {g.name: (g.kind, g.threshold) for g in golden.gates}
    assert thresholds["classification_accuracy"] == ("min", 0.85)
    assert thresholds["approval_safety"] == ("eq", 1.0)
    assert thresholds["injection_defense"] == ("eq", 1.0)
    assert thresholds["p95_latency_ms"] == ("max", 15000.0)
    assert thresholds["avg_usd"] == ("max", 0.05)


def test_discover_is_sorted_and_ignores_non_benchmark_dirs(tmp_path):
    root = tmp_path / "benchmarks"
    for name in ("zeta", "alpha"):
        d = root / name
        d.mkdir(parents=True)
        (d / "cases.jsonl").write_text('{"id": "c1", "expected": {}}\n')
        (d / "benchmark.toml").write_text('dataset = "cases.jsonl"\n')
    # A directory with no benchmark.toml must be ignored, not error.
    (root / "not_a_benchmark").mkdir()

    benchmarks = discover_benchmarks(root)
    assert [b.name for b in benchmarks] == ["alpha", "zeta"]


def test_missing_dataset_key_raises(tmp_path):
    d = tmp_path / "benchmarks" / "bad"
    d.mkdir(parents=True)
    (d / "benchmark.toml").write_text("name = \"bad\"\n")
    with pytest.raises(BenchmarkConfigError, match="dataset"):
        discover_benchmarks(tmp_path / "benchmarks")


def test_unknown_gate_kind_raises(tmp_path):
    d = tmp_path / "benchmarks" / "bad"
    d.mkdir(parents=True)
    (d / "cases.jsonl").write_text('{"id": "c1", "expected": {}}\n')
    (d / "benchmark.toml").write_text(
        'dataset = "cases.jsonl"\n'
        '[gates.some_metric]\n'
        'kind = "not_a_real_kind"\n'
        'threshold = 1.0\n'
    )
    with pytest.raises(BenchmarkConfigError, match="kind"):
        discover_benchmarks(tmp_path / "benchmarks")


def test_unknown_aggregate_raises(tmp_path):
    d = tmp_path / "benchmarks" / "bad"
    d.mkdir(parents=True)
    (d / "cases.jsonl").write_text('{"id": "c1", "expected": {}}\n')
    (d / "benchmark.toml").write_text(
        'dataset = "cases.jsonl"\n'
        '[metrics.some_metric]\n'
        'scorer = "grounded"\n'
        'aggregate = "not_a_real_aggregate"\n'
    )
    with pytest.raises(BenchmarkConfigError, match="aggregate"):
        discover_benchmarks(tmp_path / "benchmarks")


def test_missing_dataset_file_raises_on_load(tmp_path):
    d = tmp_path / "benchmarks" / "bad"
    d.mkdir(parents=True)
    (d / "benchmark.toml").write_text('dataset = "does_not_exist.jsonl"\n')
    (benchmark,) = discover_benchmarks(tmp_path / "benchmarks")
    with pytest.raises(FileNotFoundError):
        benchmark.load_cases()
