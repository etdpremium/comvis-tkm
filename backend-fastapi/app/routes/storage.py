"""
app/routes/storage.py — MinIO bucket listing
PRD F4 — Admin lihat isi MinIO via dashboard.
"""
from __future__ import annotations
from fastapi import APIRouter, Depends, HTTPException
from ..services.minio_service import minio_service
from ..auth import require_admin
from ..config import settings
from ..models import User

router = APIRouter(prefix="/api/v1/storage", tags=["storage"])


@router.get("/buckets")
async def list_buckets(user: User = Depends(require_admin)):
    try:
        return {"buckets": [b["Name"] for b in minio_service.client.list_buckets().get("Buckets", [])]}
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"MinIO: {e}")


@router.get("/objects")
async def list_objects(
    bucket: str,
    prefix: str = "",
    limit: int = 100,
    user: User = Depends(require_admin),
):
    if bucket not in (settings.minio_bucket_raw, settings.minio_bucket_annotated, settings.minio_bucket_models):
        raise HTTPException(status_code=400, detail="Unknown bucket")
    return {"bucket": bucket, "prefix": prefix, "objects": minio_service.list_objects(bucket, prefix, limit)}
