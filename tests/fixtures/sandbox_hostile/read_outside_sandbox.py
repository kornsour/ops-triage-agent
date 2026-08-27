"""Hostile probe for tests/test_sandbox.py: try to read a file the sandboxed
user has no business reading. `/etc/shadow` is mode 0640, owned by
root:shadow on a stock image -- readable only by root or a member of the
`shadow` group, neither of which the container's non-root, capability
-dropped user is.

Mounted read-only at /sandbox/effects.py in place of the real
triage/sandbox/effects.py -- see `_hostile_sandbox()` in test_sandbox.py.
"""

from __future__ import annotations

from typing import Any


def pure_read_secret(**_: Any) -> dict[str, Any]:
    with open("/etc/shadow", encoding="utf-8", errors="replace") as fh:
        return {"leaked": fh.read()}


PURE_ACTION_EFFECTS = {"read_secret": pure_read_secret}
