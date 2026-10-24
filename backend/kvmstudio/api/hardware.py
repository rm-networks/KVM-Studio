from __future__ import annotations

from fastapi import APIRouter, Response
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from ..context import Context
from ..services import hardware
from ..xml.profiles import NicModel

router = APIRouter(prefix="/vms", tags=["hardware"])


class Drive(BaseModel):
    target: str
    bus: str
    path: str | None
    format: str | None


class Nic(BaseModel):
    mac: str
    network: str | None
    model: str
    target: str | None
    connected: bool


class Hardware(BaseModel):
    memory_mib: int
    vcpus: int
    active: bool
    disks: list[Drive]
    cdroms: list[Drive]
    nics: list[Nic]


class CpuMemory(BaseModel):
    memory_mib: int = Field(ge=64, le=4 * 1024 * 1024)
    vcpus: int = Field(ge=1, le=512)


class NicCreate(BaseModel):
    network: str
    model: NicModel = "virtio"


class NicChange(BaseModel):
    network: str | None = None
    model: NicModel | None = None
    connected: bool | None = None


class CdromCreate(BaseModel):
    path: str | None = None


class Changed(BaseModel):
    restart_required: bool


def _drive(d: hardware.Drive) -> Drive:
    return Drive(target=d.target, bus=d.bus, path=d.path, format=d.format)


def _nic(n: hardware.Nic) -> Nic:
    return Nic(mac=n.mac, network=n.network, model=n.model, target=n.target, connected=n.connected)


@router.get("/{uuid}/hardware")
async def get(ctx: Context, uuid: str) -> Hardware:
    hw = await run_in_threadpool(hardware.get, ctx.conn, uuid)
    return Hardware(
        memory_mib=hw.memory_mib,
        vcpus=hw.vcpus,
        active=hw.active,
        disks=[_drive(d) for d in hw.disks],
        cdroms=[_drive(d) for d in hw.cdroms],
        nics=[_nic(n) for n in hw.nics],
    )


@router.put("/{uuid}/hardware/cpu-memory")
async def cpu_memory(ctx: Context, uuid: str, body: CpuMemory) -> Changed:
    restart = await run_in_threadpool(
        hardware.set_cpu_memory, ctx.conn, uuid, body.memory_mib, body.vcpus
    )
    return Changed(restart_required=restart)


@router.post("/{uuid}/nics", status_code=201)
async def add_nic(ctx: Context, uuid: str, body: NicCreate) -> Nic:
    nic = await run_in_threadpool(hardware.add_nic, ctx.conn, uuid, body.network, body.model)
    return _nic(nic)


@router.patch("/{uuid}/nics/{mac}")
async def change_nic(ctx: Context, uuid: str, mac: str, body: NicChange) -> Changed:
    restart = await run_in_threadpool(
        lambda: hardware.update_nic(
            ctx.conn, uuid, mac, network=body.network, model=body.model, connected=body.connected
        )
    )
    return Changed(restart_required=restart)


@router.delete("/{uuid}/nics/{mac}", status_code=204)
async def remove_nic(ctx: Context, uuid: str, mac: str) -> Response:
    await run_in_threadpool(hardware.remove_nic, ctx.conn, uuid, mac)
    return Response(status_code=204)


@router.post("/{uuid}/cdroms", status_code=201)
async def add_cdrom(ctx: Context, uuid: str, body: CdromCreate) -> Changed:
    restart = await run_in_threadpool(hardware.add_cdrom, ctx.conn, ctx.config, uuid, body.path)
    return Changed(restart_required=restart)


@router.delete("/{uuid}/cdroms/{target}")
async def remove_cdrom(ctx: Context, uuid: str, target: str) -> Changed:
    restart = await run_in_threadpool(hardware.remove_cdrom, ctx.conn, uuid, target)
    return Changed(restart_required=restart)
