from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated, Literal, cast

from fastapi import Depends, Request

from .config import Config
from .libvirt_conn import LibvirtConnection

Mode = Literal["desktop", "web"]


@dataclass(frozen=True, slots=True)
class AppContext:
    config: Config
    conn: LibvirtConnection
    token: str
    mode: Mode


def get_context(request: Request) -> AppContext:
    return cast(AppContext, request.app.state.context)


Context = Annotated[AppContext, Depends(get_context)]
