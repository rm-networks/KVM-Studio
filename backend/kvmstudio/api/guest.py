from __future__ import annotations

import libvirt
from fastapi import APIRouter
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from ..context import Context
from ..guesttools import tools
from ..services.library import metadata_values

router = APIRouter(prefix="/vms", tags=["guest"])


class GuestToolsInfo(BaseModel):
    active: bool
    family: tools.Family | None
    agent: bool
    # The tools CD is in a drive (put back the previous media with eject).
    inserted: bool
    # The virtio-win ISO of the Preferences, as configured, and what is wrong with it.
    virtio_win: str | None
    virtio_state: tools.VirtioState
    linux_command: str


class InsertRequest(BaseModel):
    family: tools.Family


class InsertResult(BaseModel):
    drive: str
    # The drive or the agent channel is only in the config yet: power the VM
    # off and start it again (a reboot inside the guest is not enough).
    restart_required: bool
    # Windows: virtio-win-guest-tools.exe is on the CD.
    installer: str | None


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
        state, iso = tools.virtio_iso(ctx.config)
        return GuestToolsInfo(
            active=active,
            family=family if family in ("windows", "linux", "bsd", "other") else None,  # type: ignore[arg-type]
            agent=active and tools.agent_responds(dom),
            inserted=tools.inserted(xml),
            virtio_win=str(iso) if iso else None,
            virtio_state=state,
            linux_command=tools.LINUX_COMMAND,
        )

    return await run_in_threadpool(ctx.conn.run, op)


@router.post("/{uuid}/guest-tools")
async def insert(ctx: Context, uuid: str, body: InsertRequest) -> InsertResult:
    drive, restart = await run_in_threadpool(tools.insert, ctx.conn, ctx.config, uuid, body.family)
    installer = tools.WINDOWS_INSTALLER if body.family == "windows" else None
    return InsertResult(drive=drive, restart_required=restart, installer=installer)


@router.post("/{uuid}/guest-tools/eject")
async def eject(ctx: Context, uuid: str) -> EjectResult:
    return EjectResult(drives=await run_in_threadpool(tools.eject, ctx.conn, uuid))


@router.get("/{uuid}/agent")
async def agent(ctx: Context, uuid: str) -> AgentStatus:
    def op(c: libvirt.virConnect) -> AgentStatus:
        dom = c.lookupByUUIDString(uuid)
        return AgentStatus(responding=bool(dom.isActive()) and tools.agent_responds(dom))

    return await run_in_threadpool(ctx.conn.run, op)
