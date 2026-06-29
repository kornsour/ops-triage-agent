# Architecture Decision Record

Numbered, dated decisions with their context, the choice made, and the trade-off
accepted. ADRs are deliberately terse — they record *why*, not *how*.

---

## ADR-001 — A deterministic offline provider is the default LLM backend

**Date:** 2026-06-29 · **Status:** accepted

**Context.** A portfolio system that only runs with a paid API key can't be
cloned and evaluated by a reviewer, can't run in CI, and produces
non-reproducible eval numbers.

**Decision.** Depend only on a small `LLMProvider` interface. Ship a
deterministic `MockProvider` that implements genuine keyword/heuristic triage
logic as the default, with `OpenAIProvider` and `AnthropicProvider` as one-line,
config-selected swaps.

**Consequences.** `make demo`, the test suite, and the eval harness all run
offline and reproducibly. The cost is that the offline classifier is rules-based,
not learned — but the *architecture* (the agent loop, controls, evals) is exactly
what a real model plugs into, and that is the thing being demonstrated.

---

## ADR-002 — One chokepoint for every side-effect

**Date:** 2026-06-29 · **Status:** accepted

**Context.** Agents that can take actions are dangerous precisely when an action
slips through without authorization, approval, or a record.

**Decision.** Route every guarded action through a single `ActionExecutor` that
enforces auth → rate limit → idempotency → approval policy → retry → audit, in
that order. Tools expose only the raw effect; nothing calls effects directly.

**Consequences.** The safety properties are enforced in one auditable place and
are unit-tested as invariants (e.g. "a viewer can never request an action",
"a high-risk action is never auto-executed"). The cost is a little indirection
between the planner and the downstream system.

---

## ADR-003 — Approvals are risk-tiered, not all-or-nothing

**Date:** 2026-06-29 · **Status:** accepted

**Context.** Requiring human approval for *every* action makes the agent useless;
requiring it for *none* makes it unsafe.

**Decision.** Each action carries a risk policy. Low-risk actions that only notify
a human (`escalate`, `post_reply`) auto-execute and are audited; medium/high-risk
actions that change identity or access (`reset_password`, `grant_access`) require
an admin decision before they run.

**Consequences.** The agent is autonomous where it is safe to be and gated where
it is not. The policy table is the security-review surface and is small by design.

---

## ADR-004 — The audit trail is hash-chained

**Date:** 2026-06-29 · **Status:** accepted

**Context.** An audit log that can be edited after the fact is not evidence.

**Decision.** Each audit entry includes the hash of the previous entry; `verify()`
recomputes the chain and detects any edit, reorder, or deletion.

**Consequences.** Tamper-evidence with no external dependency. It is not
tamper-*proof* (an attacker who can rewrite the whole file can recompute hashes);
production would anchor periodically to an append-only store / WORM bucket. The
chain makes silent single-record edits detectable, which is the common case.

---

## ADR-005 — Evaluations gate releases; they are not a side report

**Date:** 2026-06-29 · **Status:** accepted

**Context.** Prompt and model changes can silently degrade quality. "It looked
fine" is not a release criterion.

**Decision.** A golden dataset + scoring harness produces metrics that CI
enforces as hard gates (`make eval-gate`), including a non-negotiable safety
invariant (`approval_safety == 1.0`). Reports are persisted and compared run over
run for drift.

**Consequences.** Quality regressions block the merge. The golden set must be
grown and curated — that maintenance is the point, and it mirrors the
deployment→product feedback loop the role descriptions ask for.

---

## ADR-006 — Retrieval ships with ingestion governance

**Date:** 2026-06-29 · **Status:** accepted

**Context.** RAG quality is bounded by corpus quality; ungoverned ingestion is
how stale or malformed runbooks poison answers.

**Decision.** Ingestion validates required metadata (schema), enforces content
quality, and records lineage (source, content hash, ingest time, review age).
Blocking failures exclude a document; quality warnings (e.g. stale review)
surface without blocking.

**Consequences.** The index is trustworthy and auditable. The default embedder is
deterministic hashing (offline); production swaps in real semantic embeddings and
a pgvector/FAISS store behind the same interface.

---

## ADR-007 — A standard MCP server is the integration surface

**Date:** 2026-06-29 · **Status:** accepted

**Context.** The tools should be reusable by other agents and clients, not locked
inside this one app.

**Decision.** Expose the tools over the Model Context Protocol, but mediate every
call through the same enterprise-controls executor the in-process agent uses.

**Consequences.** Any MCP client (Claude Desktop, an IDE, another agent) gets the
tools *with* the controls intact. The protocol handlers are thin wrappers over a
synchronous, unit-tested core.
