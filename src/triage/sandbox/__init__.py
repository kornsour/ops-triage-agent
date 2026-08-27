"""Execution boundary for guarded-action effects.

Approval (see `triage.enterprise.approvals`) decides *whether* an action may
run. This package decides *how much damage a wrong yes can do*: every
approved action's effect is invoked through a small `Sandbox` interface
rather than called directly, so the runtime that actually executes it —
same-process today, a locked-down container tomorrow — is a config choice,
not a rewrite. See docs/sandbox.md for the full design and
docs/architecture-decision-record.md ADR-010.
"""

from __future__ import annotations

from triage.sandbox.base import (
    Sandbox,
    SandboxContainmentError,
    SandboxEffectError,
    SandboxResult,
    SandboxStatus,
)
from triage.sandbox.container import ContainerSandbox, docker_available
from triage.sandbox.effects import PURE_ACTION_EFFECTS
from triage.sandbox.factory import build_sandbox
from triage.sandbox.inprocess import InProcessSandbox

__all__ = [
    "PURE_ACTION_EFFECTS",
    "ContainerSandbox",
    "InProcessSandbox",
    "Sandbox",
    "SandboxContainmentError",
    "SandboxEffectError",
    "SandboxResult",
    "SandboxStatus",
    "build_sandbox",
    "docker_available",
]
