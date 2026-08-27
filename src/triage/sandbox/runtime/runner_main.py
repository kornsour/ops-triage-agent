#!/usr/bin/env python3
"""Container entrypoint for `ContainerSandbox`.

Runs *inside* the sandboxed container, as the non-root, capability-dropped
user with a read-only root filesystem and (by default) no network device at
all. Stdlib only — the image is a stock, unmodified Python base; nothing is
installed into it.

Protocol (the "explicit channel" the boundary passes inputs/outputs over):
  input  -- one JSON object read from a fixed, read-only bind-mounted file,
            /sandbox/request.json: {"action": str, "args": {...}}. A file
            rather than stdin so the host side never needs to attach or pipe
            a live stream into the container -- the whole input is written
            once, atomically, before the container starts.
  stdout -- one JSON object, and nothing else:
              {"output": {...}}                on success
              {"error": "...", "kind": "..."}   on failure
  exit code:
    0  success
    2  unknown action (rejected before the effect ever ran)
    3  the effect itself raised — this is what a hostile probe (denied file
       read, denied network call) looks like: the OS-level boundary (non-root
       user, read-only rootfs, dropped capabilities, `--network none`/an
       unlisted host) turns the attempt into a plain Python exception here,
       which is caught, reported, and turned into a clean process exit
       rather than a crash dump on stderr.

Anything else non-zero, or the process not exiting at all, is *not* this
script's doing — that is `ContainerSandbox` on the host side classifying a
resource-limit kill (OOM, pids-limit), a seccomp denial (SIGSYS), or a
wall-clock timeout it enforced itself.
"""

from __future__ import annotations

import json
import sys

sys.path.insert(0, "/sandbox")

from effects import PURE_ACTION_EFFECTS  # noqa: E402

REQUEST_PATH = "/sandbox/request.json"


def main() -> int:
    try:
        with open(REQUEST_PATH, encoding="utf-8") as fh:
            request = json.loads(fh.read() or "{}")
    except (OSError, json.JSONDecodeError) as exc:
        print(json.dumps({"error": f"malformed or missing request: {exc}", "kind": "protocol"}))
        return 2

    action = request.get("action")
    args = request.get("args") or {}
    fn = PURE_ACTION_EFFECTS.get(action)
    if fn is None:
        print(json.dumps({"error": f"unknown action {action!r}", "kind": "unknown_action"}))
        return 2

    try:
        output = fn(**args)
    except Exception as exc:  # noqa: BLE001 - deliberately broad: this boundary
        # reports *any* failure of the untrusted-composed call back over the
        # explicit channel rather than letting it become an unhandled
        # traceback on stderr.
        print(json.dumps({"error": str(exc), "kind": type(exc).__name__}))
        return 3

    print(json.dumps({"output": output}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
