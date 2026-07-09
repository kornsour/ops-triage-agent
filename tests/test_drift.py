import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "evals"))

from drift import detect  # noqa: E402


def _metrics(**over):
    base = {
        "classification_accuracy": 0.90, "severity_accuracy": 0.90,
        "action_accuracy": 0.90, "grounding_rate": 1.0, "approval_safety": 1.0,
        "injection_defense": 1.0, "pass_rate": 0.88, "p95_latency_ms": 1.0,
        "avg_usd": 0.0,
    }
    base.update(over)
    return base


def test_no_drift_on_identical_reports():
    assert detect(_metrics(), _metrics()) == []


def test_quality_regression_is_detected():
    prev, curr = _metrics(), _metrics(classification_accuracy=0.80)
    assert "classification_accuracy" in detect(prev, curr)


def test_safety_regression_has_zero_tolerance():
    # approval_safety and injection_defense may never drop at all.
    assert "approval_safety" in detect(_metrics(), _metrics(approval_safety=0.99))
    assert "injection_defense" in detect(_metrics(), _metrics(injection_defense=0.99))


def test_small_movement_within_tolerance_is_not_drift():
    # A 0.02 dip in accuracy is within the 0.03 tolerance band.
    assert detect(_metrics(), _metrics(action_accuracy=0.88)) == []


def test_latency_regression_is_fractional():
    # p95 more than 50% slower is a regression.
    assert "p95_latency_ms" in detect(_metrics(p95_latency_ms=1.0),
                                      _metrics(p95_latency_ms=2.0))
