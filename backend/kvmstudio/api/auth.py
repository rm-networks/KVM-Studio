"""Guest login of LAN sharing (F-105). Public routes: no token needed."""

from __future__ import annotations

import asyncio
from typing import Literal

from fastapi import APIRouter, Request, Response
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from ..auth.guest import COOKIE, MAX_CHECKS, MAX_PASSWORD, SESSION_IDLE_S, check_password
from ..auth.roles import bearer_ok, is_loopback, on_lan_listener, role_of
from ..auth.token import LINK_COPY_S, LINK_OPEN_S, LinkCodes
from ..context import Context
from ..errors import ApiException

router = APIRouter(prefix="/auth", tags=["auth"])
# Password checks running at once, for every address together.
CHECK_SLOTS = asyncio.Semaphore(MAX_CHECKS)


class Login(BaseModel):
    password: str = Field(max_length=MAX_PASSWORD)


class LinkRequest(BaseModel):
    purpose: Literal["open", "copy"] = "open"


class LinkCode(BaseModel):
    code: str


class Redeem(BaseModel):
    code: str = Field(max_length=64)


class Token(BaseModel):
    token: str


class Me(BaseModel):
    role: Literal["owner", "guest"] | None
    sharing: bool


@router.get("/me")
async def me(ctx: Context, request: Request) -> Me:
    role = role_of(request, token_ok=bearer_ok(request))
    return Me(role=role, sharing=ctx.sharing is not None)


def _codes(request: Request) -> LinkCodes:
    codes: LinkCodes = request.app.state.link_codes
    return codes


@router.post("/link")
async def new_link(request: Request, body: LinkRequest) -> LinkCode:
    """A single-use code for a link to this page (the owner only)."""
    if role_of(request, token_ok=bearer_ok(request)) != "owner":
        raise ApiException(401, "auth.invalid_token", "Missing or invalid session token")
    ttl = LINK_COPY_S if body.purpose == "copy" else LINK_OPEN_S
    return LinkCode(code=_codes(request).new(ttl))


@router.post("/redeem")
async def redeem(ctx: Context, request: Request, body: Redeem) -> Token:
    """The token, for a code of a link opened on this computer, once."""
    if not is_loopback(request) or not _codes(request).redeem(body.code):
        raise ApiException(401, "auth.invalid_token", "Unknown or expired link")
    return Token(token=ctx.token)


@router.post("/login", status_code=204)
async def login(ctx: Context, request: Request, body: Login) -> Response:
    sharing = ctx.sharing
    if sharing is None or not on_lan_listener(request):
        raise ApiException(404, "auth.no_sharing", "LAN sharing is off")
    address = request.client.host if request.client else "?"
    if wait := sharing.limiter.reserve(address):
        raise ApiException(429, "auth.locked", f"Too many attempts: try again in {wait} s")
    async with CHECK_SLOTS:
        accepted = await run_in_threadpool(check_password, body.password)
    if not accepted:
        raise ApiException(401, "auth.bad_password", "Wrong password")
    sharing.limiter.succeeded(address)
    response = Response(status_code=204)
    response.set_cookie(
        COOKIE,
        sharing.sessions.open(address),
        max_age=SESSION_IDLE_S * 48,
        httponly=True,
        secure=True,
        samesite="strict",
        path="/",
    )
    return response


@router.post("/logout", status_code=204)
async def logout(ctx: Context, request: Request) -> Response:
    if ctx.sharing is not None:
        ctx.sharing.sessions.close(request.cookies.get(COOKIE))
    response = Response(status_code=204)
    response.delete_cookie(COOKIE, path="/")
    return response
