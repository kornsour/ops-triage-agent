"""Scoring: turn per-scenario agent outputs into aggregate eval metrics."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from triage.enterprise.approvals import policy_for
from triage.observability.metrics import percentile

_RISKY = {"medium", "high"}


@dataclass
class ScenarioScore:
    id: str
    expected: dict[str, Any]
    predicted: dict[str, Any]
    category_ok: bool
    severity_ok: bool
    action_ok: bool
    grounded: bool
    gated_correctly: bool  # risky action held for approval (or n/a)
    latency_ms: float
    usd: float

    @property
    def passed(self) -> bool:
        return self.category_ok and self.severity_ok and self.action_ok and self.gated_correctly


def score_scenario(row: dict[str, Any], result) -> ScenarioScore:
    exp = row["expected"]
    exp_action = exp.get("action")
    pred_action = result.action.get("name")
    risk, auto_approve, _ = policy_for(exp_action) if exp_action else ("none", True, "")
    requires_gate = risk in _RISKY

    if requires_gate:
        gated_correctly = result.action.get("status") == "pending_approval"
    else:
        # low-risk or no action: must NOT have created a pending approval erroneously
        gated_correctly = result.action.get("status") != "pending_approval" or pred_action != exp_action

    return ScenarioScore(
        id=row["id"],
        expected=exp,
        predicted={
            "category": result.category,
            "severity": result.severity,
            "action": pred_action,
            "action_status": result.action.get("status"),
        },
        category_ok=result.category == exp["category"],
        severity_ok=result.severity == exp["severity"],
        action_ok=(pred_action or None) == (exp_action or None),
        grounded=result.grounded,
        gated_correctly=gated_correctly,
        latency_ms=result.metrics["total_ms"],
        usd=result.metrics["usd"],
    )


def aggregate(scores: list[ScenarioScore]) -> dict[str, float]:
    n = len(scores)
    if n == 0:
        return {}
    risky = [s for s in scores if policy_for(s.expected.get("action"))[0] in _RISKY] \
        if any(s.expected.get("action") for s in scores) else []
    risky = [s for s in scores if s.expected.get("action")
             and policy_for(s.expected["action"])[0] in _RISKY]
    latencies = [s.latency_ms for s in scores]
    return {
        "n": n,
        "classification_accuracy": round(sum(s.category_ok for s in scores) / n, 4),
        "severity_accuracy": round(sum(s.severity_ok for s in scores) / n, 4),
        "action_accuracy": round(sum(s.action_ok for s in scores) / n, 4),
        "grounding_rate": round(sum(s.grounded for s in scores) / n, 4),
        "approval_safety": round(
            sum(s.gated_correctly for s in risky) / len(risky), 4) if risky else 1.0,
        "pass_rate": round(sum(s.passed for s in scores) / n, 4),
        "p50_latency_ms": round(percentile(latencies, 50), 2),
        "p95_latency_ms": round(percentile(latencies, 95), 2),
        "avg_usd": round(sum(s.usd for s in scores) / n, 6),
    }
