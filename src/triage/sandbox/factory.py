"""Build the `Sandbox` `ActionExecutor` uses by default, from config."""

from __future__ import annotations

import logging

from triage.config import Settings
from triage.observability.logging import get_logger, log_event
from triage.sandbox.base import Sandbox
from triage.sandbox.container import ContainerSandbox, docker_available
from triage.sandbox.inprocess import InProcessSandbox

logger = get_logger("triage.sandbox")


def build_sandbox(settings: Settings) -> Sandbox:
    """`TRIAGE_SANDBOX_MODE=container` asks for `ContainerSandbox`, but this
    still falls back to `InProcessSandbox` (logging that it did) if Docker
    isn't actually reachable -- so `make demo` and the offline test suite
    keep working with zero setup even when the setting is flipped on
    generally (e.g. a shared `.env`) without every environment having
    Docker.
    """
    mode = settings.sandbox_mode.strip().lower()
    if mode == "container":
        if docker_available():
            return ContainerSandbox(
                image=settings.sandbox_image,
                memory_mb=settings.sandbox_memory_mb,
                cpus=settings.sandbox_cpus,
                pids_limit=settings.sandbox_pids_limit,
                egress_allowlist=settings.parsed_sandbox_egress_allowlist(),
            )
        log_event(
            logger, logging.WARNING, "sandbox_container_unavailable",
            detail="TRIAGE_SANDBOX_MODE=container but docker is not reachable; "
                   "falling back to InProcessSandbox (no isolation)",
        )
    return InProcessSandbox()
