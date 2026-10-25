"""LAN sharing (F-100 to F-106), owner only: state and the guest password."""

from __future__ import annotations

from fastapi import APIRouter, Response
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from ..auth import guest
from ..context import Context
from ..errors import ApiException
from ..services import networks as net

router = APIRouter(prefix="/sharing", tags=["sharing"])


class SharingState(BaseModel):
    # In the configuration (applied when web mode starts).
    enabled: bool
    # Listening on the LAN right now.
    active: bool
    https_port: int
    has_password: bool
    addresses: list[str]
    fingerprint: str
    guests: int
    # The firewall the helper opened the port in, if any.
    firewall: str | None


class GuestPassword(BaseModel):
    password: str = Field(min_length=guest.MIN_PASSWORD, max_length=guest.MAX_PASSWORD)


@router.get("")
async def state(ctx: Context) -> SharingState:
    sharing = ctx.sharing
    return SharingState(
        enabled=ctx.config.web.share_on_lan,
        active=sharing is not None,
        https_port=ctx.config.web.https_port,
        has_password=await run_in_threadpool(guest.has_password),
        addresses=await run_in_threadpool(net.host_addresses),
        fingerprint=sharing.fingerprint if sharing else "",
        guests=sharing.sessions.count() if sharing else 0,
        firewall=sharing.firewall if sharing else None,
    )


@router.put("/password", status_code=204)
async def set_password(ctx: Context, body: GuestPassword) -> Response:
    if body.password.strip() != body.password or not body.password:
        raise ApiException(422, "sharing.bad_password", "No spaces around the password")
    await run_in_threadpool(guest.set_password, body.password)
    # Guests logged in with the old password have to log in again.
    if ctx.sharing is not None:
        ctx.sharing.sessions.close_all()
    return Response(status_code=204)
