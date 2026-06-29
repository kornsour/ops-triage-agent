"""Shared fixtures. Every test runs against an isolated temp DB / index / audit
log and the offline mock provider — no secrets, no shared state, no network.
"""

from __future__ import annotations

import pytest

from triage.config import get_settings


@pytest.fixture
def settings(tmp_path, monkeypatch):
    monkeypatch.setenv("TRIAGE_DB_PATH", str(tmp_path / "triage.db"))
    monkeypatch.setenv("TRIAGE_INDEX_DIR", str(tmp_path / "index"))
    monkeypatch.setenv("TRIAGE_AUDIT_PATH", str(tmp_path / "audit.jsonl"))
    monkeypatch.setenv("TRIAGE_LLM_PROVIDER", "mock")
    get_settings.cache_clear()
    s = get_settings()
    yield s
    get_settings.cache_clear()


@pytest.fixture
def seeded(settings):
    from triage.data.seed import seed
    from triage.rag.ingest import ingest

    seed()
    ingest(verbose=False)
    return settings


@pytest.fixture
def runner(seeded):
    from triage.agent.runner import TriageRunner

    return TriageRunner()


@pytest.fixture
def operator(settings):
    from triage.enterprise.auth import authenticate

    return authenticate("demo-operator-key", settings)


@pytest.fixture
def admin(settings):
    from triage.enterprise.auth import authenticate

    return authenticate("demo-admin-key", settings)


@pytest.fixture
def viewer(settings):
    from triage.enterprise.auth import authenticate

    return authenticate("demo-viewer-key", settings)
