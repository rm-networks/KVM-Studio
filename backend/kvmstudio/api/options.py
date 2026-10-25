from __future__ import annotations

from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from ..context import Context
from ..services import options

router = APIRouter(prefix="/vms", tags=["options"])


class BootDevice(BaseModel):
    kind: options.BootKind
    id: str
    detail: str
    enabled: bool


class Options(BaseModel):
    name: str
    profile: str | None
    active: bool
    installed: bool
    autostart: bool
    on_reboot: str
    on_crash: str
    firmware: options.Firmware
    secure_boot: bool
    tpm: bool
    boot_menu: bool
    boot: list[BootDevice]
    clipboard: bool
    reset_nvram_pending: bool


class BootEntry(BaseModel):
    kind: options.BootKind
    id: str
    enabled: bool


class OptionsChange(BaseModel):
    profile: str | None = None
    autostart: bool | None = None
    on_reboot: options.RebootAction | None = None
    on_crash: options.CrashAction | None = None
    firmware: Literal["uefi", "bios"] | None = None
    secure_boot: bool | None = None
    tpm: bool | None = None
    boot_menu: bool | None = None
    boot: list[BootEntry] | None = None
    clipboard: bool | None = None
    confirmed: bool = False


class Changed(BaseModel):
    restart_required: bool


@router.get("/{uuid}/options")
async def get_options(ctx: Context, uuid: str) -> Options:
    found = await run_in_threadpool(options.get, ctx.conn, uuid)
    return Options.model_validate(
        {
            **{k: getattr(found, k) for k in Options.model_fields if k != "boot"},
            "boot": [BootDevice.model_validate(b, from_attributes=True) for b in found.boot],
        }
    )


@router.put("/{uuid}/options")
async def set_options(ctx: Context, uuid: str, body: OptionsChange) -> Changed:
    change = options.OptionsChange(
        **body.model_dump(exclude={"boot"}),
        boot=[(b.kind, b.id, b.enabled) for b in body.boot] if body.boot is not None else None,
    )
    restart = await run_in_threadpool(options.update, ctx.conn, uuid, change)
    return Changed(restart_required=restart)
