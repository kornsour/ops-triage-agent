# Reference Architecture

How the system is put together, end to end. This is the document a Solutions
Architect would hand to a customer's platform team to show how the agent would be
deployed inside their environment.

## 1. System context

```
        ┌──────────────┐         ┌───────────────────────────────────────┐
 user → │ React/TS UI  │ ──────▶ │            FastAPI backend            │
        │ (operator/   │  HTTPS  │  authN/Z · triage API · approvals     │
        │  admin/      │  X-API- │  audit · evals                        │
        │  viewer)     │  Key    └───────────────┬───────────────────────┘
        └──────────────┘                         │
                                                 ▼
                              ┌──────────────────────────────────────────┐
   other MCP clients ───────▶ │              Agent core                  │
   (Claude Desktop, IDEs)     │  guardrail → tool-calling loop → answer   │
        via MCP server        │                                          │
                              │   ┌────────────┐   ┌───────────────────┐ │
                              │   │   RAG      │   │ Enterprise control│ │
                              │   │ retriever  │   │ auth·approval·    │ │
                              │   │ + governed │   │ idempotency·rate· │ │
                              │   │   index    │   │ retry·audit       │ │
                              │   └─────┬──────┘   └─────────┬─────────┘ │
                              └─────────┼────────────────────┼───────────┘
                                        ▼                    ▼
                                ┌──────────────┐    ┌──────────────────┐
                                │ vector store │    │ downstream systems│
                                │ + ticket DB  │    │ (IdP, ticketing,  │
                                │ (SQLite)     │    │  notifications)   │
                                └──────────────┘    └──────────────────┘
                                        ▲
                                ┌───────┴────────┐
                                │ LLM provider   │
                                │ mock|OpenAI|   │
                                │ Anthropic      │
                                └────────────────┘
```

## 2. Request flow — a single triage run

1. **Ingress / authN.** The UI (or an MCP client) calls the backend with an
   `X-API-Key`. The key resolves to a `Principal` with a role
   (`viewer` < `operator` < `admin`). Running triage requires `operator`.
2. **Guardrail.** The ticket text is scanned for prompt-injection patterns. A hit
   is recorded on the run and forces every subsequent action through approval.
3. **Tool-calling loop.** Each turn the model returns JSON that either calls read
   tools (`search_runbooks` over the governed index, `lookup_ticket_history`,
   `lookup_user`) or finalizes. The runner executes the calls, feeds observations
   back, and repeats up to a step budget. The final answer carries the
   classification, a reply grounded *only* in retrieved runbooks with citations,
   and at most one recommended guarded action. A grounding check rejects any
   citation not in the set the tools actually returned; if that leaves no valid
   citation, the run's `status` is `ungrounded`.
4. **Act.** Any recommended guarded action is routed through the
   `ActionExecutor`: auth → rate limit → idempotency → approval policy → retry →
   audit. Low-risk actions auto-execute; medium/high-risk actions — and any action
   from a run flagged for injection — return `pending_approval`. The exception is
   `post_reply` on an `ungrounded` run: it is suppressed before it ever reaches
   the executor, so a fabricated draft is never posted to the requester.
5. **Approve (separate request).** An admin approves via the UI/MCP; the executor
   runs the effect once (idempotent) and writes the execution to the audit chain.
6. **Observe.** Latency per step, token usage, and USD cost are recorded on the
   run; the structured run record is persisted.

## 3. Components and their production swaps

| Concern | Reference implementation | Production swap |
| --- | --- | --- |
| LLM | deterministic mock | OpenAI / Anthropic (interface unchanged) |
| Embeddings | feature-hashing (offline) | `text-embedding-3` / managed embeddings |
| Vector store | numpy cosine + on-disk | pgvector / FAISS / managed vector DB |
| Ticket DB | SQLite | Postgres |
| Approvals store | SQLite | Postgres + workflow engine / queue |
| AuthN/Z | API-key → role | OIDC / SSO + fine-grained RBAC |
| Audit | hash-chained JSONL | append-only store / WORM bucket, periodic anchoring |
| Transport | FastAPI + MCP stdio | same + MCP over HTTP, gateway, mTLS |

Every swap is behind an interface the rest of the system already depends on, so
it is a configuration/adapter change, not a rewrite.

## 4. Security & governance posture

- **Least privilege** at two layers: human roles (RBAC) and per-action risk
  policy.
- **Human-in-the-loop** for any identity/access mutation.
- **Untrusted input** — ticket content is treated as data, not instructions;
  injection attempts are flagged and force actions to approval.
- **Tamper-evident audit** of every request, decision, and execution.
- **Idempotency** so retries and re-runs never double-apply an effect.
- **Data lineage** on every retrieved document (source, hash, ingest time,
  review age), with stale-content warnings.
- **Eval-gated releases** with a hard safety invariant that risky actions are
  always gated.

## 5. Deployment shape

- Backend: a stateless container (FastAPI/uvicorn) behind a gateway; scale
  horizontally. State lives in Postgres + the vector DB + the audit store.
- MCP server: runs alongside the agent core; exposed to internal clients over the
  protocol with the same auth.
- UI: static build served from any CDN/host; talks to the backend over HTTPS.
- CI: tests + eval gate must pass before deploy; eval reports are archived as
  build artifacts for drift tracking.

## 6. Failure modes considered

| Failure | Handling |
| --- | --- |
| Downstream effect flaky | bounded retry with backoff in the executor |
| Duplicate / replayed request | idempotency key replays the first result |
| Runaway agent loop | per-principal rate limiting; per-run cost/latency budget |
| Model degradation | eval gate + drift detection block the release |
| Stale runbook | ingestion lineage surfaces a staleness warning |
| Prompt injection in a ticket | guardrail flags the run and forces actions to approval |
| Audit tampering | chain verification detects edits/reorder/deletion |
