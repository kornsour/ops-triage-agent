#!/usr/bin/env python3
"""Allowlist-enforcing HTTPS forward proxy for `ContainerSandbox`'s egress path.

Deny-by-default egress means an action container gets *no* network device at
all (`--network none`) unless the action declares a host allowlist. When it
does, the action container is instead attached only to a Docker `--internal`
network — which Docker never routes to the outside world — alongside one
instance of this proxy, which is additionally attached to a normal network
with real internet access. That is the only path out: the action container
cannot reach anything the proxy does not forward, and this proxy forwards
only `CONNECT` to a host:port on the allowlist. Everything else gets a plain
403 and the connection is closed.

Stdlib only, no dependencies — this is trusted infrastructure (not sandboxed
itself), but it stays tiny and auditable on purpose.

Env:
  TRIAGE_SANDBOX_ALLOWED_HOSTS  comma-separated "host" or "host:port" entries
                                (port defaults to 443, since this proxies
                                CONNECT tunnels — i.e. TLS — not plaintext
                                HTTP)
  TRIAGE_SANDBOX_PROXY_PORT     listen port (default 8080)
"""

from __future__ import annotations

import os
import socket
import socketserver
import sys
import threading


def _parse_allowlist(raw: str) -> set[tuple[str, int]]:
    out: set[tuple[str, int]] = set()
    for entry in raw.split(","):
        entry = entry.strip()
        if not entry:
            continue
        host, _, port = entry.partition(":")
        out.add((host.strip().lower(), int(port) if port else 443))
    return out


ALLOWED = _parse_allowlist(os.environ.get("TRIAGE_SANDBOX_ALLOWED_HOSTS", ""))
LISTEN_PORT = int(os.environ.get("TRIAGE_SANDBOX_PROXY_PORT", "8080"))
_BUF = 65536


def _pump(src: socket.socket, dst: socket.socket) -> None:
    try:
        while True:
            chunk = src.recv(_BUF)
            if not chunk:
                break
            dst.sendall(chunk)
    except OSError:
        pass
    finally:
        for s in (src, dst):
            try:
                s.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass


class ConnectHandler(socketserver.StreamRequestHandler):
    def handle(self) -> None:
        try:
            request_line = self.rfile.readline(8192).decode("latin-1").strip()
        except OSError:
            return
        if not request_line:
            return
        parts = request_line.split()
        # Drain headers regardless of outcome, so the client's write doesn't hang.
        while True:
            line = self.rfile.readline(8192)
            if not line or line in (b"\r\n", b"\n"):
                break

        if len(parts) != 3 or parts[0] != "CONNECT":
            self._deny(f"unsupported request {request_line!r} (only CONNECT is proxied)")
            return

        target = parts[1]
        host, _, port_s = target.partition(":")
        port = int(port_s) if port_s else 443
        if (host.lower(), port) not in ALLOWED:
            self._deny(f"{host}:{port} is not on this action's egress allowlist")
            return

        try:
            upstream = socket.create_connection((host, port), timeout=5)
        except OSError as exc:
            self._deny(f"upstream connect to {host}:{port} failed: {exc}")
            return

        self.connection.sendall(b"HTTP/1.1 200 Connection Established\r\n\r\n")
        t = threading.Thread(target=_pump, args=(upstream, self.connection), daemon=True)
        t.start()
        _pump(self.connection, upstream)
        t.join(timeout=2)

    def _deny(self, reason: str) -> None:
        print(f"denied: {reason}", file=sys.stderr, flush=True)
        try:
            self.connection.sendall(b"HTTP/1.1 403 Forbidden\r\n\r\n")
        except OSError:
            pass


class Server(socketserver.ThreadingMixIn, socketserver.TCPServer):
    daemon_threads = True
    allow_reuse_address = True


def main() -> int:
    with Server(("0.0.0.0", LISTEN_PORT), ConnectHandler) as server:  # noqa: S104 - proxy must listen on all interfaces to be reachable from the sandbox network
        print(f"sandbox egress proxy listening on :{LISTEN_PORT}, allowlist={sorted(ALLOWED)}",
              file=sys.stderr, flush=True)
        server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
