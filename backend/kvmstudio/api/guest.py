from __future__ import annotations

import libvirt
from fastapi import APIRouter
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from ..context import Context
from ..guesttools import tools
from ..paths import in_iso_library
from ..services.library import metadata_values

router = APIRouter(prefix="/vms", tags=["guest"])


class GuestToolsInfo(BaseModel):
    active: bool
    family: tools.Family | None
    agent: bool
    # The tools CD is in a drive (put back the previous media with eject).
    inserted: bool
    virtio_win: str | None
    linux_command: str


class InsertRequest(BaseModel):
    family: tools.Family


class InsertResult(BaseModel):
    drives: list[str]
    # A drive or the agent channel was added to the config: restart the VM.
    restart_required: bool


class EjectResult(BaseModel):
    drives: list[str]


class AgentStatus(BaseModel):
    responding: bool


@router.get("/{uuid}/guest-tools")
async def info(ctx: Context, uuid: str) -> GuestToolsInfo:
    def op(c: libvirt.virConnect) -> GuestToolsInfo:
        dom = c.lookupByUUIDString(uuid)
        active = bool(dom.isActive())
        xml = dom.XMLDesc(0)
        family = metadata_values(xml).get("family") or tools.guess_family(xml)
        iso = ctx.config.defaults.virtio_win_iso
        return GuestToolsInfo(
            active=active,
            family=family if family in ("windows", "linux", "bsd", "other") else None,  # type: ignore[arg-type]
            agent=active and tools.agent_responds(dom),
            inserted=tools.inserted(xml),
            virtio_win=str(iso) if iso and in_iso_library(iso, ctx.config) else None,
            linux_command=tools.LINUX_COMMAND,
        )

    return await run_in_threadpool(ctx.conn.run, op)


@router.post("/{uuid}/guest-tools")
async def insert(ctx: Context, uuid: str, body: InsertRequest) -> InsertResult:
    drives, restart = await run_in_threadpool(tools.insert, ctx.conn, ctx.config, uuid, body.family)
    return InsertResult(drives=drives, restart_required=restart)


@router.post("/{uuid}/guest-tools/eject")
async def eject(ctx: Context, uuid: str) -> EjectResult:
    return EjectResult(drives=await run_in_threadpool(tools.eject, ctx.conn, uuid))


@router.get("/{uuid}/agent")
async def agent(ctx: Context, uuid: str) -> AgentStatus:
    def op(c: libvirt.virConnect) -> AgentStatus:
        dom = c.lookupByUUIDString(uuid)
        return AgentStatus(responding=bool(dom.isActive()) and tools.agent_responds(dom))

    return await run_in_threadpool(ctx.conn.run, op)
