"""
Async SQLAlchemy engine/session setup for the running app. Alembic
migrations use a separate *sync* engine (see alembic/env.py) because
Alembic's migration runner is sync by design -- the two are intentionally
independent.
"""
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import settings


engine = create_async_engine(
    settings.async_database_url, echo=False, future=True, connect_args=settings.asyncpg_connect_args
)
AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


async def get_db() -> AsyncSession:
    """FastAPI dependency: one AsyncSession per request, closed afterwards."""
    async with AsyncSessionLocal() as session:
        yield session