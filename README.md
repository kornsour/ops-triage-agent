# ops-triage-agent

> An enterprise agentic system that triages an internal IT/Ops support queue end to end — it retrieves context, drafts grounded responses, and takes **guarded** actions behind human-approval gates, with every release gated by an evaluation harness.

[![CI](https://github.com/kornsour/ops-triage-agent/actions/workflows/ci.yml/badge.svg)](https://github.com/kornsour/ops-triage-agent/actions/workflows/ci.yml)
&nbsp;Python 3.11+ · FastAPI · React/TypeScript · MCP · runs fully offline (no API key required)

---

## Why this project exists

Most public "AI agent" demos are a chat loop wired to a couple of tools. The hard
part of shipping agents *inside an enterprise* is everything around the model:
authentication, permissions, idempotency, rate limits, human-approval gates,
audit trails, data governance, and — above all — **evaluations that gate
releases**. This repo is built to demonstrate exactly that layer.

It is deliberately the kind of internal-platform build an applied-AI platform
team does, delivered the way a forward-deployed engineer would ship it: a real
multi-step agent, a real database and retrieval pipeline, a real MCP server with
enterprise controls, a thin TypeScript UI, and an eval-gated CI pipeline.

**It runs with zero API keys.** A deterministic offline provider implements
genuine triage logic, so `make demo`, the test suite, and the eval harness all
produce meaningful, reproducible results. Swapping in OpenAI or Anthropic is a
one-line config change — the agent loop is identical.

## What it does

The agent works an internal support queue. For each ticket it runs a multi-step,
tool-routing workflow:

```
retrieve runbooks (RAG) → plan + classify (LLM) → gather context (DB tools)
        → draft grounded reply (LLM) → take guarded action (approval-gated)
```

- A **password lockout** ticket is classified `access_password`, the relevant
  runbook is retrieved and cited, and a `reset_password` action is created — but
  because it is medium-risk, it is **held for admin approval**, not executed.
- A **"whole team is down"** ticket is classified `incident / high`, and an
  `escalate` action **auto-executes** (it only notifies a human) and is recorded
  in the audit trail.
- A **repo-access** request is classified `access_request`, and a high-risk
  `grant_access` action is held for approval with the requester's directory
  record attached.

## The eval harness is the centerpiece

Releases are gated, not vibes-checked. `make eval-gate` runs the agent across a
golden dataset and fails CI if any quality metric regresses:

| Metric | What it measures | Gate |
| --- | --- | --- |
| `classification_accuracy` | category predicted correctly | ≥ 0.85 |
| `severity_accuracy` | severity predicted correctly | ≥ 0.85 |
| `action_accuracy` | correct guarded action recommended | ≥ 0.85 |
| `grounding_rate` | replies cite only retrieved runbooks (no hallucinated sources) | ≥ 0.90 |
| `approval_safety` | every high/medium-risk action was gated, never auto-run | = 1.0 |
| `p95_latency_ms` / `avg_usd` | runtime cost & latency budgets | budgeted |

The harness also performs **drift detection** between report runs, so a prompt or
model change that quietly degrades quality is caught before it ships.

## Quickstart

```bash
make install     # uv venv (Python 3.12) + dev deps
make demo        # seed data, build the RAG index, run triage end-to-end
make test        # full offline test suite
make eval        # run the eval harness, write evals/reports/<ts>.json
make serve       # FastAPI backend on :8000  (docs at /docs)
make web         # React/TypeScript dashboard (proxies to :8000)
```

To use a real model:

```bash
export TRIAGE_LLM_PROVIDER=anthropic        # or openai
export TRIAGE_LLM_MODEL=claude-opus-4-8     # or gpt-4.1
export ANTHROPIC_API_KEY=...                # or OPENAI_API_KEY
uv pip install -e ".[anthropic]"            # or .[openai]
```

## Architecture

```
src/triage/
├── llm/            provider-agnostic interface: mock (offline) | openai | anthropic
├── rag/            embeddings · cosine vector store · ingestion governance · retriever
├── enterprise/     auth · approval gates · hash-chained audit · idempotency · rate limit · retry
├── agent/          tool registry · guarded-action executor · planner/responder · run orchestrator
├── data/           SQLite ticket store + seed queue
├── observability/  structured logging · latency/cost/token metrics
└── api/            FastAPI backend
mcp_server/         MCP server exposing the enterprise tools with controls
evals/              golden set · scoring · regression gates · drift detection
web/                React + TypeScript dashboard
docs/               architecture decision record · reference architecture · solution brief · data governance
knowledge_base/     runbooks (the RAG corpus)
```

See [`docs/reference-architecture.md`](docs/reference-architecture.md) for the
full design, [`docs/architecture-decision-record.md`](docs/architecture-decision-record.md)
for the key decisions and trade-offs, and
[`docs/solution-brief.md`](docs/solution-brief.md) for the one-page,
customer-facing framing.

## Enterprise controls (the differentiator)

Every side-effect passes through a single guarded-action executor that enforces:

- **AuthN/Z** — API-key → role (`viewer` < `operator` < `admin`); only operators
  request actions, only admins approve them.
- **Approval gates** — per-action risk policy; medium/high-risk actions require an
  admin decision before they run.
- **Idempotency** — identical `(action, args)` executes once and replays after.
- **Rate limiting** — per-principal token bucket protects downstream systems.
- **Retries** — bounded exponential backoff around flaky downstream effects.
- **Audit trail** — append-only, **hash-chained**, tamper-evident; `verify()`
  detects any edit, reorder, or deletion.

## Business value

The framing the README leads with on purpose: this is a system that **cuts
time-to-resolution** on a support queue while **never letting an agent take an
unsafe action unattended**. Time-per-ticket, cost-per-task, and tail latency are
tracked on every run; releases are gated by evals so quality can't silently
regress; and the deployment-to-product feedback loop (golden-set growth, drift
detection) is built in. The same artifact serves a Forward Deployed Engineer
narrative (shipped full-stack, measurable workflow impact), a Solutions Architect
narrative (see the solution brief + reference architecture), and an Enterprise AI
Platform narrative (the controls + governance + eval layer).

## License

MIT — see [LICENSE](LICENSE).
