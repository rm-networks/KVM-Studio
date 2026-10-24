"""Ask polkit whether the process at the other end of the socket may do this.

The subject is the peer process as the kernel reports it (SO_PEERCRED):
pid, its start time (so a recycled pid is detected) and its real uid. Nothing
the client sends is used to identify it.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

# Tools are looked up in the system directories only.
TOOL_ENV = {"PATH": "/usr/sbin:/usr/bin", "LC_ALL": "C"}
# Leaves time to type a password in the authentication dialog.
TIMEOUT = 300


@dataclass(frozen=True, slots=True)
class Peer:
    pid: int
    uid: int
    gid: int


def start_time(pid: int) -> str:
    """Field 22 of /proc/<pid>/stat; the command name before it may contain spaces."""
    stat = Path(f"/proc/{pid}/stat").read_text()
    return stat[stat.rindex(")") + 2 :].split()[19]


def authorize(action: str, peer: Peer) -> bool:
    try:
        subject = f"{peer.pid},{start_time(peer.pid)},{peer.uid}"
    except (OSError, ValueError, IndexError):
        return False
    argv = ["pkcheck", "--action-id", action, "--process", subject, "--allow-user-interaction"]
    try:
        result = subprocess.run(  # noqa: S603
            argv,
            env=TOOL_ENV,
            capture_output=True,
            timeout=TIMEOUT,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0
