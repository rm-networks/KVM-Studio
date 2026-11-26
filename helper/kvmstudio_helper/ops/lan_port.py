"""Open or close the HTTPS port of LAN sharing in the host firewall (F-106).

firewalld (default zone, runtime only: a crash, a reboot or a firewall
reload leaves it closed) or else ufw, whose rules always last: the
forwarding unit closes what was recorded at boot. The helper writes down what
it opened, so that closing, and the package removal, take back exactly that
and nothing else. Closing is its own operation, without a password for the
active session: it can only take back what was opened.
"""

from __future__ import annotations

import contextlib
import json
import os
import shutil
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from ..config import HelperConfig
from ..errors import HelperError
from ..polkit import Peer
from . import Runner, Task, expect_keys

ACTION = "org.kvmstudio.helper.lan-port"
CLOSE_ACTION = "org.kvmstudio.helper.lan-port-close"
DEFAULT_PORT = 60443
SERVICE = "kvm-studio"


def state_file(config: HelperConfig) -> Path:
    return config.state.parent / "lan-port.json"


def _firewall(runner: Runner) -> str | None:
    if shutil.which("firewall-cmd", path="/usr/sbin:/usr/bin"):
        try:
            runner(["firewall-cmd", "--state"], ())
            return "firewalld"
        except HelperError:
            pass
    if shutil.which("ufw", path="/usr/sbin:/usr/bin"):
        return "ufw"
    return None


def _firewalld_spec(port: int) -> str:
    # The packaged firewalld service (shown by name in firewall-config) has the
    # default port; another port is opened alone.
    if port == DEFAULT_PORT:
        return f"--{{}}-service={SERVICE}"
    return f"--{{}}-port={port}/tcp"


def _open(tool: str, port: int, runner: Runner) -> None:
    if tool == "firewalld":
        runner(["firewall-cmd", _firewalld_spec(port).format("add")], ())
    else:
        runner(["ufw", "allow", f"{port}/tcp", "comment", "kvm-studio"], ())


def _close(tool: str, port: int, runner: Runner) -> None:
    if tool == "firewalld":
        spec = _firewalld_spec(port).format("remove")
        with contextlib.suppress(HelperError):
            runner(["firewall-cmd", spec], ())
        # Versions up to 1.1.1 opened it in the permanent configuration too.
        with contextlib.suppress(HelperError):
            runner(["firewall-cmd", "--permanent", spec], ())
    else:
        with contextlib.suppress(HelperError):
            runner(["ufw", "delete", "allow", f"{port}/tcp"], ())


def _load(config: HelperConfig) -> dict[str, Any]:
    try:
        data = json.loads(state_file(config).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _save(config: HelperConfig, data: dict[str, Any] | None) -> None:
    path = state_file(config)
    if data is None:
        path.unlink(missing_ok=True)
        return
    path.parent.mkdir(mode=0o755, parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as out:
        json.dump(data, out)


def close_recorded(config: HelperConfig, runner: Runner) -> None:
    data = _load(config)
    tool, port = data.get("tool"), data.get("port")
    if tool in ("firewalld", "ufw") and isinstance(port, int):
        _close(str(tool), port, runner)
    _save(config, None)


def check(params: Mapping[str, object]) -> None:
    expect_keys(params, {"open", "port"})
    if not isinstance(params["open"], bool):
        raise HelperError("invalid_params", "open must be true or false")
    port = params["port"]
    if not isinstance(port, int) or isinstance(port, bool) or not 1024 <= port <= 65535:
        raise HelperError("invalid_params", "port must be between 1024 and 65535")


def prepare(params: Mapping[str, object], config: HelperConfig, peer: Peer) -> Task:
    expect_keys(params, {"open", "port"})
    wanted, port = params["open"], params["port"]
    if not isinstance(wanted, bool):
        raise HelperError("invalid_params", "open must be true or false")
    if not isinstance(port, int) or isinstance(port, bool) or not 1024 <= port <= 65535:
        raise HelperError("invalid_params", "port must be between 1024 and 65535")

    def run(runner: Runner) -> dict[str, Any]:
        close_recorded(config, runner)
        if not wanted:
            return {"firewall": None}
        tool = _firewall(runner)
        if tool is not None:
            _open(tool, port, runner)
            _save(config, {"tool": tool, "port": port})
        return {"firewall": tool}

    return run


def check_close(params: Mapping[str, object]) -> None:
    expect_keys(params, set())


def prepare_close(params: Mapping[str, object], config: HelperConfig, peer: Peer) -> Task:
    expect_keys(params, set())

    def run(runner: Runner) -> dict[str, Any]:
        closed = bool(_load(config))
        close_recorded(config, runner)
        return {"closed": closed}

    return run
