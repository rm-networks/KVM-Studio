from __future__ import annotations

from typing import Literal

from fastapi import Request
from pydantic import BaseModel

from .. import APP_NAME, __version__
from ..context import Context, Mode
from ..errors import ApiException
from ..i18n import resolve
from ..services import host_kvm


class Health(BaseModel):
    status: Literal["ok"] = "ok"


class LibvirtInfo(BaseModel):
    uri: str
    hostname: str
    driver: str
    libvirt_version: str
    hypervisor_version: str


class KvmInfo(BaseModel):
    """KVM on the host, checked at each start (kernel updates can break it)."""

    problem: host_kvm.Problem | None
    kernel: str
    module: str


class UiPreferences(BaseModel):
    theme: Literal["system", "light", "dark"]
    # The language to show: the setting, or the desktop's when it is "system".
    language: Literal["en", "fr"]


class AppInfo(BaseModel):
    version: str
    mode: Mode
    libvirt: LibvirtInfo
    ui: UiPreferences
    # Only for a QEMU connection (not the test driver).
    kvm: KvmInfo | None = None


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
        ui=UiPreferences(theme=ctx.config.ui.theme, language=resolve(ctx.config.ui.language)),
        kvm=_kvm() if host.uri.startswith("qemu") else None,
    )


def _kvm() -> KvmInfo:
    state = host_kvm.kvm_state()
    module = state.module or ("kvm_amd" if state.vendor == "amd" else "kvm_intel")
    return KvmInfo(problem=state.problem, kernel=state.kernel, module=module)


class Restarting(BaseModel):
    restarting: Literal[True] = True


def restart(request: Request) -> Restarting:
    """Restart the whole app (after an interface mode change, for instance)."""
    on_restart = request.app.state.on_restart
    if on_restart is None:
        raise ApiException(409, "restart.unavailable", f"Restart {APP_NAME} by hand")
    on_restart()
    return Restarting()
