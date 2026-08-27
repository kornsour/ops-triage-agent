"""Hostile probe for tests/test_sandbox.py: try to reach the real network.
No allowlist is configured for this action in the test, so the container
gets `--network none` -- no network device at all -- and this should fail
before a single byte leaves the box.
"""

from __future__ import annotations

import socket
from typing import Any


def pure_phone_home(**_: Any) -> dict[str, Any]:
    with socket.create_connection(("1.1.1.1", 80), timeout=3):
        return {"connected": True}


PURE_ACTION_EFFECTS = {"phone_home": pure_phone_home}
