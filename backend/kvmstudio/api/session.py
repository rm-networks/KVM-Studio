"""What happens to running VMs when KVM Studio closes or changes mode.

VMs are run by libvirt and QEMU, not by KVM Studio: they keep running unless
the user asks to suspend them (state saved to disk, resumed at next start) or
to shut them down.
"""

from __future__ import annotations

from typing import Literal

import libvirt
from fastapi import APIRouter
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from ..context import Context
from ..errors import classify

router = APIRouter(prefix="/session", tags=["session"])

CloseAction = Literal["suspend", "shutdown", "poweroff"]


class RunningVm(BaseModel):
    uuid: str
    name: str


class Failure(BaseModel):
    name: str
    code: str
    detail: str


class ActionResult(BaseModel):
    done: list[str]
    failed: list[Failure]


def _running(c: libvirt.virConnect) -> list[libvirt.virDomain]:
    return sorted(
        c.listAllDomains(libvirt.VIR_CONNECT_LIST_DOMAINS_ACTIVE), key=lambda d: d.name().casefold()
    )


@router.get("/running")
async def running(ctx: Context) -> list[RunningVm]:
    def op(c: libvirt.virConnect) -> list[RunningVm]:
        return [RunningVm(uuid=d.UUIDString(), name=d.name()) for d in _running(c)]

    return await run_in_threadpool(ctx.conn.run, op)


@router.post("/running/{action}")
async def act(ctx: Context, action: CloseAction) -> ActionResult:
    """Suspend, shut down or power off every running VM; reports each failure."""

    def op(c: libvirt.virConnect) -> ActionResult:
        result = ActionResult(done=[], failed=[])
        for dom in _running(c):
            try:
                if action == "suspend":
                    # Saved to disk; libvirt restores it at the next start.
                    dom.managedSave(0)
                elif action == "shutdown":
                    dom.shutdownFlags(0)
                else:
                    dom.destroy()
                result.done.append(dom.name())
            except libvirt.libvirtError as exc:
                code = classify(exc)[1]
                result.failed.append(Failure(name=dom.name(), code=code, detail=str(exc)))
        return result

    return await run_in_threadpool(ctx.conn.run, op)
