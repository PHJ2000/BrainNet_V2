"""Per-process admission and body limits, applied before authentication parsing.

Client IP is ASGI's verified peer address; never trust arbitrary forwarded headers.
Across replicas, put a shared rate limiter at the ingress as well.
"""
import asyncio
import math
import time
from collections import OrderedDict

from starlette.responses import JSONResponse
from app.core.config import positive_int_env
from app.core.trace import current_trace_id


class RequestLimits:
    def __init__(self, app):
        self.app = app
        self.limit = positive_int_env("AUTH_REQUESTS_PER_MINUTE", "60")
        self.capacity = positive_int_env("AUTH_MAX_INFLIGHT", "32")
        self.max_body = positive_int_env("AUTH_MAX_BODY_BYTES", "16384")
        self.active = 0
        self.buckets = OrderedDict()

    def retry_after(self, key):
        now = time.monotonic()
        while self.buckets and next(iter(self.buckets.values()))[0] <= now:
            self.buckets.popitem(last=False)
        expires, count = self.buckets.get(key, (now + 60, 0))
        if count >= self.limit or (key not in self.buckets and len(self.buckets) >= 10000):
            return max(1, math.ceil(expires - now))
        self.buckets[key] = (expires, count + 1)
        return 0

    async def __call__(self, scope, receive, send):
        path = scope.get("path", "").rstrip("/")
        if (scope["type"] != "http" or scope.get("method") != "POST"
                or path not in ("/auth/login", "/auth/register", "/projects/join")):
            return await self.app(scope, receive, send)

        async def reject(status, code, message, retry=None):
            headers = {"Retry-After": str(retry)} if retry else {}
            response = JSONResponse({"code": code, "message": message,
                                     "trace_id": current_trace_id()}, status_code=status, headers=headers)
            await response(scope, receive, send)

        key = (scope.get("client") or ("unknown",))[0]
        retry = self.retry_after(key)
        if retry or self.active >= self.capacity:
            return await reject(429, "RATE_LIMITED", "Too many authentication requests", retry or 1)
        self.active += 1
        try:
            length = dict(scope["headers"]).get(b"content-length")
            if length is not None:
                try:
                    size = int(length)
                except ValueError:
                    return await reject(400, "BAD_REQUEST", "Invalid Content-Length")
                if size < 0:
                    return await reject(400, "BAD_REQUEST", "Invalid Content-Length")
                if size > self.max_body:
                    return await reject(413, "REQUEST_TOO_LARGE", "Authentication request is too large")
            body = bytearray()
            try:
                async with asyncio.timeout(10):
                    while True:
                        message = await receive()
                        if message["type"] == "http.disconnect":
                            return
                        body.extend(message.get("body", b""))
                        if len(body) > self.max_body:
                            return await reject(413, "REQUEST_TOO_LARGE", "Authentication request is too large")
                        if not message.get("more_body", False):
                            break
            except TimeoutError:
                return await reject(408, "REQUEST_TIMEOUT", "Authentication body timed out")
            delivered = False

            async def bounded_receive():
                nonlocal delivered
                if delivered:
                    return await receive()
                delivered = True
                return {"type": "http.request", "body": bytes(body), "more_body": False}

            await self.app(scope, bounded_receive, send)
        finally:
            self.active -= 1
