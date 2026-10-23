from __future__ import annotations

import socket
from collections.abc import Callable
from dataclasses import dataclass
from typing import Annotated, Literal, cast

from fastapi import Depends
from starlette.requests import HTTPConnection

from .config import Config
from .libvirt_conn import LibvirtConnection

Mode = Literal["desktop", "web"]


@dataclass(frozen=True, slots=True)
class AppContext:
    config: Config
    conn: LibvirtConnection
    token: str
    mode: Mode
    open_console: Callable[[LibvirtConnection, str], socket.socket]


def get_context(conn: HTTPConnection) -> AppContext:
    return cast(AppContext, conn.app.state.context)


Context = Annotated[AppContext, Depends(get_context)]
