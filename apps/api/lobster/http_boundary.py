"""Bounded local HTTP boundary. Public hosting still requires separate controls."""

import asyncio

from starlette.datastructures import Headers, MutableHeaders
from starlette.responses import JSONResponse

LOCAL_ORIGINS = {"http://127.0.0.1:3000", "http://localhost:3000",
                 "http://127.0.0.1:8000", "http://localhost:8000"}
MAX_BODY_BYTES = 65536


class LocalBoundary:
    def __init__(self, app, max_body_bytes: int = MAX_BODY_BYTES, body_timeout: float = 5):
        self.app = app
        self.max_body_bytes = max_body_bytes
        self.body_timeout = body_timeout

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def guarded_send(message):
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                headers["Cache-Control"] = "no-store"
                headers["X-Content-Type-Options"] = "nosniff"
                headers["Referrer-Policy"] = "no-referrer"
            await send(message)

        async def refuse(status, detail):
            await JSONResponse({"detail": detail}, status_code=status)(scope, receive, guarded_send)

        headers = Headers(scope=scope)
        origins = headers.getlist("origin")
        if len(origins) > 1 or origins and origins[0] not in LOCAL_ORIGINS:
            await refuse(403, "Only the configured loopback browser origins may access this local API.")
            return
        lengths = headers.getlist("content-length")
        if len(lengths) > 1 or lengths and (len(lengths[0]) > 20 or not lengths[0].isascii() or not lengths[0].isdigit()):
            await refuse(400, "Invalid Content-Length.")
            return
        if lengths and int(lengths[0]) > self.max_body_bytes:
            await refuse(413, "Request body exceeds the 64 KiB local API limit.")
            return
        if scope["method"] not in {"POST", "PUT", "PATCH", "DELETE"}:
            await self.app(scope, receive, guarded_send)
            return
        body = bytearray()
        try:
            async with asyncio.timeout(self.body_timeout):
                while True:
                    message = await receive()
                    if message["type"] == "http.disconnect":
                        return
                    chunk = message.get("body", b"")
                    if len(body) + len(chunk) > self.max_body_bytes:
                        await refuse(413, "Request body exceeds the 64 KiB local API limit.")
                        return
                    body.extend(chunk)
                    if not message.get("more_body", False):
                        break
        except TimeoutError:
            await refuse(408, "Request body did not arrive within the local API time limit.")
            return
        delivered = False

        async def replay():
            nonlocal delivered
            if not delivered:
                delivered = True
                return {"type": "http.request", "body": bytes(body), "more_body": False}
            return await receive()

        await self.app(scope, replay, guarded_send)
