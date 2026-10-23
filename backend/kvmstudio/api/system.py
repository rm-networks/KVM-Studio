from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

from .. import __version__
from ..context import Context, Mode


class Health(BaseModel):
    status: Literal["ok"] = "ok"


class LibvirtInfo(BaseModel):
    uri: str
    hostname: str
    driver: str
    libvirt_version: str
    hypervisor_version: str


class UiPreferences(BaseModel):
    theme: Literal["system", "light", "dark"]
    language: Literal["fr", "en"]


class AppInfo(BaseModel):
    version: str
    mode: Mode
    libvirt: LibvirtInfo
    ui: UiPreferences


def health() -> Health:
    return Health()


def info(ctx: Context) -> AppInfo:
    host = ctx.conn.host_info()
    return AppInfo(
        version=__version__,
        mode=ctx.mode,
        libvirt=LibvirtInfo(
            uri=host.uri,
            hostname=host.hostname,
            driver=host.driver,
            libvirt_version=host.libvirt_version,
            hypervisor_version=host.hypervisor_version,
        ),
        ui=UiPreferences(theme=ctx.config.ui.theme, language=ctx.config.ui.language),
    )
