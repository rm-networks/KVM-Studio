"""Turn libvirt errors into stable codes the frontend can translate."""

from __future__ import annotations

import libvirt
from fastapi import Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel


class ErrorBody(BaseModel):
    code: str
    detail: str


class ApiError(BaseModel):
    error: ErrorBody


_LIBVIRT_CODES: dict[int, tuple[int, str]] = {
    libvirt.VIR_ERR_NO_CONNECT: (503, "libvirt.unreachable"),
    libvirt.VIR_ERR_SYSTEM_ERROR: (503, "libvirt.unreachable"),
    libvirt.VIR_ERR_AUTH_FAILED: (403, "libvirt.auth_failed"),
    libvirt.VIR_ERR_AUTH_CANCELLED: (403, "libvirt.auth_failed"),
    libvirt.VIR_ERR_AUTH_UNAVAILABLE: (403, "libvirt.auth_failed"),
    libvirt.VIR_ERR_OPERATION_DENIED: (403, "libvirt.denied"),
    libvirt.VIR_ERR_ACCESS_DENIED: (403, "libvirt.denied"),
    libvirt.VIR_ERR_NO_DOMAIN: (404, "libvirt.no_domain"),
    libvirt.VIR_ERR_OPERATION_INVALID: (409, "libvirt.invalid_state"),
    libvirt.VIR_ERR_NO_SUPPORT: (501, "libvirt.unsupported"),
}


class ApiException(Exception):
    def __init__(self, status: int, code: str, detail: str) -> None:
        super().__init__(detail)
        self.status = status
        self.code = code
        self.detail = detail


def classify(exc: libvirt.libvirtError) -> tuple[int, str]:
    code = exc.get_error_code()
    if code is None:
        return 500, "libvirt.error"
    return _LIBVIRT_CODES.get(code, (500, "libvirt.error"))


def error_response(status: int, code: str, detail: str) -> JSONResponse:
    body = ApiError(error=ErrorBody(code=code, detail=detail))
    return JSONResponse(status_code=status, content=body.model_dump())


async def libvirt_error_handler(_request: Request, exc: Exception) -> JSONResponse:
    if not isinstance(exc, libvirt.libvirtError):
        raise exc
    status, code = classify(exc)
    return error_response(status, code, exc.get_error_message() or str(exc))


async def api_exception_handler(_request: Request, exc: Exception) -> JSONResponse:
    if not isinstance(exc, ApiException):
        raise exc
    return error_response(exc.status, exc.code, exc.detail)
