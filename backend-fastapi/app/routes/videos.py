"""
app/routes/videos.py — upload + register
"""
from __future__ import annotations
import uuid
import os
from datetime import datetime, timezone
from pathlib import Path
from fastapi import APIRouter, Depends, UploadFile, File, HTTPException, BackgroundTasks
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_session
from ..models import VideoBatch, VideoStatus
from ..auth import require_teacher, require_service
from ..models import User
from ..services.minio_service import minio_service
from ..config import settings
from ..schemas.detection import DetectionAck

router = APIRouter(prefix="/api/v1/videos", tags=["videos"])

UPLOAD_DIR = Path("/tmp/tkm-uploads")
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)


@router.post("/upload", status_code=201)
async def upload_video(
    background: BackgroundTasks,
    file: UploadFile = File(...),
    class_id: int | None = None,
    camera_id: int | None = None,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_teacher),
):
    """Upload .mp4 raw → simpan lokal + register VideoBatch (status=uploaded)."""
    if not file.filename or not file.filename.lower().endswith((".mp4", ".mov", ".avi")):
        raise HTTPException(status_code=400, detail="File must be .mp4/.mov/.avi")
    safe_name = f"{int(datetime.now().timestamp())}_{uuid.uuid4().hex[:8]}_{Path(file.filename).name}"
    dest = UPLOAD_DIR / safe_name
    contents = await file.read()
    dest.write_bytes(contents)

    key = f"raw-videos/uploads/{safe_name}"
    try:
        minio_service.upload_file(dest, settings.minio_bucket_raw, key)
    except Exception as e:
        # Still keep DB record with local path; let worker pick up
        pass

    vb = VideoBatch(
        camera_id=camera_id,
        class_id=class_id,
        started_at=datetime.now(timezone.utc),
        duration_sec=0,
        fps=settings.fps_target,
        frames_total=0,
        detections_count=0,
        raw_s3_key=key,
        size_bytes=len(contents),
        status=VideoStatus.uploaded,
    )
    session.add(vb)
    await session.commit()
    await session.refresh(vb)

    background.add_task(_cleanup_local, str(dest))

    return {
        "id": vb.id,
        "raw_s3_key": key,
        "size_bytes": len(contents),
        "status": "uploaded",
        "presigned_url": minio_service.presigned_url(settings.minio_bucket_raw, key),
    }


def _cleanup_local(path: str) -> None:
    try:
        os.unlink(path)
    except OSError:
        pass


@router.get("", response_model=list)
async def list_videos(
    limit: int = 50,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_service),
):
    rows = (await session.execute(
        select(VideoBatch).order_by(VideoBatch.started_at.desc()).limit(limit)
    )).scalars().all()
    return [
        {
            "id": v.id,
            "started_at": v.started_at.isoformat(),
            "duration_sec": v.duration_sec,
            "fps": v.fps,
            "frames_total": v.frames_total,
            "detections_count": v.detections_count,
            "raw_s3_key": v.raw_s3_key,
            "annotated_s3_key": v.annotated_s3_key,
            "status": v.status.value,
            "size_bytes": v.size_bytes,
        }
        for v in rows
    ]


@router.post("/by-raw-key/annotate")
async def register_annotated_by_raw_key(
    raw_s3_key: str,
    annotated_s3_key: str,
    duration_sec: int,
    frames_total: int,
    detections_count: int = 0,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_service),
):
    res = await session.execute(
        select(VideoBatch).where(VideoBatch.raw_s3_key == raw_s3_key).order_by(VideoBatch.id.desc()).limit(1)
    )
    v: VideoBatch | None = res.scalar_one_or_none()
    if not v:
        # create one
        v = VideoBatch(
            started_at=datetime.now(timezone.utc),
            duration_sec=duration_sec,
            frames_total=frames_total,
            raw_s3_key=raw_s3_key,
            annotated_s3_key=annotated_s3_key,
            detections_count=detections_count,
            status=VideoStatus.done,
        )
        session.add(v)
    else:
        v.annotated_s3_key = annotated_s3_key
        v.duration_sec = duration_sec
        v.frames_total = frames_total
        v.detections_count = detections_count
        v.ended_at = datetime.now(timezone.utc)
        v.status = VideoStatus.done
    await session.commit()
    await session.refresh(v)
    return {"ok": True, "id": v.id, "annotated_url": minio_service.presigned_url(settings.minio_bucket_annotated, annotated_s3_key)}


@router.post("/{video_id}/annotate")
async def register_annotated(
    video_id: int,
    annotated_s3_key: str,
    duration_sec: int,
    frames_total: int,
    detections_count: int = 0,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_service),
):
    v = (await session.execute(select(VideoBatch).where(VideoBatch.id == video_id))).scalar_one_or_none()
    if not v:
        raise HTTPException(status_code=404, detail="Video not found")
    v.annotated_s3_key = annotated_s3_key
    v.duration_sec = duration_sec
    v.frames_total = frames_total
    v.detections_count = detections_count
    v.ended_at = datetime.now(timezone.utc)
    v.status = VideoStatus.done
    await session.commit()
    return {"ok": True, "id": v.id, "annotated_url": minio_service.presigned_url(settings.minio_bucket_annotated, annotated_s3_key)}
