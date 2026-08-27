"""Eval harness — discover registered benchmarks, run each against the agent,
score them, and gate the release.

    python evals/run_evals.py                    # run every benchmark + write a report
    python evals/run_evals.py --gate              # also enforce quality gates (exit 1 on fail)
    python evals/run_evals.py --benchmark golden_set  # run just one benchmark (repeatable)

A benchmark is a directory under evals/benchmarks/<name>/ with a benchmark.toml
declaring its dataset, scorers, and gates — see registry.py and docs/evals.md.
Adding one is a new directory, not an edit to this file.

Reports are written to evals/reports/<timestamp>.json and feed drift detection.
The whole thing runs offline with the deterministic mock provider, so CI is
hermetic and reproducible.
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from gates import evaluate_gates  # noqa: E402
from registry import Benchmark, discover_benchmarks  # noqa: E402
from scoring import aggregate, score_case  # noqa: E402

from triage.agent.actions import ActionExecutor  # noqa: E402
from triage.agent.prompts import PROMPT_VERSION  # noqa: E402
from triage.agent.runner import TriageRunner  # noqa: E402
from triage.config import get_settings  # noqa: E402
from triage.data.db import Ticket, TicketDB  # noqa: E402
from triage.data.seed import seed  # noqa: E402
from triage.enterprise.approvals import ApprovalStore  # noqa: E402
from triage.enterprise.audit import AuditLog  # noqa: E402
from triage.enterprise.auth import Principal, authenticate  # noqa: E402
from triage.llm import get_provider  # noqa: E402
from triage.rag.ingest import ingest  # noqa: E402
from triage.rag.retriever import Retriever  # noqa: E402
from triage.rag.store import VectorStore  # noqa: E402

REPORTS = HERE / "reports"


def build_runner() -> TriageRunner:
    s = get_settings()
    if not s.db_path.exists():
        seed()
    if not VectorStore.exists(s.index_dir):
        ingest(verbose=False)
    db = TicketDB(s.db_path)
    retriever = Retriever.from_settings(s)
    # Isolated controls so re-running evals is clean (fresh approvals + idempotency).
    tmp = Path(tempfile.mkdtemp(prefix="triage-eval-"))
    executor = ActionExecutor(db, AuditLog(tmp / "audit.jsonl"), ApprovalStore(tmp / "approvals.db"))
    return TriageRunner(settings=s, provider=get_provider(s), db=db,
                        retriever=retriever, executor=executor)


def run_benchmark(benchmark: Benchmark, runner: TriageRunner, principal: Principal) -> dict:
    cases = benchmark.load_cases()
    per_case = []
    scenarios = []
    for case in cases:
        ticket = Ticket(id=f"{benchmark.name}-{case['id']}", subject=case.get("subject", ""),
                        body=case.get("body", ""), requester=case.get("requester", ""))
        result = runner.run(ticket, principal, run_id=f"{benchmark.name}-{case['id']}")
        row = score_case(case, result)
        per_case.append(row)
        scenarios.append({
            "id": case["id"],
            "expected": case.get("expected", {}),
            "predicted": {
                "category": result.category,
                "severity": result.severity,
                "action": result.action.get("name") or None,
                "action_status": result.action.get("status"),
            },
            "passed": bool(row.get("overall_pass", True)),
        })

    metrics = aggregate(benchmark, per_case)
    gate_results = evaluate_gates(benchmark, metrics)
    return {
        "name": benchmark.name,
        "config": str(benchmark.config_path.relative_to(HERE)),
        "metrics": metrics,
        "gates": [asdict(g) for g in gate_results],
        "scenarios": scenarios,
    }


def run(benchmarks: list[Benchmark] | None = None) -> dict:
    if benchmarks is None:
        benchmarks = discover_benchmarks()
    if not benchmarks:
        raise RuntimeError(f"no benchmarks registered under {HERE / 'benchmarks'}")

    runner = build_runner()
    principal = authenticate("demo-operator-key")
    results = [run_benchmark(b, runner, principal) for b in benchmarks]

    s = get_settings()
    return {
        "timestamp": datetime.now(UTC).isoformat(),
        "provider": s.llm_provider,
        "model": runner.provider.model,
        "prompt_version": PROMPT_VERSION,
        "benchmarks": results,
    }


def write_report(report: dict) -> Path:
    REPORTS.mkdir(parents=True, exist_ok=True)
    stamp = report["timestamp"].replace(":", "").replace("-", "").replace(".", "")[:15]
    path = REPORTS / f"{stamp}.json"
    path.write_text(json.dumps(report, indent=2))
    return path


def print_summary(report: dict, gated: bool) -> None:
    print(f"\nEval report — provider={report['provider']} model={report['model']} "
          f"prompt={report['prompt_version']}")
    for b in report["benchmarks"]:
        m = b["metrics"]
        print("=" * 64)
        print(f"benchmark: {b['name']}  (config={b['config']}, n={m['n']})")
        print("-" * 64)
        for k, v in m.items():
            if k == "n":
                continue
            print(f"  {k:24} {v}")
        failures = [s for s in b["scenarios"] if not s["passed"]]
        if failures:
            print("\n  failing scenarios:")
            for f in failures:
                print(f"    {f['id']}: expected={f['expected']} predicted={f['predicted']}")
        if gated:
            print("\n  gates:")
            for g in b["gates"]:
                flag = "PASS" if g["ok"] else "FAIL"
                print(f"    [{flag}] {g['name']} = {g['value']} ({g['kind']} {g['threshold']})")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the triage eval harness.")
    parser.add_argument("--gate", action="store_true", help="enforce quality gates")
    parser.add_argument("--benchmark", action="append", dest="benchmarks", metavar="NAME",
                         help="run only this benchmark (repeatable); default: all registered")
    args = parser.parse_args(argv)

    all_benchmarks = discover_benchmarks()
    if args.benchmarks:
        by_name = {b.name: b for b in all_benchmarks}
        missing = [n for n in args.benchmarks if n not in by_name]
        if missing:
            print(f"unknown benchmark(s): {', '.join(missing)} "
                  f"(available: {', '.join(sorted(by_name)) or 'none'})", file=sys.stderr)
            return 2
        selected = [by_name[n] for n in args.benchmarks]
    else:
        selected = all_benchmarks

    report = run(selected)
    path = write_report(report)
    print_summary(report, gated=args.gate)
    print(f"\nreport written: {path.relative_to(Path.cwd()) if path.is_relative_to(Path.cwd()) else path}")

    failed_benchmarks = [b["name"] for b in report["benchmarks"]
                          if not all(g["ok"] for g in b["gates"])]
    if args.gate and failed_benchmarks:
        print(f"\nGATE FAILED — quality regression detected in: {', '.join(failed_benchmarks)}.",
              file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
