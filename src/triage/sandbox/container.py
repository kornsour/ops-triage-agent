"""Docker-backed `Sandbox`: each approved action runs in its own short-lived,
locked-down container instead of in this process.

Isolation, per container:
  - `--read-only` root filesystem + a small `noexec` tmpfs for `/tmp`
  - a non-root, unprivileged user (65534, i.e. `nobody`)
  - every Linux capability dropped, `no-new-privileges`
  - a seccomp profile (runtime/seccomp-profile.json)
  - CPU / memory / PID limits
  - a wall-clock timeout enforced from the host side, with a `docker kill`
    fallback if the runtime doesn't exit on its own

Egress is deny-by-default: with no allowlist configured for the action, the
container gets `--network none` -- no network device exists inside it at
all. An action with a configured allowlist instead runs on a Docker
`--internal` network (which Docker never routes to the outside world)
alongside a small allowlist-enforcing proxy that is the only thing on that
network with a second leg out to the internet -- see runtime/proxy_main.py
and docs/sandbox.md for the full design and its verification status.

Inputs and outputs cross the boundary over an explicit channel only: the
action's JSON args are written to a throwaway file bind-mounted read-only
into the container at a fixed path, and the container's only output is one
JSON object on stdout (runtime/runner_main.py). No ticket DB, no other host
filesystem state, and no credential ever crosses in either direction.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import time
import uuid
from pathlib import Path
from typing import Any

from triage.sandbox.base import Sandbox, SandboxEffectError, SandboxResult, SandboxStatus

_HERE = Path(__file__).resolve().parent
RUNTIME_DIR = _HERE / "runtime"
DEFAULT_EFFECTS_PATH = _HERE / "effects.py"
DEFAULT_RUNNER_PATH = RUNTIME_DIR / "runner_main.py"
DEFAULT_PROXY_PATH = RUNTIME_DIR / "proxy_main.py"
DEFAULT_SECCOMP_PROFILE = RUNTIME_DIR / "seccomp-profile.json"
DEFAULT_IMAGE = "python:3.12-alpine"

# Exit codes emitted by runtime/runner_main.py -- see its docstring for the
# full protocol. Anything outside this set (137 = SIGKILL/OOM, 143 =
# SIGTERM, 159 = 128+SIGSYS from a seccomp denial, ...) means the *runtime*
# was terminated before the script itself could report an outcome.
_EXIT_UNKNOWN_ACTION = 2
_EXIT_EFFECT_FAILED = 3


def docker_available(docker_bin: str = "docker") -> bool:
    """Fast, bounded check -- never hangs even if the daemon is unresponsive.

    Used both to gate `ContainerSandbox` tests and, in principle, to decide
    at startup whether `TRIAGE_SANDBOX_MODE=container` can actually be
    honored (`ActionExecutor` falls back to `InProcessSandbox` otherwise --
    see `triage.config`).
    """
    if shutil.which(docker_bin) is None:
        return False
    try:
        proc = subprocess.run(
            [docker_bin, "version", "--format", "{{.Server.Version}}"],
            capture_output=True, timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return proc.returncode == 0


class ContainerSandbox(Sandbox):
    def __init__(
        self,
        *,
        image: str = DEFAULT_IMAGE,
        memory_mb: int = 64,
        cpus: float = 0.5,
        pids_limit: int = 64,
        seccomp_profile: Path | str = DEFAULT_SECCOMP_PROFILE,
        egress_allowlist: dict[str, list[str]] | None = None,
        docker_bin: str = "docker",
        effects_path: Path | str = DEFAULT_EFFECTS_PATH,
        runner_path: Path | str = DEFAULT_RUNNER_PATH,
        proxy_path: Path | str = DEFAULT_PROXY_PATH,
        proxy_image: str | None = None,
    ) -> None:
        self.image = image
        self.memory_mb = memory_mb
        self.cpus = cpus
        self.pids_limit = pids_limit
        self.seccomp_profile = Path(seccomp_profile)
        # action -> ["host" | "host:port", ...] -- deny-by-default means an
        # action absent from this mapping (or mapped to an empty list) gets
        # no network device at all. See docs/sandbox.md for how a real
        # deployment declares e.g. `reset_password -> idp.example.com`.
        self.egress_allowlist = egress_allowlist or {}
        self.docker_bin = docker_bin
        self.effects_path = Path(effects_path)
        self.runner_path = Path(runner_path)
        self.proxy_path = Path(proxy_path)
        self.proxy_image = proxy_image or image

    # -- Sandbox interface ------------------------------------------------

    def run(self, *, action: str, args: dict[str, Any], timeout_s: float) -> SandboxResult:
        # No local pre-check against a registry: `effects_path` is
        # per-instance (tests point it at fixture modules with entirely
        # different action names), so whether `action` is known is the
        # runtime's call, not this process's -- `runtime/runner_main.py`
        # reports an unknown action as a normal DENIED outcome (exit 2, see
        # `_invoke`) rather than this ever needing its own copy of the
        # registry to stay in sync with.
        hosts = self.egress_allowlist.get(action) or []
        if hosts:
            return self._run_with_egress(action, args, timeout_s, hosts)
        return self._run_isolated(action, args, timeout_s)

    # -- the two run paths --------------------------------------------------

    def _run_isolated(self, action: str, args: dict[str, Any], timeout_s: float) -> SandboxResult:
        with tempfile.TemporaryDirectory(prefix="triage-sandbox-") as tmp:
            request_path = self._write_request(tmp, action, args)
            name = self._container_name(action)
            cmd = (
                self._base_run_args(name, network="none", request_path=request_path)
                + [self.image, "python3", "runner_main.py"]
            )
            return self._invoke(action, name, cmd, timeout_s)

    def _run_with_egress(
        self, action: str, args: dict[str, Any], timeout_s: float, hosts: list[str],
    ) -> SandboxResult:
        run_id = uuid.uuid4().hex[:10]
        net_name = f"triage-sandbox-net-{run_id}"
        proxy_name = f"triage-sandbox-proxy-{run_id}"
        action_name = f"triage-sandbox-{run_id}"

        with tempfile.TemporaryDirectory(prefix="triage-sandbox-") as tmp:
            request_path = self._write_request(tmp, action, args)
            try:
                self._docker(["network", "create", "--internal", net_name], timeout=15)
            except (RuntimeError, subprocess.TimeoutExpired) as exc:
                return SandboxResult(status=SandboxStatus.DENIED,
                                     error=f"could not provision an isolated network: {exc}")
            try:
                try:
                    self._start_proxy(proxy_name, net_name, hosts)
                except (RuntimeError, subprocess.TimeoutExpired) as exc:
                    return SandboxResult(status=SandboxStatus.DENIED,
                                         error=f"could not start the egress proxy: {exc}")
                try:
                    proxy_ip = self._container_ip(proxy_name, net_name)
                except (RuntimeError, subprocess.TimeoutExpired) as exc:
                    return SandboxResult(status=SandboxStatus.DENIED,
                                         error=f"could not address the egress proxy: {exc}")

                cmd = (
                    self._base_run_args(action_name, network=net_name, request_path=request_path)
                    + [
                        "-e", f"HTTP_PROXY=http://{proxy_ip}:8080",
                        "-e", f"HTTPS_PROXY=http://{proxy_ip}:8080",
                        "-e", "NO_PROXY=",
                        self.image, "python3", "runner_main.py",
                    ]
                )
                return self._invoke(action, action_name, cmd, timeout_s)
            finally:
                self._docker(["rm", "-f", proxy_name], timeout=15, check=False)
                self._docker(["network", "rm", net_name], timeout=15, check=False)

    def _start_proxy(self, proxy_name: str, net_name: str, hosts: list[str]) -> None:
        self._docker(
            [
                "run", "-d", "--rm", "--name", proxy_name,
                "--network", net_name,
                "--read-only", "--tmpfs", "/tmp:rw,noexec,nosuid,size=8m",
                "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
                "--memory", "32m", "--pids-limit", "32",
                "-e", f"TRIAGE_SANDBOX_ALLOWED_HOSTS={','.join(hosts)}",
                "-v", f"{self.proxy_path}:/sandbox/proxy_main.py:ro",
                "-w", "/sandbox",
                self.proxy_image, "python3", "proxy_main.py",
            ],
            timeout=20,
        )
        # Second network leg: real egress, so the proxy can actually reach
        # an allowlisted host. `--internal` networks are never routed
        # outside, so this join is what makes the proxy (and only the
        # proxy) dual-homed -- the action container, attached only to
        # `net_name`, has no such second leg.
        self._docker(["network", "connect", "bridge", proxy_name], timeout=15)

    # -- shared plumbing ----------------------------------------------------

    def _write_request(self, tmp_dir: str, action: str, args: dict[str, Any]) -> Path:
        path = Path(tmp_dir) / "request.json"
        path.write_text(json.dumps({"action": action, "args": args}))
        return path

    def _container_name(self, action: str) -> str:
        safe_action = "".join(c if c.isalnum() else "-" for c in action)
        return f"triage-sandbox-{safe_action}-{uuid.uuid4().hex[:10]}"

    def _base_run_args(self, name: str, *, network: str, request_path: Path) -> list[str]:
        return [
            self.docker_bin, "run", "--rm",
            "--name", name,
            "--network", network,
            "--read-only",
            "--tmpfs", "/tmp:rw,noexec,nosuid,size=16m",
            "--user", "65534:65534",
            "--cap-drop", "ALL",
            "--security-opt", "no-new-privileges",
            "--security-opt", f"seccomp={self.seccomp_profile}",
            "--memory", f"{self.memory_mb}m",
            "--pids-limit", str(self.pids_limit),
            "--cpus", str(self.cpus),
            "-v", f"{self.effects_path}:/sandbox/effects.py:ro",
            "-v", f"{self.runner_path}:/sandbox/runner_main.py:ro",
            "-v", f"{request_path}:/sandbox/request.json:ro",
            "-w", "/sandbox",
        ]

    def _invoke(
        self, action: str, container_name: str, cmd: list[str], timeout_s: float,
    ) -> SandboxResult:
        start = time.monotonic()
        try:
            proc = subprocess.run(cmd, capture_output=True, timeout=timeout_s, text=True)
        except subprocess.TimeoutExpired:
            self._kill(container_name)
            return SandboxResult(
                status=SandboxStatus.TIMED_OUT, error=f"exceeded {timeout_s}s",
                duration_ms=(time.monotonic() - start) * 1000,
                detail={"container": container_name},
            )
        duration_ms = (time.monotonic() - start) * 1000
        detail: dict[str, Any] = {"container": container_name, "exit_code": proc.returncode}

        if proc.returncode == 0:
            try:
                payload = json.loads(proc.stdout)
            except json.JSONDecodeError as exc:
                # The protocol promises exactly one JSON object on stdout;
                # anything else means the runtime itself misbehaved, which
                # is a containment-relevant fact, not a clean completion.
                detail["stdout"] = proc.stdout[-2000:]
                return SandboxResult(status=SandboxStatus.KILLED,
                                     error=f"malformed sandbox output: {exc}",
                                     duration_ms=duration_ms, detail=detail)
            return SandboxResult(status=SandboxStatus.COMPLETED, output=payload.get("output"),
                                 duration_ms=duration_ms, detail=detail)

        if proc.returncode in (_EXIT_UNKNOWN_ACTION, _EXIT_EFFECT_FAILED):
            try:
                payload = json.loads(proc.stdout)
            except json.JSONDecodeError:
                payload = {"error": (proc.stdout or proc.stderr or "unknown failure").strip()}
            if proc.returncode == _EXIT_UNKNOWN_ACTION:
                return SandboxResult(status=SandboxStatus.DENIED,
                                     error=payload.get("error"),
                                     duration_ms=duration_ms, detail=detail)
            raise SandboxEffectError(action, payload.get("error", "effect failed"),
                                     kind=payload.get("kind", ""))

        detail["stderr"] = proc.stderr[-2000:]
        return SandboxResult(
            status=SandboxStatus.KILLED,
            error=f"container exited {proc.returncode} (resource limit or security policy)",
            duration_ms=duration_ms, detail=detail,
        )

    def _kill(self, name: str) -> None:
        try:
            subprocess.run([self.docker_bin, "kill", name], capture_output=True, timeout=10)
        except (OSError, subprocess.TimeoutExpired):
            pass

    def _container_ip(self, name: str, network: str) -> str:
        fmt = f'{{{{ (index .NetworkSettings.Networks "{network}").IPAddress }}}}'
        proc = self._docker(["inspect", "-f", fmt, name], timeout=10)
        ip = proc.stdout.strip()
        if not ip:
            raise RuntimeError(f"container {name!r} has no address on network {network!r}")
        return ip

    def _docker(
        self, args: list[str], *, timeout: float, check: bool = True,
    ) -> subprocess.CompletedProcess[str]:
        proc = subprocess.run([self.docker_bin, *args], capture_output=True,
                              timeout=timeout, text=True)
        if check and proc.returncode != 0:
            raise RuntimeError(f"`docker {' '.join(args)}` failed: {proc.stderr.strip()}")
        return proc
