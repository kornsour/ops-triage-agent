"""The `Sandbox` interface and the small vocabulary every implementation shares.

Approval decides *if* an action runs (`triage.enterprise.approvals`); a
`Sandbox` decides *how much damage a wrong yes can do* by drawing the
execution boundary around the effect itself. Every implementation receives
only `(action, args)` -- JSON-serializable, nothing else -- and returns a
`SandboxResult` over that same explicit channel. No database handle, no
shared filesystem, no ambient credentials cross the boundary either way.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class SandboxStatus(StrEnum):
    """The isolation-boundary outcome of one sandboxed call.

    This is deliberately a *small* vocabulary -- just enough to answer "did
    the boundary hold, and if not, how": the action ran to completion inside
    the boundary (`COMPLETED`; its own business logic may still have failed,
    see `SandboxEffectError`), the boundary gave up waiting and tore the
    runtime down (`TIMED_OUT`), the runtime was forcibly terminated for
    exceeding a resource limit or violating a security policy before either
    of those (`KILLED`), or the call was refused before anything ran at all
    (`DENIED` -- an unregistered action, or no sandbox runtime available).
    """

    COMPLETED = "completed"
    TIMED_OUT = "timed_out"
    KILLED = "killed"
    DENIED = "denied"


@dataclass(frozen=True)
class SandboxResult:
    status: SandboxStatus
    output: dict[str, Any] | None = None
    error: str | None = None
    duration_ms: float = 0.0
    # Free-form, implementation-specific bookkeeping about *how* the call
    # ran (container id, exit code, image) -- never data that crossed the
    # boundary itself. Safe to fold straight into an audit entry's metadata.
    detail: dict[str, Any] = field(default_factory=dict)


class SandboxEffectError(Exception):
    """The sandboxed effect itself failed -- a business-logic exception, or a
    hostile/misbehaving action's file or network access being refused by the
    boundary (a denied read surfaces here as a plain `PermissionError`-style
    message, not as a special `SandboxResult`; the boundary held, the call
    simply failed the way any well-contained failure should).

    Distinct from a containment failure (`SandboxResult.status !=
    COMPLETED`): this means the runtime *did* run the call end-to-end and it
    raised, mirroring how `ACTION_EFFECTS` already behaves today so
    `ActionExecutor`'s existing retry-on-exception path keeps working
    unchanged for both sandbox implementations.
    """

    def __init__(self, action: str, message: str, *, kind: str = "") -> None:
        super().__init__(f"action {action!r} failed inside the sandbox: {message}")
        self.action = action
        self.message = message
        self.kind = kind


class SandboxContainmentError(Exception):
    """The isolation boundary itself is why an action didn't produce output:
    it timed out, was killed for exceeding a resource limit or violating a
    security policy, or was denied before it ever ran.

    Carries the terminal `SandboxResult` (`status != COMPLETED`) so a caller
    can audit exactly what happened -- see `ActionExecutor._run_effect`.
    """

    def __init__(self, action: str, result: SandboxResult) -> None:
        detail = f" ({result.error})" if result.error else ""
        super().__init__(f"action {action!r} was not completed by the sandbox: "
                         f"{result.status.value}{detail}")
        self.action = action
        self.result = result


class Sandbox(ABC):
    """Execution boundary for guarded-action effects."""

    @abstractmethod
    def run(self, *, action: str, args: dict[str, Any], timeout_s: float) -> SandboxResult:
        """Run `action(**args)` inside this boundary and return the outcome.

        Raises `SandboxEffectError` if the call ran but the effect itself
        failed. Never raises for a containment failure -- that comes back as
        a `SandboxResult` with `status != COMPLETED` so the caller can audit
        it as a first-class outcome rather than catch an exception.
        """
