from collections.abc import AsyncIterator
from sqlalchemy.ext.asyncio import AsyncSession
from app.db.session import AsyncSessionLocal


async def get_db() -> AsyncIterator[AsyncSession]:
    """Share session lifetime; transactions remain owned by each operation."""
    async with AsyncSessionLocal() as session:
        yield session
