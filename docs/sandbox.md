# The Sandbox: an execution boundary for approved actions

Approval (`triage.enterprise.approvals`, see also ADR-002/003) decides *whether* a
guarded action runs — auth, rate limiting, idempotency, risk-tiered human approval,
all before anything happens. It says nothing about *where* the action then runs.
Once approved, `reset_password` / `grant_access` / `escalate` / `post_reply` /
`close_ticket` executed in the same process as the agent, with that process's
filesystem, network, and credentials. For this repo's simulated actions (a local
SQLite ticket store standing in for the real IdP/ticketing system) that was
contained by construction. It stops being contained the moment an action shells
out, calls a real downstream service, or runs anything the model had a hand in
composing — which is exactly the direction a real deployment of this system goes.

This document describes the boundary this repo now draws around that execution,
under `src/triage/sandbox/`.

## The interface

```python
class Sandbox(ABC):
    def run(self, *, action: str, args: dict[str, Any], timeout_s: float) -> SandboxResult:
        ...
```

Every implementation receives only `action` and its JSON-serializable `args` —
never a database handle, a file, or any other shared state — and returns a
`SandboxResult` over that same explicit channel:

```python
class SandboxStatus(StrEnum):
    COMPLETED = "completed"   # ran to completion inside the boundary
    TIMED_OUT = "timed_out"   # exceeded its wall-clock budget
    KILLED    = "killed"      # terminated for a resource limit / security policy
    DENIED    = "denied"      # refused before it ever ran
```

A completed run's own business logic can still fail — a hostile probe's file read
or network call getting refused by the OS, say — and that surfaces as a plain
`SandboxEffectError` exception, exactly mirroring how the original in-process call
already behaved (an exception the caller's existing `retry()` wrapper already knew
how to handle). `SandboxStatus` is reserved for the boundary's own outcome: did the
runtime that was supposed to produce an answer actually get to run one to
completion. That is what `ActionExecutor` audits as a first-class, security-relevant
event distinct from a business error — see "Wiring into `ActionExecutor`" below.

Two implementations exist:

- **`InProcessSandbox`** — the trivial one. Calls the effect directly, in this
  process, on a daemon worker thread so a wall-clock timeout can still be enforced
  (the thread is simply abandoned on timeout — this is *not* isolation, and the
  docstring says so). This is the default, so `make demo`, the offline test suite,
  and every environment without Docker installed keep working exactly as before —
  the interface landed without forcing a runtime dependency on anyone.
- **`ContainerSandbox`** — Docker-backed. Each call gets its own short-lived
  container.

## `ContainerSandbox`

Per action container:

| Control | Mechanism |
|---|---|
| Read-only root filesystem | `--read-only` + a small `noexec,nosuid` tmpfs for `/tmp` |
| Non-root user | `--user 65534:65534` (`nobody`) |
| No ambient credentials | nothing is mounted or set in the environment beyond the two trusted script files and (for the allowlisted-egress path) a proxy URL |
| Dropped capabilities | `--cap-drop=ALL`, `--security-opt no-new-privileges` |
| Seccomp | `runtime/seccomp-profile.json` — see below |
| CPU / memory / PID limits | `--cpus`, `--memory`, `--pids-limit` |
| Wall-clock timeout | enforced host-side (`subprocess.run(..., timeout=...)`), with a `docker kill` fallback if the container doesn't exit on its own |
| Egress | deny-by-default — see below |

**Explicit channel, not shared state.** The action's args are written to a
throwaway file and bind-mounted read-only into the container at a fixed path
(`/sandbox/request.json`); the container's *only* output is one JSON object on
stdout. Nothing else about the host — no ticket DB, no other filesystem path, no
credential — is reachable from inside. `runtime/runner_main.py` is the entrypoint
that speaks this protocol; `runtime/effects.py` (the same file `InProcessSandbox`
imports directly — one source of truth) is bind-mounted alongside it and holds the
actual business logic for each action.

The one action with genuine host-side state, `close_ticket` (marks a ticket
resolved in the local SQLite store), never crosses the boundary at all — the
sandboxed effect returns a declarative `{"effect": "ticket_closed", ...}` result,
and `ActionExecutor._run_effect` applies the real database write itself, on the
trusted host side, once the sandboxed call has actually completed. The ticket DB is
host infrastructure, not something sandboxed code should ever touch directly.

**Seccomp profile.** `runtime/seccomp-profile.json` is a deny-list: default
`SCMP_ACT_ALLOW`, with an explicit `SCMP_ACT_ERRNO` block on syscalls a guarded
-action effect has no legitimate reason to call — namespace/mount manipulation
(`mount`, `unshare`, `setns`, `pivot_root`, `chroot`), kernel module loading,
`ptrace`/process-memory access, `bpf`, system-control operations (`reboot`,
`swapon`), and a few others. This is deliberately conservative rather than a full
default-deny allowlist (Docker's own default profile, ~300 lines, is one): a
denylist is small enough to author and reason about correctly by hand without
enumerating every syscall a stock Python interpreter needs, at the cost of being
weaker in principle than allowlisting. Nearly everything on this list is already
unreachable given `--cap-drop=ALL` (most of it needs `CAP_SYS_ADMIN` or similar);
blocking the syscalls too is defence in depth against a kernel bug that makes a
"dropped" capability check bypassable. Swapping in Docker's default profile (or a
generated allowlist specific to this runner) is the natural next hardening step for
a production deployment.

**Egress: deny-by-default, with a per-action allowlist.** An action with no
allowlist entry gets `--network none` — there is no network device inside the
container at all, not merely a firewalled one. An action that declares an
allowlist (`TRIAGE_SANDBOX_EGRESS_ALLOWLIST`, e.g. `reset_password=idp.example.com`)
instead runs attached to a Docker `--internal` network — a network Docker never
routes to the outside world, by design — shared with exactly one other container:
a small allowlist-enforcing HTTPS forward proxy (`runtime/proxy_main.py`, stdlib
only, ~90 lines) that is additionally attached to a normal network with real
internet access. That second attachment is what makes the proxy (and *only* the
proxy) dual-homed; the action container has no such second leg, so the proxy is the
one path out, and it forwards `CONNECT` only to hosts on that action's own
allowlist — everything else gets a 403 and the connection is closed. The action
container is pointed at the proxy via `HTTP_PROXY`/`HTTPS_PROXY`, which is a
convention its own code has to respect, but the *boundary* — whether an
unallowlisted host is reachable at all — is enforced at the network layer by the
`--internal` network having no route out, not by that convention.

## Wiring into `ActionExecutor`

`ActionExecutor` now takes a `sandbox: Sandbox | None = None` constructor argument
(defaulting to `build_sandbox(get_settings())`, which honors `TRIAGE_SANDBOX_MODE`
and transparently falls back to `InProcessSandbox` — logging that it did — if
`container` mode is requested but Docker isn't actually reachable). `_run_effect`
routes every action through it instead of calling the effect bare:

- A `SandboxStatus.COMPLETED` result flows through exactly as before.
- Anything else (`TIMED_OUT` / `KILLED` / `DENIED`) raises `SandboxContainmentError`
  — **not** retried (a resource-limit kill or a timeout is a security-relevant
  event, not transient flakiness to paper over) — which `request()` /
  `execute_approved()` catch and turn into a `{"status": "contained", ...}` result,
  recorded in the existing hash-chained audit trail as `outcome="sandbox_<status>"`.
  An approval that hit a containment failure stays `approved`, not `executed`, so
  an admin can retry it once the underlying issue (e.g. daemon load) clears — see
  the next section for exactly that scenario.
- A `SandboxEffectError` (the sandboxed effect itself raised) is retried, matching
  the pre-existing "retry the flaky effect call" behavior unchanged.

## Verification status

The isolation flags above (`--read-only`, non-root user, `--cap-drop=ALL`,
`no-new-privileges`, the seccomp profile, `--memory`/`--cpus`/`--pids-limit`,
`--network none`) were smoke-tested together against a live Docker daemon during
development — a plain Python interpreter (including `threading`) starts and runs
correctly under the full flag set, confirming the seccomp profile in particular
doesn't break the runtime it's meant to constrain.

The full `ContainerSandbox.run()` path — the request-file protocol, the three
"boundary holds" cases (`tests/test_sandbox.py`: a hostile read outside the
sandbox, an un-allowlisted network call, a wall-clock timeout) and the
egress-allowlist proxy — is implemented and covered by tests, but this repo's
development environment shares a Docker daemon with other concurrent work and that
daemon became unable to reliably start *any* container (not specific to this
feature — plain `docker run --rm alpine true` hung the same way) partway through
this feature's development, before every container test could be exercised live to
a clean pass. `tests/test_sandbox.py` guards its Docker-backed tests behind a real
`docker run` health probe (not just `docker version`, which answered fine even
while `docker run` was wedged) precisely because of this, so they skip cleanly
rather than hang when a daemon is in that state, and will run for real in any
environment — including CI, which runs its own unshared Docker daemon — where the
daemon is healthy. Treat the container path as implemented-and-reviewed, verified
in its core isolation mechanics, but not yet exercised end-to-end to a clean pass
in this repository's own CI; that run is the natural next step, not a redesign.

## What's out of scope here

- A production allowlist proxy would want TLS certificate pinning / SNI
  inspection rather than trusting the client's own `CONNECT` target string, plus
  rate limiting and structured logging of denied attempts.
- The seccomp profile is a hand-authored denylist, not a generated allowlist; see
  above.
- No real downstream system is integrated in this repo (every action is
  simulated), so the egress allowlist has no default entries — there is nothing
  to allowlist yet. A real deployment fills in
  `TRIAGE_SANDBOX_EGRESS_ALLOWLIST` per the action that needs it (e.g. the actual
  identity provider host for `reset_password`).
