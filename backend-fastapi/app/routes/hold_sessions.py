"""
app/routes/hold_sessions.py — Hold session: anak pegang barang (open → kembalikan/timeout).

Endpoint:
  POST /api/v1/hold-sessions   — bulk insert dari worker (X-Service-Key)
  GET  /api/v1/hold-sessions   — list (auth, filter by video_id / class_id)
  GET  /api/v1/hold-sessions/summary — agregat per orang × barang (untuk dashboard)
"""
from __future__ import annotations
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Header, Query
from pydantic import BaseModel, Field
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_session
from ..models import HoldSession, VideoBatch, User
from ..auth import get_current_user

router = APIRouter(prefix="/api/v1/hold-sessions", tags=["hold-sessions"])


class HoldSessionIn(BaseModel):
    person_track_id: int
    object_track_id: int
    object_class: str
    open_ts: float
    close_ts: float
    duration_sec: float
    end_reason: str = Field(pattern=r"^(timeout|returned_to_rak|segment_end)$")


class HoldSessionBulkIn(BaseModel):
    video_id: int
    sessions: list[HoldSessionIn]


@router.post("", status_code=201)
async def create_hold_sessions(
    payload: HoldSessionBulkIn,
    session: AsyncSession = Depends(get_session),
    x_service_key: Optional[str] = Header(None, alias="X-Service-Key"),
):
    """Worker push bulk hold-sessions yang ditutup selama satu segment."""
    if not x_service_key or x_service_key.strip() == "":
        raise HTTPException(status_code=401, detail="Service key required")

    # Lookup video_batch_id (FK). Kalau tidak ketemu → simpan tanpa FK (NULL).
    vb = (await session.execute(
        select(VideoBatch).where(VideoBatch.id == payload.video_id)
    )).scalar_one_or_none()
    if vb is None:
        raise HTTPException(status_code=404, detail=f"VideoBatch {payload.video_id} tidak ditemukan")

    now = datetime.now(timezone.utc)
    rows = []
    for s in payload.sessions:
        rows.append(HoldSession(
            video_batch_id=vb.id,
            person_track_id=s.person_track_id,
            object_track_id=s.object_track_id,
            object_class=s.object_class,
            open_ts=s.open_ts,
            close_ts=s.close_ts,
            duration_sec=s.duration_sec,
            end_reason=s.end_reason,
            created_at=now,
        ))
    session.add_all(rows)
    await session.commit()
    return {"ok": True, "inserted": len(rows)}


@router.get("")
async def list_hold_sessions(
    video_id: Optional[int] = Query(None),
    object_class: Optional[str] = Query(None),
    limit: int = Query(200, ge=1, le=1000),
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    stmt = select(HoldSession)
    if video_id is not None:
        stmt = stmt.where(HoldSession.video_batch_id == video_id)
    if object_class is not None:
        stmt = stmt.where(HoldSession.object_class == object_class)
    stmt = stmt.order_by(HoldSession.created_at.desc()).limit(limit)
    rows = (await session.execute(stmt)).scalars().all()
    return [
        {
            "id": r.id,
            "video_batch_id": r.video_batch_id,
            "person_track_id": r.person_track_id,
            "object_track_id": r.object_track_id,
            "object_class": r.object_class,
            "open_ts": r.open_ts,
            "close_ts": r.close_ts,
            "duration_sec": r.duration_sec,
            "end_reason": r.end_reason,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in rows
    ]


@router.get("/summary")
async def summary_hold_sessions(
    video_id: Optional[int] = Query(None),
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    """Agregat per (person_track_id, object_class): total sesi, total durasi,
    rata-rata durasi, dan breakdown end_reason. Untuk tabel 'Durasi ambil → kembalikan'."""
    stmt = select(
        HoldSession.person_track_id,
        HoldSession.object_class,
        func.count(HoldSession.id).label("n_sessions"),
        func.sum(HoldSession.duration_sec).label("total_sec"),
        func.avg(HoldSession.duration_sec).label("avg_sec"),
        func.max(HoldSession.duration_sec).label("max_sec"),
    ).group_by(
        HoldSession.person_track_id, HoldSession.object_class
    )
    if video_id is not None:
        stmt = stmt.where(HoldSession.video_batch_id == video_id)
    stmt = stmt.order_by(func.sum(HoldSession.duration_sec).desc())
    rows = (await session.execute(stmt)).all()

    # End-reason breakdown per group
    er_stmt = select(
        HoldSession.person_track_id,
        HoldSession.object_class,
        HoldSession.end_reason,
        func.count(HoldSession.id),
    ).group_by(
        HoldSession.person_track_id, HoldSession.object_class, HoldSession.end_reason
    )
    if video_id is not None:
        er_stmt = er_stmt.where(HoldSession.video_batch_id == video_id)
    er_rows = (await session.execute(er_stmt)).all()
    er_map: dict[tuple[int, str], dict[str, int]] = {}
    for pid, cls, reason, n in er_rows:
        er_map.setdefault((pid, cls), {})[reason] = int(n)

    out = []
    for pid, cls, n, tot, avg, mx in rows:
        out.append({
            "person_track_id": int(pid),
            "object_class": cls,
            "n_sessions": int(n),
            "total_sec": round(float(tot or 0), 1),
            "avg_sec": round(float(avg or 0), 1),
            "max_sec": round(float(mx or 0), 1),
            "end_reasons": er_map.get((pid, cls), {}),
        })
    return out
