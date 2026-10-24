from __future__ import annotations

import libvirt
from fastapi import APIRouter
from lxml import etree
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from ..console.vnc import graphics_types
from ..context import Context
from ..xml.devices import vnc_graphics

router = APIRouter(prefix="/vms", tags=["console"])


class DisplayInfo(BaseModel):
    # What the running VM offers right now, and what its config will offer.
    live: list[str]
    config: list[str]
    clipboard: bool  # qemu-vdagent channel with copy/paste
    active: bool


class DisplayChange(BaseModel):
    restart_required: bool


def _has_vdagent(xml: str) -> bool:
    root = etree.fromstring(xml.encode(), parser=etree.XMLParser(resolve_entities=False))
    for channel in root.iterfind("devices/channel[@type='qemu-vdagent']"):
        clip = channel.find("source/clipboard")
        if clip is not None and clip.get("copypaste") == "yes":
            return True
    return False


@router.get("/{uuid}/display")
async def display(ctx: Context, uuid: str) -> DisplayInfo:
    def op(c: libvirt.virConnect) -> DisplayInfo:
        dom = c.lookupByUUIDString(uuid)
        active = bool(dom.isActive())
        live = dom.XMLDesc(0)
        config = dom.XMLDesc(libvirt.VIR_DOMAIN_XML_INACTIVE) if dom.isPersistent() else live
        return DisplayInfo(
            live=graphics_types(live) if active else [],
            config=graphics_types(config),
            clipboard=_has_vdagent(live if active else config),
            active=active,
        )

    return await run_in_threadpool(ctx.conn.run, op)


@router.post("/{uuid}/display/vnc")
async def add_vnc(ctx: Context, uuid: str) -> DisplayChange:
    """Add a listen-less VNC display next to the existing ones (SPICE stays)."""

    def op(c: libvirt.virConnect) -> DisplayChange:
        dom = c.lookupByUUIDString(uuid)
        root = etree.fromstring(
            dom.XMLDesc(libvirt.VIR_DOMAIN_XML_INACTIVE).encode(),
            parser=etree.XMLParser(resolve_entities=False),
        )
        devices = root.find("devices")
        if devices is not None and devices.find("graphics[@type='vnc']") is None:
            devices.append(vnc_graphics())
            c.defineXML(etree.tostring(root).decode())
        # Graphics cannot be hot-plugged: a running VM gets it at next boot.
        return DisplayChange(restart_required=bool(dom.isActive()))

    return await run_in_threadpool(ctx.conn.run, op)
