import os
from typing import Tuple, Dict, Any
import sqlalchemy
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy import text
from models import Base

DATABASE_URL_RAW = os.getenv("DATABASE_URL", "postgresql+asyncpg://postgres:admin@127.0.0.1:5432/postgres")

def _normalize_db_url(url: str) -> str:
    try:
        if url.startswith("postgres://"):
            return "postgresql+asyncpg://" + url[len("postgres://"):]
        if url.startswith("postgresql://") and "+" not in url.split("://",1)[0]:
            # postgres variant without driver
            return "postgresql+asyncpg://" + url[len("postgresql://"):]
        return url
    except Exception:
        return url

DATABASE_URL = _normalize_db_url(DATABASE_URL_RAW)

_engine = None
_Session: async_sessionmaker[AsyncSession] | None = None

async def init_db() -> None:
    global _engine, _Session
    if _engine is None:
        _engine = create_async_engine(DATABASE_URL, echo=False, future=True)
        _Session = async_sessionmaker(_engine, expire_on_commit=False)
    # Auto-create tables for development; prefer Alembic in production
    async with _engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

async def get_session() -> AsyncSession:
    if _Session is None:
        await init_db()
    assert _Session is not None
    return _Session()

async def db_health() -> Tuple[bool, Dict[str, Any]]:
    try:
        if _engine is None:
            await init_db()
        assert _engine is not None
        async with _engine.connect() as conn:
            res = await conn.execute(text("SELECT 'ok'::text, current_database(), current_user"))
            row = res.first()
            return True, {"status": row[0], "database": row[1], "user": row[2]}
    except Exception as e:
        return False, {"error": str(e)}

async def reset_db() -> Tuple[bool, str]:
    try:
        if _engine is None:
            await init_db()
        assert _engine is not None
        async with _engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
            await conn.run_sync(Base.metadata.create_all)
        return True, "reset"
    except Exception as e:
        return False, str(e)
