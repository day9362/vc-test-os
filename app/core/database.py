from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings

_connect = {}
if settings.database_search_path:
    _connect["server_settings"] = {"search_path": settings.database_search_path}

engine = create_async_engine(settings.database_url, pool_pre_ping=True, connect_args=_connect)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False)


async def get_session() -> AsyncIterator[AsyncSession]:
    async with SessionLocal() as session:
        yield session
