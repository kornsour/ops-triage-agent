"""ActionExecutor-level tests for the rate limiter.

`TokenBucket` itself is covered in isolation in test_enterprise.py; these
tests exercise it through `ActionExecutor.request`, where the bug in #10
actually lived — one shared bucket meant one principal's traffic could
exhaust another's allowance.
"""

from __future__ import annotations

import pytest

from triage.agent.actions import ActionExecutor
from triage.data.db import TicketDB
from triage.enterprise.approvals import ApprovalStore
from triage.enterprise.audit import AuditLog
from triage.enterprise.ratelimit import RateLimitExceeded


@pytest.fixture
def executor(settings):
    db = TicketDB(settings.db_path)
    audit = AuditLog(settings.audit_path)
    approvals = ApprovalStore(settings.db_path)
    return ActionExecutor(db, audit, approvals)


def _close_ticket(executor, principal, tag):
    # Distinct args per call so idempotency replay doesn't mask whether the
    # rate limiter itself let the call through.
    return executor.request(
        run_id=tag, principal=principal, action="close_ticket",
        args={"ticket_id": f"TCK-{tag}"},
    )


def test_rate_limit_is_isolated_per_principal(executor, operator, admin, settings):
    capacity = settings.rate_limit_per_min
    assert capacity >= 1

    # Exhaust the operator's own bucket.
    for i in range(capacity):
        result = _close_ticket(executor, operator, f"op-{i}")
        assert result["status"] == "executed"
    with pytest.raises(RateLimitExceeded):
        _close_ticket(executor, operator, "op-over")

    # The admin's allowance is untouched by the operator's traffic.
    admin_result = _close_ticket(executor, admin, "admin-0")
    assert admin_result["status"] == "executed"

    # ...and the operator is still refused, independent of the admin call.
    with pytest.raises(RateLimitExceeded):
        _close_ticket(executor, operator, "op-still-over")


def test_buckets_are_pre_seeded_from_configured_api_keys(executor, settings):
    assert set(executor.buckets) == set(settings.parsed_api_keys())
