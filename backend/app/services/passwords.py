"""Bound password work without blocking the event loop or holding a DB session."""
import anyio
from passlib.context import CryptContext

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
limiter = anyio.CapacityLimiter(4)
DUMMY_HASH = "$2b$12$LQv3c1yqBWVHxkd0LHAkCOYz6TtxCsy.vBW5cvM3MYC9e3YuXYE6G"


async def hash_password(password: str) -> str:
    return await anyio.to_thread.run_sync(pwd_context.hash, password, limiter=limiter)


def _verify(password: str, hashed: str) -> bool:
    try:
        return pwd_context.verify(password, hashed)
    except (ValueError, TypeError):
        return False


async def verify_password(password: str, hashed: str) -> bool:
    return await anyio.to_thread.run_sync(_verify, password, hashed, limiter=limiter)
