"""
Who may use the backend (hardening, 2026-10-29). Before this, the backend answered any web page with
"Access-Control-Allow-Origin: *": a website open in the student's browser could have found its port and read their
notes and decks, or searched their files. Now every request must:

  - name this computer as its Host (127.0.0.1 / localhost): no DNS rebinding, nothing from the local network;
  - carry the secret the desktop shell made for this launch (LUNAR_TOKEN) — the "mrsolis" cookie it gives its own
    windows, or the x-mrsolis header for its own checks — so other websites and programs are turned away;
  - in the installed app, come to a backend whose licence check passed (backend/gate.py).

HTML pages also get a Content-Security-Policy: only MrSOLIS's own scripts run, and pages can't send anything to
the internet, so even text injected through a slide could neither run nor leak anything.
"""
from __future__ import annotations

import hmac

_HOSTS = {"127.0.0.1", "localhost", "[::1]"}
CSP = ("default-src 'self'; script-src 'self' blob:; worker-src 'self' blob:; style-src 'self' 'unsafe-inline'; "
       "img-src 'self' data: blob:; media-src 'self' data: blob:; font-src 'self' data:; connect-src 'self'; "
       "object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'")


def _cookie(raw: str, name: str) -> str:
    for part in raw.split(";"):
        key, _, value = part.strip().partition("=")
        if key == name:
            return value
    return ""


async def _refuse(scope, receive, send, status: int, text: str):
    if scope["type"] == "websocket":
        await receive()                                    # websocket.connect, then turn it away
        await send({"type": "websocket.close", "code": 1008})
        return
    body = text.encode()
    await send({"type": "http.response.start", "status": status,
                "headers": [(b"content-type", b"text/plain; charset=utf-8"), (b"content-length", str(len(body)).encode())]})
    await send({"type": "http.response.body", "body": body})


class Guard:
    """ASGI middleware. token '' (a dev run without the desktop shell) skips the secret, never the Host check."""

    def __init__(self, app, token: str = "", licensed: bool = True):
        self.app, self.token, self.licensed = app, token, licensed

    async def __call__(self, scope, receive, send):
        if scope["type"] not in ("http", "websocket"):
            return await self.app(scope, receive, send)
        headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope.get("headers") or []}
        host = headers.get("host", "").lower()
        name = host[: host.find("]") + 1] if host.startswith("[") else host.split(":")[0]
        if name not in _HOSTS:
            return await _refuse(scope, receive, send, 421, "MrSOLIS only answers on this computer.")
        if self.token:
            given = _cookie(headers.get("cookie", ""), "mrsolis") or headers.get("x-mrsolis", "")
            if not hmac.compare_digest(given.encode(), self.token.encode()):
                return await _refuse(scope, receive, send, 403, "Only MrSOLIS's own windows may use this.")
        if not self.licensed:
            return await _refuse(scope, receive, send, 403, "MrSOLIS isn't activated on this computer.")
        if scope["type"] != "http":
            return await self.app(scope, receive, send)

        async def send_with_headers(msg):
            if msg["type"] == "http.response.start":
                hs = list(msg.get("headers") or [])
                ctype = next((v for k, v in hs if k.lower() == b"content-type"), b"")
                if ctype.startswith(b"text/html"):
                    hs.append((b"content-security-policy", CSP.encode()))
                hs.append((b"x-content-type-options", b"nosniff"))
                msg = {**msg, "headers": hs}
            await send(msg)

        return await self.app(scope, receive, send_with_headers)
