from __future__ import annotations

import os
import pwd

import libvirt
from fastapi import APIRouter
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from .. import helper_client
from ..context import Context
from ..errors import ApiException
from ..services import networks as net
from ..services import setup

router = APIRouter(prefix="/setup", tags=["setup"])


class HostCheck(BaseModel):
    id: setup.CheckId
    level: setup.Level
    detail: str


class DefaultNetwork(BaseModel):
    name: str
    kind: net.EditableKind
    subnet: str | None
    exists: bool


class SetupStatus(BaseModel):
    # True until a VM location is chosen: the window then opens the assistant.
    needed: bool
    user: str
    checks: list[HostCheck]
    libvirt_group: setup.GroupState
    networks: list[DefaultNetwork]


class GroupResult(BaseModel):
    libvirt_group: setup.GroupState


def _status(ctx: Context) -> SetupStatus:
    try:
        plan = [
            DefaultNetwork(name=n.name, kind=n.kind, subnet=n.subnet, exists=n.exists)
            for n in setup.default_networks(ctx.conn)
        ]
    except (libvirt.libvirtError, ApiException):  # shown by the libvirt check
        plan = []
    return SetupStatus(
        needed=ctx.config.storage.vm_default_location is None,
        user=pwd.getpwuid(os.getuid()).pw_name,
        checks=[
            HostCheck(id=c.id, level=c.level, detail=c.detail) for c in setup.host_checks(ctx.conn)
        ],
        libvirt_group=setup.libvirt_group_state(ctx.config.libvirt.uri),
        networks=plan,
    )


@router.get("")
async def status(ctx: Context) -> SetupStatus:
    return await run_in_threadpool(_status, ctx)


@router.post("/libvirt-group")
async def join_libvirt_group(ctx: Context) -> GroupResult:
    """Ask the helper to add this account to the libvirt group (password asked by polkit)."""

    def run() -> GroupResult:
        if setup.libvirt_group_state(ctx.config.libvirt.uri) in ("member", "not_needed"):
            return GroupResult(libvirt_group="member")
        helper_client.call("join_libvirt", {})
        return GroupResult(libvirt_group="relogin")

    return await run_in_threadpool(run)


@router.post("/networks")
async def create_networks(ctx: Context) -> list[str]:
    return await run_in_threadpool(setup.create_default_networks, ctx.conn)
