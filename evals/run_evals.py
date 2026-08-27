"""Eval harness — discover registered benchmarks, run each against the agent,
score them, and gate the release.

    python evals/run_evals.py                        # run every benchmark + write a report
    python evals/run_evals.py --gate                  # also enforce quality gates (exit 1 on fail)
    python evals/run_evals.py --benchmark golden_set  # run just one benchmark (repeatable)
    python evals/run_evals.py --workers 8             # run cases concurrently (default: 4)
    python evals/run_evals.py --workers 1             # sequential reference path

A benchmark is a directory under evals/benchmarks/<name>/ with a benchmark.toml
declaring its dataset, scorers, and gates — see registry.py and docs/evals.md.
Adding one is a new directory, not an edit to this file.

Cases within a benchmark run concurrently across a bounded worker pool. Each
case gets its own throwaway ticket DB (seeded fresh), approval store, audit
log, and idempotency store — nothing about one case's state (actions taken,
approvals granted, audit entries) is visible to another, so raising
`--workers` cannot change *what* happens in a case, only how many run at
once. Only the read-only pieces (the RAG index and the deterministic mock
provider) are shared across the pool, along with per-principal rate-limit
buckets (rate limiting is a property of the principal, not the case — see
`build_buckets`). Per-case results are sorted by case id before aggregation,
so the report is byte-identical regardless of worker count — see
`tests/test_evals.py`.

Reports are written to evals/reports/<timestamp>.json and feed drift detection.
The whole thing runs offline with the deterministic mock provider, so CI is
hermetic and reproducible.
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
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
from triage.config import Settings, get_settings  # noqa: E402
from triage.data.db import Ticket, TicketDB  # noqa: E402
from triage.data.seed import seed  # noqa: E402
from triage.enterprise.approvals import ApprovalStore  # noqa: E402
from triage.enterprise.audit import AuditLog  # noqa: E402
from triage.enterprise.auth import Principal, authenticate  # noqa: E402
from triage.enterprise.ratelimit import TokenBucket  # noqa: E402
from triage.llm import get_provider  # noqa: E402
from triage.llm.base import LLMProvider  # noqa: E402
from triage.rag.ingest import ingest  # noqa: E402
from triage.rag.retriever import Retriever  # noqa: E402
from triage.rag.store import VectorStore  # noqa: E402

REPORTS = HERE / "reports"
DEFAULT_WORKERS = 4


def ensure_index(settings: Settings) -> None:
    if not VectorStore.exists(settings.index_dir):
        ingest(verbose=False)


def build_buckets(settings: Settings) -> dict[str, TokenBucket]:
    """One `TokenBucket` per configured principal, for the whole eval run.

    Mirrors `ActionExecutor`'s own default (pre-seeded from
    `parsed_api_keys()`), but built once and handed to every per-case
    executor — see `run_case`.
    """
    return {
        api_key: TokenBucket(capacity=settings.rate_limit_per_min,
                             refill_per_sec=settings.rate_limit_per_min / 60.0)
        for api_key in settings.parsed_api_keys()
    }


def run_case(
    benchmark: Benchmark,
    case: dict,
    *,
    settings: Settings,
    provider: LLMProvider,
    retriever: Retriever,
    principal: Principal,
    buckets: dict[str, TokenBucket],
) -> tuple[dict[str, float | bool | None], dict]:
    """Run one case against a throwaway, per-case environment.

    Everything stateful *to that case* (ticket DB, approvals, audit trail,
    idempotency) is fresh for this call and discarded afterwards, so
    concurrent cases never observe or mutate each other's state. Only the
    read-only RAG index and the stateless LLM provider are shared with the
    caller — and `buckets`: rate limiting is a property of the *principal*,
    not of the case. Letting `ActionExecutor` build its own default buckets
    here would hand every case a fresh, full-capacity allowance for the same
    `demo-operator-key` used across a whole benchmark run, silently
    defeating the per-principal limit the real system guarantees (see
    `tests/test_actions.py::test_rate_limit_is_isolated_per_principal`).
    `TokenBucket.allow()` is internally lock-protected, so sharing these
    across concurrent worker threads is safe.

    Latency is measured as this thread's own CPU time (`time.thread_time()`),
    not wall-clock, and written back into `result.metrics["total_ms"]` before
    scoring so the registered `latency_ms` scorer (see `scorers.py`) reports
    it. Under a worker pool, wall-clock time also counts however long this
    case sat descheduled while sibling cases held the GIL/CPU — contention
    noise that grows with `--workers` and CI-runner load, not a change in
    what the agent actually did. CPU time isolates the case's own cost, so
    p50/p95 mean the same thing at `--workers 1` and `--workers 8` and stay
    meaningful to the drift gate as concurrency (or a noisy CI box) changes —
    see `test_p95_is_stable_across_worker_counts`.

    Returns `(per_case_row, scenario)`: `per_case_row` is what `scoring.py`
    aggregates into benchmark metrics, `scenario` is what the report shows
    for this case.
    """
    with tempfile.TemporaryDirectory(prefix="triage-eval-case-") as tmp:
        tmp_path = Path(tmp)
        db = TicketDB(tmp_path / "triage.db")
        seed(db)
        executor = ActionExecutor(
            db, AuditLog(tmp_path / "audit.jsonl"), ApprovalStore(tmp_path / "approvals.db"),
            buckets=buckets,
        )
        runner = TriageRunner(settings=settings, provider=provider, db=db,
                              retriever=retriever, executor=executor)
        ticket = Ticket(id=f"{benchmark.name}-{case['id']}", subject=case.get("subject", ""),
                        body=case.get("body", ""), requester=case.get("requester", ""))
        cpu_start = time.thread_time()
        result = runner.run(ticket, principal, run_id=f"{benchmark.name}-{case['id']}")
        result.metrics["total_ms"] = (time.thread_time() - cpu_start) * 1000.0

    row = score_case(case, result)
    scenario = {
        "id": case["id"],
        "expected": case.get("expected", {}),
        "predicted": {
            "category": result.category,
            "severity": result.severity,
            "action": result.action.get("name") or None,
            "action_status": result.action.get("status"),
        },
        "passed": bool(row.get("overall_pass", True)),
    }
    return row, scenario


def run_benchmark(
    benchmark: Benchmark,
    *,
    settings: Settings,
    provider: LLMProvider,
    retriever: Retriever,
    principal: Principal,
    buckets: dict[str, TokenBucket],
    workers: int,
) -> dict:
    cases = benchmark.load_cases()

    wall_start = time.perf_counter()
    if workers == 1:
        # The reproducible reference path: no pool, no thread scheduling.
        results = [run_case(benchmark, case, settings=settings, provider=provider,
                            retriever=retriever, principal=principal, buckets=buckets)
                   for case in cases]
    else:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = [
                pool.submit(run_case, benchmark, case, settings=settings, provider=provider,
                           retriever=retriever, principal=principal, buckets=buckets)
                for case in cases
            ]
            results = [f.result() for f in as_completed(futures)]
    wall_ms = (time.perf_counter() - wall_start) * 1000.0

    # Collect by case id and sort before scoring — `--workers 8` and
    # `--workers 1` must produce byte-identical reports.
    results.sort(key=lambda pair: pair[1]["id"])
    per_case = [row for row, _ in results]
    scenarios = [scenario for _, scenario in results]

    metrics = aggregate(benchmark, per_case)
    gate_results = evaluate_gates(benchmark, metrics)

    serial_ms = sum(row["latency_ms"] for row in per_case if row.get("latency_ms") is not None)
    saved_ms = max(0.0, serial_ms - wall_ms)
    return {
        "name": benchmark.name,
        "config": str(benchmark.config_path.relative_to(HERE)),
        "metrics": metrics,
        "gates": [asdict(g) for g in gate_results],
        "scenarios": scenarios,
        "concurrency": {
            "workers": workers,
            "wall_clock_ms": round(wall_ms, 2),
            "serial_ms_estimate": round(serial_ms, 2),
            "wall_clock_saved_ms": round(saved_ms, 2),
            "speedup_x": round(serial_ms / wall_ms, 2) if wall_ms > 0 else 1.0,
        },
    }


def run(benchmarks: list[Benchmark] | None = None, workers: int = DEFAULT_WORKERS) -> dict:
    if workers < 1:
        raise ValueError(f"workers must be >= 1, got {workers}")
    if benchmarks is None:
        benchmarks = discover_benchmarks()
    if not benchmarks:
        raise RuntimeError(f"no benchmarks registered under {HERE / 'benchmarks'}")

    s = get_settings()
    ensure_index(s)
    provider = get_provider(s)
    retriever = Retriever.from_settings(s)
    principal = authenticate("demo-operator-key")
    # Shared across every case (and every worker thread) — see `run_case`.
    buckets = build_buckets(s)

    results = [
        run_benchmark(b, settings=s, provider=provider, retriever=retriever,
                     principal=principal, buckets=buckets, workers=workers)
        for b in benchmarks
    ]

    return {
        "timestamp": datetime.now(UTC).isoformat(),
        "provider": s.llm_provider,
        "model": provider.model,
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
        c = b["concurrency"]
        print("=" * 64)
        print(f"benchmark: {b['name']}  (config={b['config']}, n={m['n']})")
        print("-" * 64)
        for k, v in m.items():
            if k == "n":
                continue
            print(f"  {k:24} {v}")
        print(f"\n  workers={c['workers']}  wall-clock={c['wall_clock_ms']}ms  "
              f"(serial estimate {c['serial_ms_estimate']}ms, "
              f"saved {c['wall_clock_saved_ms']}ms, {c['speedup_x']}x)")
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
    parser.add_argument("--workers", type=int, default=DEFAULT_WORKERS,
                        help=f"concurrent workers per benchmark (default: {DEFAULT_WORKERS}); "
                             "1 = sequential reference path")
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

    report = run(selected, workers=args.workers)
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
