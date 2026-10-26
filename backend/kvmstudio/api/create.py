from __future__ import annotations

from typing import Annotated

import libvirt
from fastapi import APIRouter, Query, Request
from lxml import etree
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from ..auth.roles import check_guest_networks
from ..context import Context
from ..services import create
from ..xml.profiles import PROFILES, DiskBus, Family, NicModel, guess_profile

router = APIRouter(tags=["create"])

ALL_BUSES: list[DiskBus] = ["virtio", "scsi", "sata", "nvme", "ide"]
NIC_MODELS: list[NicModel] = ["virtio", "e1000e", "rtl8139", "vmxnet3"]


class ProfileInfo(BaseModel):
    id: str
    family: Family
    memory_mib: int
    vcpus: int
    disk_gib: int
    disk_bus: DiskBus
    nic_model: NicModel
    nics: int
    uefi: bool
    secure_boot: bool
    tpm: bool
    serial: bool
    nested: bool


class HostInfo(BaseModel):
    cpus: int
    memory_mib: int
    disk_buses: list[DiskBus]
    nic_models: list[NicModel]
    uefi: bool
    secure_boot: bool
    tpm: bool


class Guess(BaseModel):
    profile: str


class NicChoice(BaseModel):
    network: str
    model: NicModel


class NewVmRequest(BaseModel):
    name: str
    folder: str = ""
    profile: str
    iso: str | None = None
    existing_disk: str | None = None
    existing_mode: create.ExistingMode = "in_place"
    disk_gib: int = Field(ge=0, le=16384)
    disk_bus: DiskBus
    disk_format: str = "qcow2"
    preallocate: bool = False
    memory_mib: int = Field(ge=64, le=4 * 1024 * 1024)
    vcpus: int = Field(ge=1, le=512)
    nics: list[NicChoice] = []
    uefi: bool = True
    secure_boot: bool = False
    tpm: bool = False
    start: bool = False


class Created(BaseModel):
    uuid: str


@router.get("/profiles")
def profiles() -> list[ProfileInfo]:
    return [
        ProfileInfo(
            id=p.id,
            family=p.family,
            memory_mib=p.memory_mib,
            vcpus=p.vcpus,
            disk_gib=p.disk_gib,
            disk_bus=p.disk_bus,
            nic_model=p.nic_model,
            nics=p.nics,
            uefi=p.uefi,
            secure_boot=p.secure_boot,
            tpm=p.tpm,
            serial=p.serial,
            nested=p.nested,
        )
        for p in PROFILES.values()
    ]


@router.get("/profiles/guess")
def guess(iso: Annotated[str, Query()]) -> Guess:
    return Guess(profile=guess_profile(iso.rsplit("/", 1)[-1]))


def _domain_caps(c: libvirt.virConnect) -> tuple[list[DiskBus], bool, bool, bool]:
    """Disk buses, UEFI, Secure Boot and TPM support; generous defaults if unknown."""
    try:
        xml = c.getDomainCapabilities(None, "x86_64", "q35", "kvm", 0)
    except libvirt.libvirtError:
        return ALL_BUSES, True, True, True
    root = etree.fromstring(xml.encode(), parser=etree.XMLParser(resolve_entities=False))
    buses = {v.text for v in root.iterfind("devices/disk/enum[@name='bus']/value")}
    firmware = {v.text for v in root.iterfind("os/enum[@name='firmware']/value")}
    secure = {v.text for v in root.iterfind("os/loader/enum[@name='secure']/value")}
    tpm = root.find("devices/tpm[@supported='yes']") is not None
    return (
        [b for b in ALL_BUSES if b in buses] or ALL_BUSES,
        "efi" in firmware,
        "yes" in secure,
        tpm,
    )


@router.get("/host")
async def host(ctx: Context) -> HostInfo:
    def op(c: libvirt.virConnect) -> HostInfo:
        info = c.getInfo()
        buses, uefi, secure, tpm = _domain_caps(c)
        return HostInfo(
            cpus=info[2],
            memory_mib=info[1],
            disk_buses=buses,
            nic_models=NIC_MODELS,
            uefi=uefi,
            secure_boot=secure,
            tpm=tpm,
        )

    return await run_in_threadpool(ctx.conn.run, op)


@router.post("/vms", status_code=201)
async def create_vm(ctx: Context, request: Request, body: NewVmRequest) -> Created:
    await run_in_threadpool(check_guest_networks, request, [n.network for n in body.nics])
    vm = create.NewVm(
        name=body.name,
        folder=body.folder,
        profile=body.profile,
        iso=body.iso,
        existing_disk=body.existing_disk,
        disk_gib=body.disk_gib,
        disk_bus=body.disk_bus,
        disk_format=body.disk_format,
        preallocate=body.preallocate,
        memory_mib=body.memory_mib,
        vcpus=body.vcpus,
        nics=[create.NicChoice(n.network, n.model) for n in body.nics],
        uefi=body.uefi,
        secure_boot=body.secure_boot,
        tpm=body.tpm,
        start=body.start,
        existing_mode=body.existing_mode,
        confined=getattr(request.state, "role", "owner") == "guest",
    )
    uuid = await run_in_threadpool(create.create_vm, ctx.conn, ctx.config, vm)
    return Created(uuid=uuid)
