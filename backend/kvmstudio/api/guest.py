from __future__ import annotations

import libvirt
from fastapi import APIRouter
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from ..context import Context
from ..guesttools import install
from ..guesttools.keymaps import Layout
from ..paths import in_iso_library
from ..services.library import metadata_values

router = APIRouter(prefix="/vms", tags=["guest"])


class GuestToolsInfo(BaseModel):
    active: bool
    family: install.Family | None
    layout: Layout | None
    agent: bool
    virtio_win: str | None


class InstallRequest(BaseModel):
    family: install.Family
    layout: Layout


class InstallResult(BaseModel):
    typed: bool
    drive: str | None


class AgentStatus(BaseModel):
    responding: bool


@router.get("/{uuid}/guest-tools")
async def info(ctx: Context, uuid: str) -> GuestToolsInfo:
    def op(c: libvirt.virConnect) -> GuestToolsInfo:
        dom = c.lookupByUUIDString(uuid)
        active = bool(dom.isActive())
        xml = dom.XMLDesc(0)
        meta = metadata_values(xml)
        family = meta.get("family") or install.guess_family(xml)
        layout = meta.get("keyboard")
        iso = ctx.config.defaults.virtio_win_iso
        return GuestToolsInfo(
            active=active,
            family=family if family in ("windows", "linux", "bsd", "other") else None,  # type: ignore[arg-type]
            layout=layout if layout in ("fr", "us") else None,  # type: ignore[arg-type]
            agent=active and install.agent_responds(dom),
            virtio_win=str(iso) if iso and in_iso_library(iso, ctx.config) else None,
        )

    return await run_in_threadpool(ctx.conn.run, op)


@router.post("/{uuid}/guest-tools")
async def run_install(ctx: Context, uuid: str, body: InstallRequest) -> InstallResult:
    drive = await run_in_threadpool(
        install.install, ctx.conn, ctx.config, uuid, body.family, body.layout
    )
    return InstallResult(typed=True, drive=drive)


@router.get("/{uuid}/agent")
async def agent(ctx: Context, uuid: str) -> AgentStatus:
    def op(c: libvirt.virConnect) -> AgentStatus:
        dom = c.lookupByUUIDString(uuid)
        return AgentStatus(responding=bool(dom.isActive()) and install.agent_responds(dom))

    return await run_in_threadpool(ctx.conn.run, op)
