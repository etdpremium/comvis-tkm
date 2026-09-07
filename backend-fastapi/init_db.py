"""
backend-fastapi/init_db.py — Initialize Postgres schema (PRD F1.2)
Jalankan sekali setelah docker compose up: `python init_db.py`
"""
from __future__ import annotations
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy import text
from app.config import settings

# IMPORTANT: import models so SQLAlchemy registers them on Base.metadata
from app.db import Base
from app import models  # noqa: F401  -- ensure all tables registered


async def main():
    eng = create_async_engine(settings.database_url, echo=False)
    print("Creating schema...")
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with eng.connect() as c:
        r = await c.execute(text(
            "SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename"
        ))
        tables = [row[0] for row in r]
    await eng.dispose()
    print(f"OK: {len(tables)} tables")
    for t in tables:
        print(f"  - {t}")


if __name__ == "__main__":
    asyncio.run(main())
