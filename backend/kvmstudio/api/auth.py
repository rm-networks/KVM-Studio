"""Guest login of LAN sharing (F-105). Public routes: no token needed."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Request, Response
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from ..auth.guest import COOKIE, MAX_PASSWORD, SESSION_IDLE_S, check_password
from ..auth.roles import bearer_ok, on_lan_listener, role_of
from ..context import Context
from ..errors import ApiException

router = APIRouter(prefix="/auth", tags=["auth"])


class Login(BaseModel):
    password: str = Field(max_length=MAX_PASSWORD)


class Me(BaseModel):
    role: Literal["owner", "guest"] | None
    sharing: bool


@router.get("/me")
async def me(ctx: Context, request: Request) -> Me:
    role = role_of(request, token_ok=bearer_ok(request))
    return Me(role=role, sharing=ctx.sharing is not None)


@router.post("/login", status_code=204)
async def login(ctx: Context, request: Request, body: Login) -> Response:
    sharing = ctx.sharing
    if sharing is None or not on_lan_listener(request):
        raise ApiException(404, "auth.no_sharing", "LAN sharing is off")
    address = request.client.host if request.client else "?"
    if wait := sharing.limiter.locked_for(address):
        raise ApiException(429, "auth.locked", f"Too many attempts: try again in {wait} s")
    if not await run_in_threadpool(check_password, body.password):
        sharing.limiter.failed(address)
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
