"""Bound concurrent node creation before opening a session or claiming a key."""
import asyncio
from contextlib import asynccontextmanager
import math
import os

from fastapi import HTTPException
from app.core.errors import error_detail


class NodeCreationAdmission:
    def __init__(self, capacity=32, max_waiting=512, wait_seconds=5.0):
        if capacity < 1 or max_waiting < 0 or not math.isfinite(wait_seconds) or wait_seconds <= 0:
            raise ValueError("Invalid node creation admission limits")
        self.capacity = capacity
        self.max_waiting = max_waiting
        self.wait_seconds = wait_seconds
        self._slots = asyncio.Semaphore(capacity)
        self.active = 0
        self.waiting = 0
        self.rejected = 0

    @classmethod
    def from_env(cls, prefix="NODE_CREATE"):
        return cls(int(os.getenv(prefix + "_CONCURRENCY", "32")),
                   int(os.getenv(prefix + "_MAX_WAITING", "512")),
                   float(os.getenv(prefix + "_WAIT_SECONDS", "5")))

    def _busy(self):
        self.rejected += 1
        raise HTTPException(503, detail=error_detail(
            "NODE_CREATION_BUSY", "Node creation is busy; retry with the same Idempotency-Key"),
            headers={"Retry-After": "1"})

    @asynccontextmanager
    async def enter(self):
        if self._slots.locked() and self.waiting >= self.max_waiting:
            self._busy()
        self.waiting += 1
        try:
            try:
                async with asyncio.timeout(self.wait_seconds):
                    await self._slots.acquire()
            except TimeoutError:
                self._busy()
        finally:
            self.waiting -= 1
        self.active += 1
        try:
            yield
        finally:
            self.active -= 1
            self._slots.release()
