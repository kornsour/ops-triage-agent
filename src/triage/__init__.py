"""ops-triage-agent: an enterprise agentic IT/Ops support-triage system.

Packages:
    llm           Provider-agnostic LLM interface (mock / OpenAI / Anthropic).
    rag           Retrieval pipeline with ingestion governance.
    enterprise    Auth, approval gates, audit trail, idempotency, retries, rate limits.
    agent         Planner + tool registry + run orchestration.
    data          SQLite ticket store and seed data.
    observability Structured logging and latency/cost metrics.
    api           FastAPI backend.
"""

__version__ = "0.1.0"
