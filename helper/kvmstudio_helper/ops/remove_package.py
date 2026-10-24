"""Remove the kvm-studio package, at the end of the uninstall assistant.

No parameters: the package name is fixed here. The removal runs as a
transient systemd unit, outside this service, because removing the package
stops the helper itself.
"""

from __future__ import annotations

import shutil
from collections.abc import Mapping
from typing import Any

from ..config import HelperConfig
from ..errors import HelperError
from ..polkit import TOOL_ENV, Peer
from . import Runner, Task, expect_keys

ACTION = "org.kvmstudio.helper.remove-package"
PACKAGE = "kvm-studio"
UNIT = "kvm-studio-removal"


def which(name: str) -> str | None:
    return shutil.which(name, path=TOOL_ENV["PATH"])


def _removal() -> list[str]:
    if which("dnf"):
        return ["--", "dnf", "remove", "-y", PACKAGE]
    if which("apt-get"):
        return ["--setenv=DEBIAN_FRONTEND=noninteractive", "--", "apt-get", "remove", "-y", PACKAGE]
    raise HelperError("failed", "neither dnf nor apt-get was found")


def prepare(params: Mapping[str, object], config: HelperConfig, peer: Peer) -> Task:
    expect_keys(params, set())
    command = _removal()

    def run(runner: Runner) -> dict[str, Any]:
        runner(["systemd-run", f"--unit={UNIT}", "--collect", "--quiet", *command], ())
        return {"unit": UNIT}

    return run
