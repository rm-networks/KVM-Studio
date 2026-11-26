"""Unix socket server: one JSON request per connection, one JSON answer.

Request:  {"op": "iso_acl", "params": {"path": "/srv/iso/x.iso"}}
Answer:   {"ok": true, "result": {...}}
          {"ok": false, "error": "path_not_allowed", "message": "..."}

Order: parse, check the parameters' syntax, ask polkit for the peer's uid,
then check them against the system (files, libvirt, accounts), and run.
Nothing on the system is looked at before polkit said yes: a caller without
the right gets the same answer whatever the paths or VMs it names.
"""

from __future__ import annotations

import json
import logging
import os
import socket
import socketserver
import struct
import subprocess
import threading
import time
from collections import Counter
from collections.abc import Callable
from typing import Any

from .config import HelperConfig
from .errors import HelperError
from .ops import Operation, Runner, registry
from .polkit import TOOL_ENV, Peer, authorize

MAX_REQUEST = 64 * 1024
# The whole request must arrive within this time (the client sends it at once).
READ_TIMEOUT = 2
# Connections served at once, in all and per account: a connection waiting
# for a password holds one, idle ones are dropped after READ_TIMEOUT.
MAX_CONNECTIONS = 16
MAX_PER_UID = 8
TOOL_TIMEOUT = 60
# Systemd socket activation passes the listening socket as fd 3.
LISTEN_FD = 3

log = logging.getLogger("kvmstudio-helper")

Authorizer = Callable[[str, Peer], bool]


# Linux 4.13: the peer's supplementary groups as they were when it connected.
SO_PEERGROUPS = getattr(socket, "SO_PEERGROUPS", 59)
# Python reads at most 1024 bytes of a socket option: 256 groups.
MAX_GROUPS = 256


def peer_groups(sock: socket.socket) -> tuple[int, ...]:
    try:
        raw = sock.getsockopt(socket.SOL_SOCKET, SO_PEERGROUPS, 4 * MAX_GROUPS)
    except OSError:
        return ()
    return struct.unpack(f"{len(raw) // 4}I", raw[: len(raw) // 4 * 4])


def peer_of(sock: socket.socket) -> Peer:
    raw = sock.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize("3i"))
    pid, uid, gid = struct.unpack("3i", raw)
    return Peer(pid, uid, gid, peer_groups(sock))


def _no_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    keys = [k for k, _ in pairs]
    if len(keys) != len(set(keys)):
        raise HelperError("bad_request", "duplicate keys")
    return dict(pairs)


def parse(raw: bytes) -> tuple[str, dict[str, object]]:
    if len(raw) > MAX_REQUEST:
        raise HelperError("bad_request", "request too large")
    try:
        request = json.loads(raw.decode("utf-8"), object_pairs_hook=_no_duplicates)
    except (UnicodeDecodeError, ValueError):
        raise HelperError("bad_request", "request is not valid JSON") from None
    if not isinstance(request, dict) or set(request) != {"op", "params"}:
        raise HelperError("bad_request", 'request must be {"op": ..., "params": {...}}')
    op, params = request["op"], request["params"]
    if not isinstance(op, str) or not isinstance(params, dict):
        raise HelperError("bad_request", "op must be a string and params an object")
    return op, params


def run_tool(argv: list[str], fds: tuple[int, ...]) -> None:
    try:
        subprocess.run(  # noqa: S603
            argv,
            pass_fds=fds,
            env=TOOL_ENV,
            capture_output=True,
            timeout=TOOL_TIMEOUT,
            check=True,
        )
    except subprocess.CalledProcessError as exc:
        detail = exc.stderr.decode(errors="replace").strip()
        raise HelperError("failed", f"{argv[0]}: {detail}") from None
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise HelperError("failed", f"{argv[0]}: {exc}") from None


def handle(
    raw: bytes,
    peer: Peer,
    config: HelperConfig,
    *,
    authorizer: Authorizer = authorize,
    runner: Runner = run_tool,
    operations: dict[str, Operation] | None = None,
) -> dict[str, Any]:
    name = "?"
    try:
        name, params = parse(raw)
        operation = (operations or registry()).get(name)
        if operation is None:
            raise HelperError("unknown_operation", f"unknown operation {name!r}")
        operation.check(params)
        if operation.action is not None and not authorizer(operation.action, peer):
            raise HelperError("not_authorized", "authorization refused")
        if operation.allowed is not None and not operation.allowed(peer):
            raise HelperError("not_authorized", "not allowed for this account")
        task = operation.prepare(params, config, peer)
        result = task(runner)
    except HelperError as exc:
        log.warning("uid=%d pid=%d op=%.40r refused: %s", peer.uid, peer.pid, name, exc.code)
        return {"ok": False, "error": exc.code, "message": exc.message}
    log.info("uid=%d pid=%d op=%s done", peer.uid, peer.pid, name)
    return {"ok": True, "result": result}


def _read_request(sock: socket.socket) -> bytes:
    deadline = time.monotonic() + READ_TIMEOUT
    data = b""
    while b"\n" not in data and len(data) <= MAX_REQUEST:
        left = deadline - time.monotonic()
        if left <= 0:
            raise TimeoutError("request not received in time")
        sock.settimeout(left)
        chunk = sock.recv(4096)
        if not chunk:
            break
        data += chunk
    return data.split(b"\n", 1)[0]


class _Handler(socketserver.BaseRequestHandler):
    server: HelperServer

    def handle(self) -> None:
        sock: socket.socket = self.request
        try:
            raw = _read_request(sock)
            answer = handle(raw, peer_of(sock), self.server.config)
            sock.settimeout(READ_TIMEOUT)
            sock.sendall(json.dumps(answer).encode() + b"\n")
        except OSError as exc:
            log.warning("connection dropped: %s", exc)


class HelperServer(socketserver.ThreadingUnixStreamServer):
    daemon_threads = True

    def __init__(self, config: HelperConfig) -> None:
        self.config = config
        self._lock = threading.Lock()
        self._open: Counter[int] = Counter()
        self._uid_of: dict[int, int] = {}
        activated = os.environ.get("LISTEN_PID") == str(os.getpid())
        if activated and os.environ.get("LISTEN_FDS") == "1":
            super().__init__(str(config.socket), _Handler, bind_and_activate=False)
            self.socket.close()
            self.socket = socket.socket(fileno=LISTEN_FD)
        else:
            config.socket.unlink(missing_ok=True)
            super().__init__(str(config.socket), _Handler)
            # Anyone may connect: polkit decides what each caller may do.
            os.chmod(config.socket, 0o666)  # noqa: S103

    def process_request(self, request: Any, client_address: Any) -> None:
        """Refuses a connection beyond the limits, before a thread is made for it."""
        try:
            uid = peer_of(request).uid
        except OSError:
            self.shutdown_request(request)
            return
        with self._lock:
            if self._open.total() >= MAX_CONNECTIONS or self._open[uid] >= MAX_PER_UID:
                busy = True
            else:
                busy = False
                self._open[uid] += 1
                self._uid_of[id(request)] = uid
        if busy:
            log.warning("uid=%d refused: too many connections", uid)
            self.shutdown_request(request)
            return
        try:
            super().process_request(request, client_address)
        except BaseException:
            self._release(request)
            raise

    def process_request_thread(self, request: Any, client_address: Any) -> None:
        try:
            super().process_request_thread(request, client_address)
        finally:
            self._release(request)

    def _release(self, request: Any) -> None:
        with self._lock:
            uid = self._uid_of.pop(id(request), None)
            if uid is None:
                return
            self._open[uid] -= 1
            if self._open[uid] <= 0:
                del self._open[uid]
