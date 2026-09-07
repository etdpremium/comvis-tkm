"""
backend-fastapi/app/db.py — SQLAlchemy 2.0 async engine + session factory
"""
from __future__ import annotations
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase
from .config import settings


class Base(DeclarativeBase):
    pass


engine = create_async_engine(
    settings.database_url,
    echo=settings.debug,
    pool_size=10,
    max_overflow=20,
    pool_pre_ping=True,
)

SessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)


async def get_session() -> AsyncSession:
    async with SessionLocal() as session:
        yield session
