"""Headers on every HTTP answer, to limit what an injected script could do.

Scripts only from our own files; styles may be inline because xterm.js adds
<style> elements; WebSockets to any address the page was served from. No
framing, no MIME sniffing, no Referer, and HSTS on the HTTPS listener.

In window mode the page is only shown by the window, whose bridge to Python
(pywebview) is built with new Function() and runs evaluate_js with eval():
there, and only there, scripts may evaluate strings.
"""

from __future__ import annotations

from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send


def policy(*, window: bool = False) -> str:
    return "; ".join(
        [
            "default-src 'self'",
            "script-src 'self' 'unsafe-eval'" if window else "script-src 'self'",
            "style-src 'self' 'unsafe-inline'",
            "img-src 'self' data: blob:",
            "font-src 'self' data:",
            "connect-src 'self' ws: wss:",
            "object-src 'none'",
            "base-uri 'none'",
            "form-action 'self'",
            "frame-ancestors 'none'",
        ]
    )


CSP = policy()
HSTS = "max-age=31536000"


class SecurityHeaders:
    def __init__(self, app: ASGIApp, *, window: bool = False) -> None:
        self.app = app
        self.csp = policy(window=window)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        secure = scope.get("scheme") == "https"

        async def with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                headers["Content-Security-Policy"] = self.csp
                headers["X-Content-Type-Options"] = "nosniff"
                headers["X-Frame-Options"] = "DENY"
                headers["Referrer-Policy"] = "no-referrer"
                if secure:
                    headers["Strict-Transport-Security"] = HSTS
            await send(message)

        await self.app(scope, receive, with_headers)
