# Data Governance

The retrieval corpus is the agent's source of truth, so it is governed at
ingestion rather than trusted blindly. This note maps the implementation to the
governance concerns an enterprise platform team will ask about.

## Scope

Governance applies to the **knowledge base** (`knowledge_base/*.md`) that feeds
RAG, and to the **runtime data** the agent reads (tickets, users) and writes
(runs, approvals, audit).

## Ingestion controls (`src/triage/rag/ingest.py`)

Each document passes three checks before it can enter the index:

| Stage | Checks | On failure |
| --- | --- | --- |
| **Schema** | required metadata present and well-formed: `id` (must match `kb-<slug>`), `title`, `owner`, `last_reviewed` (ISO-8601), `tags` | **blocking** — document excluded from the index |
| **Quality** | non-empty body; minimum length; recognized id format | **blocking** |
| **Lineage / freshness** | record source path, content SHA-256, ingest timestamp, and review age; flag if `last_reviewed` is older than the staleness window | **warning** — surfaced, not blocked |

The ingestion run prints and returns a governance report (counts of ingested /
rejected / warnings, per-document detail), which the test suite asserts on.

## Lineage

Every indexed chunk carries a `lineage` record:

```json
{
  "source": "knowledge_base/password-reset.md",
  "content_sha256": "…",
  "ingested_at": "2026-06-29T…Z",
  "last_reviewed": "2026-05-01"
}
```

This makes it possible to answer "where did this answer come from, from which
version of which runbook, ingested when?" — and to invalidate the index when a
source changes (the content hash changes).

## Runtime data classes

| Data | Store | Sensitivity | Controls |
| --- | --- | --- | --- |
| Tickets | SQLite (Postgres in prod) | internal | read requires `viewer` |
| Directory / users | SQLite | PII (email, manager) | read requires `viewer`; minimized to what triage needs |
| Runs | SQLite | internal | persisted with metrics for audit/replay |
| Approvals | SQLite | sensitive (access changes) | write requires `admin`; full decision record |
| Audit | hash-chained JSONL | sensitive | append-only, tamper-evident, `verify()` |

## Grounding & provenance at answer time

The responder is instructed to use **only** retrieved context and to cite the
runbook ids it used. A grounding check rejects any citation that is not in the
retrieved set, and the eval harness enforces a corpus-wide `grounding_rate` gate.
This ties every generated answer back to governed source documents.

## What production would add

- Real PII handling: field-level encryption, retention policies, DSAR support.
- Access logging on the data stores themselves, not just the action audit.
- A review workflow that enforces `last_reviewed` refresh (the staleness warning
  becomes a blocking policy past a threshold).
- Index invalidation wired to source-control changes via the content hash.
