"""Drift detection — compare the two most recent eval reports.

Catches the silent-degradation failure mode: a prompt tweak or model swap that
quietly lowers quality. Flags any metric that moved beyond tolerance in the
wrong direction.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPORTS = HERE / "reports"

# metric -> ("higher_better" | "lower_better", tolerance)
DIRECTION = {
    "classification_accuracy": ("higher_better", 0.03),
    "severity_accuracy": ("higher_better", 0.03),
    "action_accuracy": ("higher_better", 0.03),
    "grounding_rate": ("higher_better", 0.03),
    "approval_safety": ("higher_better", 0.0),
    "pass_rate": ("higher_better", 0.03),
    "p95_latency_ms": ("lower_better", 0.50),  # fractional tolerance for latency
    "avg_usd": ("lower_better", 0.50),
}


def latest_reports(n: int = 2) -> list[Path]:
    return sorted(REPORTS.glob("*.json"))[-n:]


def main() -> int:
    reports = latest_reports(2)
    if len(reports) < 2:
        print(f"Need 2 reports to detect drift; found {len(reports)} in {REPORTS}.")
        return 0
    prev, curr = json.loads(reports[0].read_text()), json.loads(reports[1].read_text())
    pm, cm = prev["metrics"], curr["metrics"]
    print(f"Drift: {reports[0].name}  ->  {reports[1].name}")
    print("-" * 60)
    regressions = []
    for metric, (direction, tol) in DIRECTION.items():
        if metric not in pm or metric not in cm:
            continue
        before, after = pm[metric], cm[metric]
        delta = after - before
        if direction == "higher_better":
            regressed = delta < -tol
        else:  # lower_better — tolerance is fractional for latency/cost
            regressed = before > 0 and (after - before) / before > tol
        flag = "REGRESSION" if regressed else "ok"
        print(f"  {metric:24} {before} -> {after}  (Δ{delta:+.4f})  [{flag}]")
        if regressed:
            regressions.append(metric)
    if regressions:
        print(f"\nDRIFT DETECTED in: {', '.join(regressions)}", file=sys.stderr)
        return 1
    print("\nNo drift beyond tolerance.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
