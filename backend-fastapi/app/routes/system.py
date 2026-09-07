"""
app/routes/system.py — System monitoring (PRD F4.2)
- /api/v1/system/stats: combined health + counts
- /api/v1/system/workers: who's running (placeholder)
"""
from __future__ import annotations
from datetime import datetime, timezone, timedelta
from fastapi import APIRouter, Depends
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_session
from ..models import VisionIdEvent, Activity, VideoBatch, Student, Material
from ..auth import get_current_user
from ..models import User
from ..services.minio_service import minio_service
from ..config import settings

router = APIRouter(prefix="/api/v1/system", tags=["system"])


@router.get("/stats")
async def system_stats(
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    counts = {}
    for name, model in [
        ("students", Student),
        ("materials", Material),
        ("vision_id_events", VisionIdEvent),
        ("activities", Activity),
        ("video_batches", VideoBatch),
    ]:
        r = await session.execute(select(func.count()).select_from(model))
        counts[name] = r.scalar() or 0

    # MinIO storage usage
    storage = {}
    for b in (settings.minio_bucket_raw, settings.minio_bucket_annotated, settings.minio_bucket_models):
        try:
            objs = minio_service.list_objects(b, "", 1000)
            total = sum(o["size"] for o in objs)
            storage[b] = {"objects": len(objs), "bytes": total}
        except Exception:
            storage[b] = {"objects": 0, "bytes": 0}

    # Last 24h events
    since = datetime.now(timezone.utc) - timedelta(hours=24)
    r = await session.execute(select(func.count()).select_from(VisionIdEvent).where(VisionIdEvent.ts >= since))
    events_24h = r.scalar() or 0

    return {
        "ts": datetime.now(timezone.utc).isoformat(),
        "counts": counts,
        "storage": storage,
        "events_24h": events_24h,
        "config": {
            "minio_endpoint": settings.minio_endpoint,
            "postgres": f"{settings.postgres_user}@{settings.postgres_host}:{settings.postgres_port}/{settings.postgres_db}",
            "fps_target": settings.fps_target,
            "segment_seconds": settings.segment_seconds,
        },
    }
