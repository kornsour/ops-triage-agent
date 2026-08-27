"""Opt-in live-model smoke test for the real provider path.

Every other test exercises the OpenAI/Anthropic adapters against injected fake
clients (test_llm_adapters.py) or the offline mock provider (everything else),
so the JSON contract between AGENT_SYSTEM (triage/agent/prompts.py) and an
actual model has never been checked. This test closes that gap by running one
golden ticket end to end through the real `OpenAIProvider` and asserting the
loop still produces a parseable `final` with a valid category, severity, and
action.

Skipped by default — it costs real money and depends on a live API — so it
never runs on an ordinary push or PR. Run it deliberately with:

    OPENAI_API_KEY=sk-... pytest tests/test_live_smoke.py -v

Optionally point it at a cheaper model:

    OPENAI_API_KEY=sk-... TRIAGE_LLM_MODEL=gpt-4o-mini pytest tests/test_live_smoke.py -v
"""

from __future__ import annotations

import os

import pytest

from triage.agent.tools import ACTION_EFFECTS
from triage.data.db import Ticket

pytestmark = pytest.mark.skipif(
    not os.getenv("OPENAI_API_KEY"),
    reason="opt-in live-model test: set OPENAI_API_KEY to run it",
)

# Mirrors the contract advertised to the model in triage/agent/prompts.py.
_VALID_CATEGORIES = {
    "incident", "access_password", "access_request",
    "network", "hardware", "productivity", "general",
}
_VALID_SEVERITIES = {"high", "medium", "low"}


@pytest.fixture
def live_settings(tmp_path, monkeypatch):
    """Same shape as the offline `settings` fixture in conftest.py, but wired
    to the real openai provider instead of forcing `mock`."""
    monkeypatch.setenv("TRIAGE_DB_PATH", str(tmp_path / "triage.db"))
    monkeypatch.setenv("TRIAGE_INDEX_DIR", str(tmp_path / "index"))
    monkeypatch.setenv("TRIAGE_AUDIT_PATH", str(tmp_path / "audit.jsonl"))
    monkeypatch.setenv("TRIAGE_LLM_PROVIDER", "openai")

    from triage.config import get_settings

    get_settings.cache_clear()
    s = get_settings()
    yield s
    get_settings.cache_clear()


def test_live_openai_golden_ticket_end_to_end(live_settings):
    from triage.agent.runner import TriageRunner
    from triage.data.seed import seed
    from triage.enterprise.auth import authenticate
    from triage.rag.ingest import ingest

    seed()
    ingest(verbose=False)

    # gold-001 from evals/golden/golden_set.jsonl — a simple, unambiguous case.
    ticket = Ticket(
        id="live-smoke-001",
        subject="Locked out of my account",
        body=(
            "I've tried my password 5 times and now I'm locked out. I have a "
            "customer demo in an hour. Please help ASAP."
        ),
        requester="dana@acme.com",
    )
    principal = authenticate("demo-operator-key", live_settings)
    runner = TriageRunner(settings=live_settings)

    # Sanity check that we're actually hitting the real adapter, not the mock.
    assert runner.provider.model != "mock-1"

    result = runner.run(ticket, principal)

    # The one thing the mock and the recorded-response tests cannot prove:
    # that a real model, given AGENT_SYSTEM, converges on the tool-calling
    # loop's JSON contract within the step budget.
    assert result.status != "step_budget_exceeded", (
        f"model never returned a parseable `final` within the step budget; "
        f"trace={[s.step for s in result.trace]}"
    )
    assert result.category in _VALID_CATEGORIES
    assert result.severity in _VALID_SEVERITIES
    assert result.action["name"] is None or result.action["name"] in ACTION_EFFECTS

    # Record the result so it's visible in CI logs / manual runs, per the issue's
    # "done when" — proof this was actually exercised against a live model.
    print(
        f"\nlive smoke result: model={runner.provider.model} "
        f"category={result.category} severity={result.severity} "
        f"action={result.action['name']} grounded={result.grounded} "
        f"usd={result.metrics['usd']} tokens={result.metrics['total_tokens']}"
    )
