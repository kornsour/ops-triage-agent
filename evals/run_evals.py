"""Eval harness — run the agent across the golden set, score it, gate the release.

    python evals/run_evals.py            # run + write a report
    python evals/run_evals.py --gate     # also enforce quality gates (exit 1 on fail)

Reports are written to evals/reports/<timestamp>.json and feed drift detection.
The whole thing runs offline with the deterministic mock provider, so CI is
hermetic and reproducible.
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from gates import all_passed, evaluate_gates  # noqa: E402
from scoring import aggregate, score_scenario  # noqa: E402

from triage.agent.actions import ActionExecutor  # noqa: E402
from triage.agent.prompts import PROMPT_VERSION  # noqa: E402
from triage.agent.runner import TriageRunner  # noqa: E402
from triage.config import get_settings  # noqa: E402
from triage.data.db import Ticket, TicketDB  # noqa: E402
from triage.data.seed import seed  # noqa: E402
from triage.enterprise.approvals import ApprovalStore  # noqa: E402
from triage.enterprise.audit import AuditLog  # noqa: E402
from triage.enterprise.auth import authenticate  # noqa: E402
from triage.llm import get_provider  # noqa: E402
from triage.rag.ingest import ingest  # noqa: E402
from triage.rag.retriever import Retriever  # noqa: E402
from triage.rag.store import VectorStore  # noqa: E402

GOLDEN = HERE / "golden" / "golden_set.jsonl"
REPORTS = HERE / "reports"


def load_golden() -> list[dict]:
    return [json.loads(line) for line in GOLDEN.read_text().splitlines() if line.strip()]


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


def run() -> dict:
    rows = load_golden()
    runner = build_runner()
    principal = authenticate("demo-operator-key")
    scores = []
    for row in rows:
        ticket = Ticket(id=f"eval-{row['id']}", subject=row["subject"],
                        body=row["body"], requester=row["requester"])
        result = runner.run(ticket, principal, run_id=f"eval-{row['id']}")
        scores.append(score_scenario(row, result))

    metrics = aggregate(scores)
    s = get_settings()
    return {
        "timestamp": datetime.now(UTC).isoformat(),
        "provider": s.llm_provider,
        "model": runner.provider.model,
        "prompt_version": PROMPT_VERSION,
        "metrics": metrics,
        "scenarios": [
            {"id": x.id, "expected": x.expected, "predicted": x.predicted,
             "grounded": x.grounded, "gated_correctly": x.gated_correctly,
             "passed": x.passed}
            for x in scores
        ],
    }


def write_report(report: dict) -> Path:
    REPORTS.mkdir(parents=True, exist_ok=True)
    stamp = report["timestamp"].replace(":", "").replace("-", "").replace(".", "")[:15]
    path = REPORTS / f"{stamp}.json"
    path.write_text(json.dumps(report, indent=2))
    return path


def print_summary(report: dict, gate_results=None) -> None:
    m = report["metrics"]
    print(f"\nEval report — provider={report['provider']} model={report['model']} "
          f"prompt={report['prompt_version']}  (n={m['n']})")
    print("-" * 64)
    for k in ("classification_accuracy", "severity_accuracy", "action_accuracy",
              "grounding_rate", "approval_safety", "pass_rate",
              "p50_latency_ms", "p95_latency_ms", "avg_usd"):
        print(f"  {k:24} {m[k]}")
    failures = [s for s in report["scenarios"] if not s["passed"]]
    if failures:
        print("\n  failing scenarios:")
        for f in failures:
            print(f"    {f['id']}: expected={f['expected']} predicted={f['predicted']}")
    if gate_results is not None:
        print("\n  gates:")
        for g in gate_results:
            flag = "PASS" if g.ok else "FAIL"
            print(f"    [{flag}] {g.name} = {g.value} ({g.kind} {g.threshold})")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the triage eval harness.")
    parser.add_argument("--gate", action="store_true", help="enforce quality gates")
    args = parser.parse_args(argv)

    report = run()
    path = write_report(report)
    gate_results = evaluate_gates(report["metrics"]) if args.gate else None
    print_summary(report, gate_results)
    print(f"\nreport written: {path.relative_to(Path.cwd()) if path.is_relative_to(Path.cwd()) else path}")

    if args.gate and not all_passed(gate_results):
        print("\nGATE FAILED — quality regression detected.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
