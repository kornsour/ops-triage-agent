"""Tests for the `Sandbox` execution boundary.

Three groups:

  * `InProcessSandbox` -- the trivial reference implementation, always run.
  * `ActionExecutor` wiring -- a fake `Sandbox` stands in so these run
    without Docker, exercising the containment-failure path (audited,
    returned as a structured "contained" result, not retried) and the
    business-exception path (retried, matching the old behavior).
  * `ContainerSandbox` -- the boundary-holds cases the issue asks for
    directly: an action that tries to read outside its sandbox, one that
    tries an un-allowlisted network call, and one that exceeds its timeout.
    Skipped when Docker isn't reachable; see `docker_available()`.
"""

from __future__ import annotations

import subprocess
import time
from pathlib import Path
from typing import Any

import pytest

from triage.agent.actions import ActionExecutor
from triage.data.db import TicketDB
from triage.enterprise.approvals import ApprovalStore
from triage.enterprise.audit import AuditLog
from triage.enterprise.idempotency import make_key
from triage.sandbox.base import Sandbox, SandboxResult, SandboxStatus
from triage.sandbox.container import DEFAULT_RUNNER_PATH, ContainerSandbox, docker_available
from triage.sandbox.inprocess import InProcessSandbox

HOSTILE_DIR = Path(__file__).parent / "fixtures" / "sandbox_hostile"

# Generous but bounded: real live-Docker runs on an idle daemon finish in a
# couple of seconds; this only needs to be large enough that a legitimately
# completing case never gets misclassified as TIMED_OUT.
LIVE_TIMEOUT_S = 20.0


# --- InProcessSandbox --------------------------------------------------------


def test_inprocess_sandbox_completes_a_real_action():
    sandbox = InProcessSandbox()
    result = sandbox.run(action="reset_password", args={"email": "a@b.com"}, timeout_s=5)
    assert result.status is SandboxStatus.COMPLETED
    assert result.output == {
        "effect": "password_reset_link_sent", "email": "a@b.com", "lockout_cleared": True,
    }


def test_inprocess_sandbox_denies_unknown_action():
    sandbox = InProcessSandbox()
    result = sandbox.run(action="delete_universe", args={}, timeout_s=5)
    assert result.status is SandboxStatus.DENIED


def test_inprocess_sandbox_enforces_wall_clock_timeout():
    def _hangs(**_: Any) -> dict[str, Any]:
        time.sleep(5)
        return {}

    sandbox = InProcessSandbox({"hangs": _hangs})
    result = sandbox.run(action="hangs", args={}, timeout_s=0.05)
    assert result.status is SandboxStatus.TIMED_OUT


def test_inprocess_sandbox_reraises_business_exceptions():
    from triage.sandbox.base import SandboxEffectError

    def _boom(**_: Any) -> dict[str, Any]:
        raise ValueError("bad args")

    sandbox = InProcessSandbox({"boom": _boom})
    with pytest.raises(SandboxEffectError):
        sandbox.run(action="boom", args={}, timeout_s=5)


# --- ActionExecutor wiring ----------------------------------------------------


class _FakeSandbox(Sandbox):
    """A `Sandbox` whose outcome is scripted, so `ActionExecutor`'s handling
    of each `SandboxStatus` can be tested without Docker."""

    def __init__(self, result: SandboxResult) -> None:
        self.result = result
        self.calls = 0

    def run(self, *, action: str, args: dict[str, Any], timeout_s: float) -> SandboxResult:
        self.calls += 1
        return self.result


@pytest.fixture
def executor_with(settings):
    def _build(sandbox: Sandbox) -> ActionExecutor:
        db = TicketDB(settings.db_path)
        audit = AuditLog(settings.audit_path)
        approvals = ApprovalStore(settings.db_path)
        return ActionExecutor(db, audit, approvals, sandbox=sandbox, now_fn=lambda: 0.0)

    return _build


def test_default_sandbox_is_wired_and_close_ticket_updates_the_db(settings):
    db = TicketDB(settings.db_path)
    from triage.data.seed import seed

    seed(db)
    audit = AuditLog(settings.audit_path)
    approvals = ApprovalStore(settings.db_path)
    executor = ActionExecutor(db, audit, approvals, now_fn=lambda: 0.0)

    assert isinstance(executor.sandbox, InProcessSandbox)

    from triage.enterprise.auth import authenticate

    operator = authenticate("demo-operator-key", settings)
    result = executor.request(run_id="r1", principal=operator, action="close_ticket",
                              args={"ticket_id": "TCK-1001"})
    assert result["status"] == "executed"
    # The sandboxed effect itself never sees a database handle (see
    # triage.sandbox.effects) -- confirm the host-side write in
    # ActionExecutor._run_effect actually still happens.
    assert db.get_ticket("TCK-1001").status == "resolved"


def test_timed_out_sandbox_result_is_contained_not_raised(executor_with, operator):
    fake = _FakeSandbox(SandboxResult(status=SandboxStatus.TIMED_OUT, error="exceeded 10.0s"))
    executor = executor_with(fake)
    result = executor.request(run_id="r1", principal=operator, action="close_ticket",
                              args={"ticket_id": "TCK-x"})
    assert result["status"] == "contained"
    assert result["sandbox_status"] == "timed_out"
    assert fake.calls == 1  # containment failures are not retried

    entries = executor.audit.entries()
    assert entries[-1]["outcome"] == "sandbox_timed_out"
    assert entries[-1]["metadata"]["reason"] == "exceeded 10.0s"


def test_killed_sandbox_result_is_contained_and_audited(executor_with, operator):
    fake = _FakeSandbox(SandboxResult(status=SandboxStatus.KILLED, error="oom"))
    executor = executor_with(fake)
    result = executor.request(run_id="r1", principal=operator, action="escalate",
                              args={"ticket_id": "TCK-x", "team": "sre"})
    assert result["status"] == "contained"
    assert result["sandbox_status"] == "killed"
    entries = executor.audit.entries()
    assert entries[-1]["outcome"] == "sandbox_killed"


def test_containment_failure_on_execute_approved_leaves_approval_retryable(executor_with, operator, admin):
    fake = _FakeSandbox(SandboxResult(status=SandboxStatus.TIMED_OUT, error="exceeded 10.0s"))
    executor = executor_with(fake)
    # grant_access is high-risk -> always needs approval.
    req = executor.request(run_id="r1", principal=operator, action="grant_access",
                           args={"email": "a@b.com", "resource": "billing-repo"})
    assert req["status"] == "pending_approval"
    executor.approvals.decide(req["approval_id"], approve=True, decided_by=admin.name)

    result = executor.execute_approved(approval_id=req["approval_id"], principal=admin)
    assert result["status"] == "contained"

    decision = executor.approvals.get(req["approval_id"])
    assert decision.status == "approved"  # not "executed" -- an admin can retry


def test_containment_failure_does_not_poison_idempotency(executor_with, operator):
    fake = _FakeSandbox(SandboxResult(status=SandboxStatus.TIMED_OUT, error="exceeded 10.0s"))
    executor = executor_with(fake)
    args = {"ticket_id": "TCK-x"}
    first = executor.request(run_id="r1", principal=operator, action="close_ticket", args=args)
    assert first["status"] == "contained"
    # Not remembered as a successful result -- a second identical request
    # can genuinely attempt again rather than replaying a failure forever.
    assert executor.idempotency.seen(make_key("close_ticket", args)) is False


# --- ContainerSandbox: the boundary holds -------------------------------------


def _hostile_sandbox(effects_filename: str, **kwargs: Any) -> ContainerSandbox:
    # The real runner (runtime/runner_main.py) is reused unmodified -- only
    # the effects module it imports is swapped for a hostile probe, so what
    # is under test is the container boundary, not a different protocol.
    return ContainerSandbox(
        effects_path=HOSTILE_DIR / effects_filename,
        runner_path=DEFAULT_RUNNER_PATH,
        **kwargs,
    )


def _docker_can_actually_run_containers() -> bool:
    """`docker_available()` only checks that the CLI can reach the daemon
    (`docker version`), which answers even when the daemon is too wedged or
    contended to actually start a container -- as observed against a shared
    Docker Desktop instance during development of this feature (see
    docs/sandbox.md, "verification status"). Confirm with a real, minimal
    `docker run` on a bounded timeout so a stuck daemon skips these tests
    rather than burning through every per-test timeout in turn.
    """
    if not docker_available():
        return False
    try:
        proc = subprocess.run(
            ["docker", "run", "--rm", "python:3.12-alpine", "true"],
            capture_output=True, timeout=15,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return proc.returncode == 0


requires_docker = pytest.mark.skipif(
    not _docker_can_actually_run_containers(),
    reason="docker is not installed, or the daemon is unreachable/unable to actually run "
           "a container within 15s",
)


@requires_docker
def test_container_sandbox_runs_a_real_action():
    sandbox = ContainerSandbox()
    result = sandbox.run(action="escalate", args={"ticket_id": "TCK-1", "team": "sre-on-call"},
                         timeout_s=LIVE_TIMEOUT_S)
    assert result.status is SandboxStatus.COMPLETED
    assert result.output == {"effect": "escalated", "ticket_id": "TCK-1", "team": "sre-on-call"}


@requires_docker
def test_container_sandbox_denies_reading_outside_its_sandbox():
    """A hostile action tries to read /etc/shadow -- readable only by root
    and the `shadow` group on a stock image. The non-root, capability
    -dropped user this container runs as can't, so the attempt fails inside
    the boundary rather than leaking anything back out."""
    from triage.sandbox.base import SandboxEffectError

    sandbox = _hostile_sandbox("read_outside_sandbox.py")
    with pytest.raises(SandboxEffectError) as exc_info:
        sandbox.run(action="read_secret", args={}, timeout_s=LIVE_TIMEOUT_S)
    assert "permission" in str(exc_info.value).lower()


@requires_docker
def test_container_sandbox_denies_unallowlisted_network_call():
    """No allowlist is configured for this action, so it gets `--network
    none` -- no network device exists inside the container at all."""
    from triage.sandbox.base import SandboxEffectError

    sandbox = _hostile_sandbox("call_the_network.py")
    with pytest.raises(SandboxEffectError):
        sandbox.run(action="phone_home", args={}, timeout_s=LIVE_TIMEOUT_S)


@requires_docker
def test_container_sandbox_kills_on_timeout():
    sandbox = _hostile_sandbox("sleep_forever.py")
    result = sandbox.run(action="nap", args={}, timeout_s=2.0)
    assert result.status is SandboxStatus.TIMED_OUT


@requires_docker
def test_container_sandbox_denies_unknown_action():
    sandbox = ContainerSandbox()
    result = sandbox.run(action="not_a_real_action", args={}, timeout_s=LIVE_TIMEOUT_S)
    assert result.status is SandboxStatus.DENIED
