"""Restarting KVM Studio in place, for instance after switching interface mode."""

from __future__ import annotations

import os
import sys

# Exit status of the backend child meaning "please restart the whole app".
RESTART_EXIT = 75


def restart_argv(argv: list[str]) -> list[str]:
    """Arguments for the new process: same options, but the mode comes from the config."""
    kept: list[str] = []
    skip = False
    for arg in argv:
        if skip:
            skip = False
            continue
        if arg == "--mode":
            skip = True
            continue
        if arg.startswith("--mode="):
            continue
        kept.append(arg)
    return kept


def exec_restart() -> None:
    """Replace the current process with a fresh KVM Studio (never returns)."""
    sys.stdout.flush()
    sys.stderr.flush()
    args = [sys.executable, "-m", "kvmstudio", *restart_argv(sys.argv[1:])]
    os.execv(sys.executable, args)  # noqa: S606
