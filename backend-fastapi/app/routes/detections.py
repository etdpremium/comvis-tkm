"""
app/routes/detections.py — POST /api/v1/detections — batch ingest dari worker
PRD F1.2 routes/detections
"""
from __future__ import annotations
import logging
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, Header
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Annotated

from ..db import get_session
from ..models import (
    VisionIdEvent, Activity, Student, Material, Zone, EventType,
    User, VideoBatch, VideoStatus,
)
from ..schemas import DetectionBatch, DetectionAck
from ..auth import require_service
from ..services.summarizer import summarizer

log = logging.getLogger("tkm.detections")
router = APIRouter(prefix="/api/v1/detections", tags=["detections"])


async def _resolve_ids(
    session: AsyncSession, detections: list, arucos: list
) -> tuple[dict[str, int], dict[int, int], dict[int, int]]:
    class_names = {d.class_name for d in detections if d.class_name}
    materials = {}
    if class_names:
        rows = (await session.execute(select(Material).where(Material.name.in_(class_names)))).scalars().all()
        materials = {m.name: m.id for m in rows}
    arucos_set = {a.aruco_id for a in arucos}
    aruco_map: dict[int, int] = {}
    if arucos_set:
        rows = (await session.execute(select(Student).where(Student.aruco_id.in_(arucos_set)))).scalars().all()
        aruco_map = {s.aruco_id: s.id for s in rows}
    zones: dict[int, int] = {}
    return materials, aruco_map, zones


@router.post("", response_model=DetectionAck)
async def post_detections(
    payload: DetectionBatch,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_service),
):
    materials, aruco_map, _ = await _resolve_ids(session, payload.detections, payload.aruco_detections)

    # Auto-create VideoBatch row if worker references unknown video_batch_id.
    # Worker memakai timestamp sebagai id segmen -> cocokkan via raw_s3_key agar
    # semua POST satu segmen jatuh ke SATU baris (bukan satu baris per POST).
    # Pakai ON CONFLICT (Postgres UPSERT) + row lock untuk menghindari race
    # antar-POST paralel (sebelumnya 92 row duplikat untuk 1 segmen).
    from sqlalchemy.dialects.postgresql import insert as pg_insert
    video_batch_db_id: int | None = None
    if payload.video_batch_id is not None:
        raw_key = f"auto/{payload.video_batch_id}"
        stmt = pg_insert(VideoBatch).values(
            started_at=payload.ts,
            duration_sec=0,
            fps=15,
            raw_s3_key=raw_key,
            status=VideoStatus.processing,
        ).on_conflict_do_nothing(index_elements=["raw_s3_key"])
        await session.execute(stmt)
        await session.commit()
        existing = (await session.execute(
            select(VideoBatch).where(VideoBatch.raw_s3_key == raw_key).order_by(VideoBatch.id.desc())
        )).scalars().first()
        if existing is not None:
            video_batch_db_id = existing.id

    rows: list[VisionIdEvent] = []
    aruco_to_track: dict[int, int] = {}
    for d in payload.detections:
        rows.append(VisionIdEvent(
            ts=payload.ts,
            camera_id=int(payload.camera_id) if (payload.camera_id and payload.camera_id.isdigit()) else None,
            video_batch_id=video_batch_db_id,
            student_id=None,
            material_id=materials.get(d.class_name),
            zone_id=d.zone_id,
            event_type=EventType.object_seen,
            track_id=d.track_id,
            class_name=d.class_name,
            confidence=d.confidence,
            bbox=d.bbox,
            extra=d.extra,
        ))
    for a in payload.aruco_detections:
        student_id = aruco_map.get(a.aruco_id)
        rows.append(VisionIdEvent(
            ts=a.ts or payload.ts,
            camera_id=int(payload.camera_id) if (payload.camera_id and payload.camera_id.isdigit()) else None,
            video_batch_id=video_batch_db_id,
            student_id=student_id,
            material_id=None,
            zone_id=None,
            event_type=EventType.aruco_seen,
            track_id=-1,
            class_name=f"aruco_{a.aruco_id}",
            confidence=a.confidence,
            bbox=a.bbox,
            xyz=a.xyz,
            extra={"aruco_id": a.aruco_id},
        ))
        aruco_to_track[a.aruco_id] = -1

    # Heartbeat when no detections (for monitoring)
    if not rows:
        rows.append(VisionIdEvent(
            ts=payload.ts,
            camera_id=int(payload.camera_id) if (payload.camera_id and payload.camera_id.isdigit()) else None,
            video_batch_id=video_batch_db_id,
            class_name="__heartbeat__",
            confidence=0.0,
            bbox=[],
            event_type=EventType.person_seen,
            extra={"frame": payload.frame, "no_detections": True},
        ))

    if rows:
        session.add_all(rows)
        await session.commit()

    # Crude PROX 80 association: latest aruco → latest track (POC)
    if aruco_to_track and payload.detections and video_batch_db_id is not None:
        latest_track = max(payload.detections, key=lambda d: d.track_id)
        latest_aruco = payload.aruco_detections[-1] if payload.aruco_detections else None
        if latest_aruco:
            student_id = aruco_map.get(latest_aruco.aruco_id)
            if student_id is not None:
                await session.execute(
                    VisionIdEvent.__table__.update()
                    .where(VisionIdEvent.track_id == latest_track.track_id)
                    .where(VisionIdEvent.video_batch_id == video_batch_db_id)
                    .values(student_id=student_id)
                )
                await session.commit()

    return DetectionAck(ok=True, tracked=len(payload.detections), aruco=len(payload.aruco_detections), activities=0)
