# Solution Brief — Agentic IT/Ops Support Triage

*One-page, customer-facing framing. The kind of brief a Solutions Architect uses
to translate a business problem into a deployable design for an executive
audience.*

---

### The problem

Internal IT/Ops support queues are slow and expensive. Tickets wait for a human
to read them, find the right runbook, check the requester's history, draft a
reply, and take an action (reset a password, grant access, escalate an outage).
Most of that is repetitive — but the few high-stakes steps (changing access,
touching production) are exactly the ones you cannot let an automated system do
blindly.

### The solution

An agent that works the queue end to end and **knows the difference between what
it can do autonomously and what a human must approve.** For each ticket it
retrieves the relevant runbook, drafts a grounded response that cites its
sources, and either takes a safe action automatically or holds a risky one for a
one-click admin approval — with every step recorded in a tamper-evident audit
trail.

### How it works (at a glance)

```
ticket → retrieve runbook → classify & plan → check history
       → draft grounded reply → safe action auto-runs / risky action waits for approval
```

### Why it's safe to deploy

| Concern an exec will raise | How the design answers it |
| --- | --- |
| "Will it do something it shouldn't?" | Every action passes one controlled gate; identity/access changes require admin approval. |
| "Can we prove what it did?" | Hash-chained audit trail of every request, decision, and execution. |
| "Will quality quietly slip?" | Releases are blocked by an evaluation gate with a hard safety invariant. |
| "Will it hallucinate answers?" | Replies are grounded in retrieved runbooks and citation-checked. |
| "What does it cost to run?" | Per-ticket latency, tokens, and dollar cost are tracked on every run. |

### Business outcomes to measure

- **Time-to-resolution** ↓ on the automatable share of the queue.
- **Cost-per-ticket** tracked directly (tokens × price) per run.
- **Zero unapproved high-risk actions** — enforced, not hoped for.
- **Deflection rate**: tickets fully resolved without a human touch (low-risk
  categories) vs. routed for approval.

### Deployment

Stateless backend container + Postgres + a vector store, behind your SSO. Model
provider is pluggable (OpenAI or Anthropic). Tools are also exposed over the
Model Context Protocol, so the same governed capabilities are available to other
internal agents and assistants. A pilot runs against a read-only copy of one
ticket category; expand category-by-category as eval coverage grows.

### Why this team / approach

The hard part of enterprise agents isn't the model — it's the controls,
governance, and evaluation around it. This solution leads with that layer:
least-privilege RBAC, risk-tiered human approval, tamper-evident audit, data
lineage, and eval-gated releases, all demonstrated in a working full-stack
system. See [`reference-architecture.md`](reference-architecture.md) for the
deployable design and [`architecture-decision-record.md`](architecture-decision-record.md)
for the decisions and trade-offs behind it.
