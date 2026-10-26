from __future__ import annotations

import socket
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, Literal, cast

from fastapi import Depends
from starlette.requests import HTTPConnection

from .config import Config
from .libvirt_conn import LibvirtConnection

if TYPE_CHECKING:
    from .auth.roles import Sharing
    from .console.serial import SerialOpener

Mode = Literal["desktop", "web"]


@dataclass(slots=True)
class AppContext:
    config: Config
    conn: LibvirtConnection
    token: str
    mode: Mode
    open_console: Callable[[LibvirtConnection, str], socket.socket]
    open_serial: SerialOpener
    # Where Preferences are saved; None when the app runs without a file (tests).
    config_path: Path | None = None
    # LAN sharing (web mode with share_on_lan); None otherwise.
    sharing: Sharing | None = None


def get_context(conn: HTTPConnection) -> AppContext:
    return cast(AppContext, conn.app.state.context)


Context = Annotated[AppContext, Depends(get_context)]
