import threading

import pytest

from triage.enterprise.audit import AuditLog
from triage.enterprise.auth import AuthError, authenticate, require_role
from triage.enterprise.idempotency import (
    IdempotencyStore,
    InMemoryIdempotencyStore,
    make_key,
)
from triage.enterprise.ratelimit import RateLimitExceeded, TokenBucket
from triage.enterprise.retry import retry


def test_role_hierarchy(settings):
    op = authenticate("demo-operator-key", settings)
    assert op.has_role("viewer") and op.has_role("operator")
    assert not op.has_role("admin")
    require_role(authenticate("demo-admin-key", settings), "admin")
    with pytest.raises(AuthError):
        require_role(op, "admin")


def test_auth_rejects_bad_key(settings):
    with pytest.raises(AuthError):
        authenticate("nope", settings)
    with pytest.raises(AuthError):
        authenticate(None, settings)


def test_audit_chain_verifies_and_detects_tampering(tmp_path):
    log = AuditLog(tmp_path / "a.jsonl")
    log.record(actor="op", action="reset_password", target="x", outcome="executed")
    log.record(actor="admin", action="grant_access", target="y", outcome="executed")
    ok, msg = log.verify()
    assert ok, msg

    # Tamper with the first line; chain must break.
    lines = (tmp_path / "a.jsonl").read_text().splitlines()
    lines[0] = lines[0].replace('"executed"', '"denied"')
    (tmp_path / "a.jsonl").write_text("\n".join(lines) + "\n")
    ok, msg = log.verify()
    assert not ok
    assert "tampered" in msg or "chain" in msg


def test_audit_concurrent_writers_keep_chain_intact(tmp_path):
    # Simulates two separate processes on the same audit path (e.g. the API
    # server and an MCP server, per docs/reference-architecture.md) by using
    # two independent AuditLog instances — each with its own in-memory tail
    # cache — writing from separate threads at the same time.
    path = tmp_path / "concurrent.jsonl"
    log_a = AuditLog(path)
    log_b = AuditLog(path)
    n = 40
    errors: list[Exception] = []

    def write_many(log: AuditLog, actor: str) -> None:
        try:
            for i in range(n):
                log.record(actor=actor, action="probe", target=str(i), outcome="executed")
        except Exception as exc:  # pragma: no cover - surfaced via errors list
            errors.append(exc)

    t1 = threading.Thread(target=write_many, args=(log_a, "writer-a"))
    t2 = threading.Thread(target=write_many, args=(log_b, "writer-b"))
    t1.start()
    t2.start()
    t1.join()
    t2.join()

    assert not errors
    entries = log_a.entries()
    assert len(entries) == 2 * n
    ok, msg = log_a.verify()
    assert ok, msg


def test_audit_chain_detects_tail_truncation(tmp_path):
    log = AuditLog(tmp_path / "a.jsonl")
    log.record(actor="op", action="reset_password", target="x", outcome="executed")
    log.record(actor="op", action="close_ticket", target="y", outcome="executed")
    log.record(actor="admin", action="grant_access", target="z", outcome="executed")
    ok, msg = log.verify()
    assert ok, msg

    # Drop the last line. The remaining prefix is still internally
    # consistent (seq 0..1, correct prev_hash/hash chain) — only the head
    # anchor can tell the log is shorter than it should be.
    log_file = tmp_path / "a.jsonl"
    lines = log_file.read_text().splitlines()
    log_file.write_text("\n".join(lines[:-1]) + "\n")

    ok, msg = log.verify()
    assert not ok
    assert "truncated" in msg


def test_audit_chain_normal_append_still_verifies(tmp_path):
    log = AuditLog(tmp_path / "a.jsonl")
    for i in range(5):
        log.record(actor="op", action="post_reply", target=f"t{i}", outcome="executed")
    ok, msg = log.verify()
    assert ok, msg


def test_idempotency_runs_once():
    store = InMemoryIdempotencyStore()
    calls = []

    def fn():
        calls.append(1)
        return "result"

    key = make_key("reset_password", {"email": "a@b.com"})
    r1, replayed1 = store.run_once(key, fn)
    r2, replayed2 = store.run_once(key, fn)
    assert r1 == r2 == "result"
    assert replayed1 is False and replayed2 is True
    assert len(calls) == 1


def test_idempotency_store_persists_across_instances(tmp_path):
    # A fresh `IdempotencyStore` built against the same db_path — modeling a
    # process restart, or a second replica behind a load balancer — must see
    # results a prior instance already stored, not re-run the effect.
    db_path = tmp_path / "triage.db"
    key = make_key("close_ticket", {"ticket_id": "TCK-1"})

    store_a = IdempotencyStore(db_path)
    calls = []

    def fn():
        calls.append(1)
        return {"ok": True}

    result_a, replayed_a = store_a.run_once(key, fn)
    assert result_a == {"ok": True}
    assert replayed_a is False

    store_b = IdempotencyStore(db_path)
    assert store_b.seen(key)
    assert store_b.get(key) == {"ok": True}
    result_b, replayed_b = store_b.run_once(key, fn)
    assert result_b == {"ok": True}
    assert replayed_b is True
    assert len(calls) == 1


def test_token_bucket_limits():
    bucket = TokenBucket(capacity=2, refill_per_sec=0.0)
    assert bucket.allow(now=0.0)
    assert bucket.allow(now=0.0)
    assert not bucket.allow(now=0.0)
    with pytest.raises(RateLimitExceeded):
        bucket.acquire(now=0.0)


def test_token_bucket_refills():
    bucket = TokenBucket(capacity=1, refill_per_sec=1.0)
    assert bucket.allow(now=0.0)
    assert not bucket.allow(now=0.0)
    assert bucket.allow(now=1.0)  # one token refilled after a second


def test_retry_succeeds_after_transient_failures():
    attempts = {"n": 0}

    def flaky():
        attempts["n"] += 1
        if attempts["n"] < 3:
            raise ConnectionError("transient")
        return "ok"

    assert retry(flaky, attempts=3) == "ok"
    assert attempts["n"] == 3


def test_retry_gives_up():
    def always_fails():
        raise ValueError("nope")

    with pytest.raises(ValueError):
        retry(always_fails, attempts=2)
