"""Hostile probe for tests/test_sandbox.py: never return, to exercise the
wall-clock timeout and `docker kill` fallback in `ContainerSandbox._invoke`.
"""

from __future__ import annotations

import time
from typing import Any


def pure_nap(**_: Any) -> dict[str, Any]:
    time.sleep(9999)
    return {}  # pragma: no cover - never reached


PURE_ACTION_EFFECTS = {"nap": pure_nap}
