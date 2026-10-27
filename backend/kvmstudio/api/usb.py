from __future__ import annotations

from fastapi import APIRouter, Response
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from ..context import Context
from ..services import usb

router = APIRouter(tags=["usb"])


class UsbDevice(BaseModel):
    bus: int
    device: int
    vendor_id: str
    product_id: str
    name: str
    size: int
    disks: list[str]
    mountpoints: list[str]
    in_use: list[str]
    vm: str | None
    vm_name: str | None


class UsbAddress(BaseModel):
    bus: int
    device: int


@router.get("/usb")
async def devices(ctx: Context) -> list[UsbDevice]:
    found = await run_in_threadpool(usb.list_devices, ctx.conn)
    return [UsbDevice.model_validate(d, from_attributes=True) for d in found]


@router.post("/vms/{uuid}/usb")
async def connect(ctx: Context, uuid: str, body: UsbAddress) -> UsbDevice:
    found = await run_in_threadpool(usb.connect, ctx.conn, uuid, body.bus, body.device)
    return UsbDevice.model_validate(found, from_attributes=True)


@router.delete("/vms/{uuid}/usb/{bus}/{device}", status_code=204)
async def disconnect(ctx: Context, uuid: str, bus: int, device: int) -> Response:
    await run_in_threadpool(usb.disconnect, ctx.conn, uuid, bus, device)
    return Response(status_code=204)
