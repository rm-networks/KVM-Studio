from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Request, Response
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from ..auth.roles import check_guest_networks
from ..context import Context
from ..services import disks, hardware
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


class Notes(BaseModel):
    notes: str = Field(max_length=hardware.MAX_NOTES)


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


@router.put("/{uuid}/notes", status_code=204)
async def set_notes(ctx: Context, uuid: str, body: Notes) -> Response:
    await run_in_threadpool(hardware.set_notes, ctx.conn, uuid, body.notes)
    return Response(status_code=204)


@router.post("/{uuid}/nics", status_code=201)
async def add_nic(ctx: Context, request: Request, uuid: str, body: NicCreate) -> Nic:
    await run_in_threadpool(check_guest_networks, request, [body.network])
    nic = await run_in_threadpool(hardware.add_nic, ctx.conn, uuid, body.network, body.model)
    return _nic(nic)


@router.patch("/{uuid}/nics/{mac}")
async def change_nic(
    ctx: Context, request: Request, uuid: str, mac: str, body: NicChange
) -> Changed:
    await run_in_threadpool(check_guest_networks, request, [body.network])
    restart = await run_in_threadpool(
        lambda: hardware.update_nic(
            ctx.conn, uuid, mac, network=body.network, model=body.model, connected=body.connected
        )
    )
    return Changed(restart_required=restart)


class NewMac(BaseModel):
    mac: str


@router.post("/{uuid}/nics/{mac}/new-mac")
async def new_mac(ctx: Context, uuid: str, mac: str) -> NewMac:
    return NewMac(mac=await run_in_threadpool(hardware.new_mac, ctx.conn, uuid, mac))


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


class DiskSize(BaseModel):
    target: str
    path: str
    capacity: int
    allocation: int
    expandable: bool
    deletable: bool


class DiskExpand(BaseModel):
    gib: int = Field(gt=0)


@router.get("/{uuid}/disks/{target}")
async def disk_size(ctx: Context, uuid: str, target: str) -> DiskSize:
    found = await run_in_threadpool(disks.size, ctx.conn, ctx.config, uuid, target)
    return DiskSize.model_validate(found, from_attributes=True)


@router.post("/{uuid}/disks/{target}/expand")
async def expand_disk(ctx: Context, uuid: str, target: str, body: DiskExpand) -> DiskSize:
    found = await run_in_threadpool(disks.expand, ctx.conn, ctx.config, uuid, target, body.gib)
    return DiskSize.model_validate(found, from_attributes=True)


class DiskCreate(BaseModel):
    """A new disk of size_gib, or the existing file at path."""

    bus: Literal["virtio", "sata", "scsi"] = "virtio"
    size_gib: int = Field(default=0, ge=0, le=disks.MAX_GIB)
    format: Literal["qcow2", "raw"] = "qcow2"
    existing: str | None = None


class AddedDisk(BaseModel):
    target: str
    path: str


class RemovedDisk(BaseModel):
    deleted: list[str]


@router.get("/{uuid}/disks-folder")
async def disks_folder(ctx: Context, uuid: str) -> dict[str, str]:
    folder = await run_in_threadpool(disks.default_dir, ctx.conn, ctx.config, uuid)
    return {"path": str(folder)}


@router.post("/{uuid}/disks", status_code=201)
async def add_disk(ctx: Context, request: Request, uuid: str, body: DiskCreate) -> AddedDisk:
    added = await run_in_threadpool(
        lambda: disks.add(
            ctx.conn,
            ctx.config,
            uuid,
            bus=body.bus,
            size_gib=body.size_gib,
            fmt=body.format,
            existing=body.existing,
            # A guest picks an existing disk only inside the library.
            confined=getattr(request.state, "role", "owner") == "guest",
        )
    )
    return AddedDisk(target=added.target, path=added.path)


@router.delete("/{uuid}/disks/{target}")
async def remove_disk(
    ctx: Context, uuid: str, target: str, delete_file: bool = False
) -> RemovedDisk:
    deleted = await run_in_threadpool(
        lambda: disks.remove(ctx.conn, ctx.config, uuid, target, delete_file=delete_file)
    )
    return RemovedDisk(deleted=deleted)
