"""Drift detection — compare two eval reports.

Catches the silent-degradation failure mode: a prompt tweak or model swap that
lowers quality without failing an absolute gate. `detect` flags any metric that
moved beyond tolerance in the wrong direction.

    python evals/drift.py                          # two latest reports in evals/reports/
    python evals/drift.py prev.json curr.json       # two explicit report paths (used in CI,
                                                      # where the previous report is restored
                                                      # from a prior run rather than sitting
                                                      # on disk next to the new one)
"""

from __future__ import annotations

import argparse
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
    "injection_defense": ("higher_better", 0.0),
    "pass_rate": ("higher_better", 0.03),
    "p95_latency_ms": ("lower_better", 0.50),  # fractional tolerance for latency
    "avg_usd": ("lower_better", 0.50),
}


def detect(prev: dict[str, float], curr: dict[str, float]) -> list[str]:
    """Return the names of metrics that regressed beyond tolerance."""
    regressions = []
    for metric, (direction, tol) in DIRECTION.items():
        if metric not in prev or metric not in curr:
            continue
        before, after = prev[metric], curr[metric]
        if direction == "higher_better":
            regressed = (after - before) < -tol
        else:  # lower_better — tolerance is fractional for latency/cost
            regressed = before > 0 and (after - before) / before > tol
        if regressed:
            regressions.append(metric)
    return regressions


def latest_reports(n: int = 2) -> list[Path]:
    return sorted(REPORTS.glob("*.json"))[-n:]


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("prev", nargs="?", type=Path,
                         help="earlier report (default: 2nd-most-recent in evals/reports/)")
    parser.add_argument("curr", nargs="?", type=Path,
                         help="later report (default: most recent in evals/reports/)")
    args = parser.parse_args(argv)
    if bool(args.prev) != bool(args.curr):
        parser.error("pass both report paths, or neither")
    return args


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.prev and args.curr:
        reports = [args.prev, args.curr]
    else:
        reports = latest_reports(2)
        if len(reports) < 2:
            print(f"Need 2 reports to detect drift; found {len(reports)} in {REPORTS}.")
            return 0
    prev, curr = json.loads(reports[0].read_text()), json.loads(reports[1].read_text())
    pm, cm = prev["metrics"], curr["metrics"]
    print(f"Drift: {reports[0].name}  ->  {reports[1].name}")
    print("-" * 60)
    regressions = detect(pm, cm)
    for metric in DIRECTION:
        if metric not in pm or metric not in cm:
            continue
        before, after = pm[metric], cm[metric]
        flag = "REGRESSION" if metric in regressions else "ok"
        print(f"  {metric:24} {before} -> {after}  (Δ{after - before:+.4f})  [{flag}]")
    if regressions:
        print(f"\nDRIFT DETECTED in: {', '.join(regressions)}", file=sys.stderr)
        return 1
    print("\nNo drift beyond tolerance.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
