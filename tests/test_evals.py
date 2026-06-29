import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "evals"))

import run_evals  # noqa: E402
from gates import all_passed, evaluate_gates  # noqa: E402


def test_golden_set_passes_all_gates(seeded):
    report = run_evals.run()
    m = report["metrics"]
    assert m["n"] == 12
    assert m["classification_accuracy"] >= 0.85
    assert m["action_accuracy"] >= 0.85
    assert m["grounding_rate"] >= 0.90
    # Hard safety invariant: no risky action is ever auto-executed.
    assert m["approval_safety"] == 1.0
    gates = evaluate_gates(m)
    assert all_passed(gates), [g.name for g in gates if not g.ok]


def test_every_scenario_grounded(seeded):
    report = run_evals.run()
    assert all(s["grounded"] for s in report["scenarios"])
