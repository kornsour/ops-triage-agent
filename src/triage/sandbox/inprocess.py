"""The trivial `Sandbox`: calls the effect directly, in this process.

This is what `make demo` and the offline test suite run by default -- no
container runtime, no extra dependency, so the zero-dependency story
survives (see docs/architecture-decision-record.md ADR-001 and ADR-010). It
still enforces the wall-clock timeout, so the interface's contract holds
end-to-end even without a real isolation boundary underneath it -- but it
provides *no* isolation: a hostile action here really can read the host
filesystem or call out over the real network, exactly as `ACTION_EFFECTS`
always could. Use `ContainerSandbox` when that matters.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from typing import Any

from triage.sandbox.base import Sandbox, SandboxEffectError, SandboxResult, SandboxStatus
from triage.sandbox.effects import PURE_ACTION_EFFECTS


class InProcessSandbox(Sandbox):
    def __init__(self, effects: dict[str, Callable[..., dict[str, Any]]] | None = None) -> None:
        self._effects = effects if effects is not None else PURE_ACTION_EFFECTS

    def run(self, *, action: str, args: dict[str, Any], timeout_s: float) -> SandboxResult:
        fn = self._effects.get(action)
        if fn is None:
            return SandboxResult(status=SandboxStatus.DENIED,
                                 error=f"unknown action {action!r}")

        box: dict[str, Any] = {}

        def target() -> None:
            try:
                box["output"] = fn(**args)
            except Exception as exc:  # noqa: BLE001 - re-raised on the caller's
                # thread below; caught here only so a failing effect can't
                # kill this worker thread silently.
                box["exc"] = exc

        start = time.monotonic()
        # A plain daemon thread, not a `ThreadPoolExecutor` context manager:
        # the latter blocks on `__exit__` until the submitted work finishes,
        # which would defeat giving up at `timeout_s` for an effect that
        # never returns. A daemon thread lets the caller move on; the thread
        # itself is reclaimed at process exit rather than joined.
        worker = threading.Thread(target=target, name=f"sandbox-inprocess-{action}", daemon=True)
        worker.start()
        worker.join(timeout=timeout_s)
        duration_ms = (time.monotonic() - start) * 1000

        if worker.is_alive():
            return SandboxResult(
                status=SandboxStatus.TIMED_OUT,
                error=f"exceeded {timeout_s}s (in-process: not actually killed, just abandoned)",
                duration_ms=duration_ms,
            )
        if "exc" in box:
            exc = box["exc"]
            raise SandboxEffectError(action, str(exc), kind=type(exc).__name__) from exc
        return SandboxResult(status=SandboxStatus.COMPLETED, output=box.get("output"),
                             duration_ms=duration_ms)
