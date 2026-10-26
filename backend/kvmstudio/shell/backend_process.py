"""The backend (web server, libvirt and its event loop) in a child process.

libvirt's event loop runs on GLib's default main context, which Qt also uses
when it is built with GLib support: in one process, the libvirt thread ends up
dispatching Qt timers and the window crashes. Keeping the window (or the tray
icon) alone in the main process and everything libvirt in a child avoids that.

The child prints "READY <port>" once it listens on 127.0.0.1, and exits when
its standard input closes, so it never outlives the parent.
"""

from __future__ import annotations

import argparse
import contextlib
import os
import select
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Literal, TextIO

from ..i18n import set_language, t
from .restart import RESTART_EXIT

READY_PREFIX = "READY "
START_TIMEOUT = 30.0
TOKEN_ENV = "KVMSTUDIO_TOKEN"  # noqa: S105 (a variable name, not a secret)


class BackendError(Exception):
    pass


def _relay(stream: TextIO) -> None:
    for line in stream:
        sys.stderr.write(line)
        sys.stderr.flush()


class BackendProcess:
    def __init__(
        self, config_path: Path, mode: Literal["desktop", "web"], token: str, port: int = 0
    ) -> None:
        self._args = [
            sys.executable,
            "-m",
            "kvmstudio.shell.backend_process",
            "--config",
            str(config_path),
            "--mode",
            mode,
            "--port",
            str(port),
        ]
        self._token = token
        self._proc: subprocess.Popen[str] | None = None
        self._relay: threading.Thread | None = None
        self._last_code: int | None = None
        self.port = 0

    def start(self, timeout: float = START_TIMEOUT) -> int:
        env = {**os.environ, TOKEN_ENV: self._token}
        self._proc = subprocess.Popen(  # noqa: S603
            self._args,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            # Relayed to sys.stderr, where the startup error window reads it.
            stderr=subprocess.PIPE,
            text=True,
            env=env,
        )
        if self._proc.stdout is None or self._proc.stderr is None:
            raise BackendError("no pipe to the backend process")
        self._relay = threading.Thread(target=_relay, args=(self._proc.stderr,), daemon=True)
        self._relay.start()
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            ready, _, _ = select.select([self._proc.stdout], [], [], 0.2)
            if ready:
                line = self._proc.stdout.readline()
                if line.startswith(READY_PREFIX):
                    self.port = int(line[len(READY_PREFIX) :])
                    return self.port
                if line == "":
                    break
                sys.stdout.write(line)  # messages printed before READY
            if self._proc.poll() is not None:
                break
        self.stop()
        if self._relay is not None:
            self._relay.join(timeout=2)  # its last messages, before ours
        raise BackendError(t("cli.backend_failed"))

    def alive(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    @property
    def returncode(self) -> int | None:
        return self._proc.poll() if self._proc is not None else self._last_code

    def wants_restart(self) -> bool:
        return self.returncode == RESTART_EXIT

    def stop(self) -> None:
        proc = self._proc
        if proc is None:
            return
        if proc.stdin is not None:
            with contextlib.suppress(OSError):
                proc.stdin.close()  # the child exits when its stdin closes
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
        self._last_code = proc.returncode
        self._proc = None


def _serve(config_path: Path, mode: Literal["desktop", "web"], port: int) -> int:
    # Heavy imports only here, in the child.
    from ..app import create_app
    from ..config import ConfigError, load_config
    from ..frontend import find_frontend_dir
    from ..libvirt_conn import LibvirtConnection
    from .server import BackgroundServer, PortInUseError, bind_loopback
    from .sharing import SharingError, start_sharing, stop_sharing

    token = os.environ.get(TOKEN_ENV)
    if not token:
        print(f"{TOKEN_ENV} is not set", file=sys.stderr)
        return 2
    try:
        config = load_config(config_path)
    except ConfigError as exc:
        print(exc, file=sys.stderr)
        return 2
    set_language(config.ui.language)
    try:
        sock = bind_loopback(port)
    except PortInUseError as exc:
        print(t("cli.port_in_use", error=exc), file=sys.stderr)
        return 1
    lan = sharing = None
    if mode == "web" and config.web.share_on_lan:
        try:
            lan, sharing = start_sharing(config)
        except SharingError as exc:
            sock.close()
            print(exc, file=sys.stderr)
            return 2
    conn = LibvirtConnection(config.libvirt.uri)

    def request_restart() -> None:
        # Let the HTTP answer leave first; the parent sees the status and restarts.
        threading.Timer(0.3, os._exit, args=(RESTART_EXIT,)).start()

    app = create_app(
        config,
        conn,
        token,
        mode=mode,
        frontend_dir=find_frontend_dir(),
        config_path=config_path,
        on_restart=request_restart,
        sharing=sharing,
    )
    server = BackgroundServer(app, sock, lan)
    server.start()
    print(f"{READY_PREFIX}{server.port}", flush=True)

    # Exit when the parent closes our stdin (or dies).
    stop = threading.Event()

    def watch_stdin() -> None:
        try:
            while sys.stdin.read(4096):
                pass
        finally:
            stop.set()

    threading.Thread(target=watch_stdin, daemon=True).start()
    try:
        stop.wait()
    except KeyboardInterrupt:
        pass
    finally:
        server.stop()
        conn.close()
        if sharing is not None:
            stop_sharing(sharing)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(prog="kvmstudio-backend")
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--mode", choices=["desktop", "web"], required=True)
    parser.add_argument("--port", type=int, default=0)
    args = parser.parse_args()
    return _serve(args.config, args.mode, args.port)


if __name__ == "__main__":
    sys.exit(main())
