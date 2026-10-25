from __future__ import annotations

import libvirt
from fastapi import APIRouter
from lxml import etree
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from ..console.vnc import graphics_types
from ..context import Context
from ..xml.devices import use_qemu_vdagent, vnc_graphics

router = APIRouter(prefix="/vms", tags=["console"])


class DisplayInfo(BaseModel):
    # What the running VM offers right now, and what its config will offer.
    live: list[str]
    config: list[str]
    clipboard: bool  # qemu-vdagent channel with copy/paste
    # Same, in the config: the running VM gets it at next boot.
    clipboard_config: bool
    # Turned off on purpose in Options > Isolation: no offer to turn it on.
    clipboard_isolated: bool = False
    active: bool


class DisplayChange(BaseModel):
    restart_required: bool


def _isolated(xml: str) -> bool:
    """Copy and paste turned off in Options > Isolation (channel kept, copypaste='no')."""
    root = etree.fromstring(xml.encode(), parser=etree.XMLParser(resolve_entities=False))
    clips = root.findall("devices/channel[@type='qemu-vdagent']/source/clipboard")
    return bool(clips) and all(c.get("copypaste") == "no" for c in clips)


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
            clipboard_config=_has_vdagent(config),
            clipboard_isolated=_isolated(config),
            active=active,
        )

    return await run_in_threadpool(ctx.conn.run, op)


def _edit_devices(conn: libvirt.virConnect, uuid: str, vnc: bool) -> DisplayChange:
    dom = conn.lookupByUUIDString(uuid)
    root = etree.fromstring(
        dom.XMLDesc(libvirt.VIR_DOMAIN_XML_INACTIVE).encode(),
        parser=etree.XMLParser(resolve_entities=False),
    )
    devices = root.find("devices")
    if devices is not None:
        changed = use_qemu_vdagent(devices)
        if vnc and devices.find("graphics[@type='vnc']") is None:
            devices.append(vnc_graphics())
            changed = True
        if changed:
            conn.defineXML(etree.tostring(root).decode())
    # Graphics and channels are not hot-plugged: a running VM gets them at next boot.
    return DisplayChange(restart_required=bool(dom.isActive()))


@router.post("/{uuid}/display/vnc")
async def add_vnc(ctx: Context, uuid: str) -> DisplayChange:
    """Add a listen-less VNC display next to the existing ones (SPICE stays)."""
    return await run_in_threadpool(ctx.conn.run, lambda c: _edit_devices(c, uuid, vnc=True))


@router.post("/{uuid}/display/clipboard")
async def enable_clipboard(ctx: Context, uuid: str) -> DisplayChange:
    """Copy and paste for a VM whose agent port belongs to SPICE, or that has none.

    The console needs a VNC display too: a SPICE-only VM gets one, SPICE stays.
    """
    return await run_in_threadpool(ctx.conn.run, lambda c: _edit_devices(c, uuid, vnc=True))
