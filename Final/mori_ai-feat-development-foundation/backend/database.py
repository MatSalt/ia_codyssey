"""One session per operation; no global live connection at import time."""
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from backend.settings import Settings


def session_factory(database_url: str | None = None) -> async_sessionmaker[AsyncSession]:
    engine = create_async_engine(database_url or Settings().database_url, pool_pre_ping=True)
    return async_sessionmaker(engine, expire_on_commit=False)
