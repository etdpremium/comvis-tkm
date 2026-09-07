"""
app/routes/cameras.py
"""
from __future__ import annotations
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_session
from ..models import Camera
from ..auth import get_current_user, require_teacher
from ..models import User

router = APIRouter(prefix="/api/v1/cameras", tags=["cameras"])


@router.get("")
async def list_cameras(
    class_id: int | None = None,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    stmt = select(Camera)
    if class_id is not None:
        stmt = stmt.where(Camera.class_id == class_id)
    rows = (await session.execute(stmt.order_by(Camera.name))).scalars().all()
    return [
        {
            "id": c.id, "name": c.name, "rtsp_url": c.rtsp_url,
            "class_id": c.class_id, "location": c.location, "fps": c.fps,
            "is_active": c.is_active, "resolution_w": c.resolution_w, "resolution_h": c.resolution_h,
        }
        for c in rows
    ]


@router.post("", status_code=201)
async def create_camera(
    name: str,
    class_id: int,
    rtsp_url: str | None = None,
    location: str | None = None,
    fps: int = 15,
    resolution_w: int = 1280,
    resolution_h: int = 720,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_teacher),
):
    c = Camera(
        name=name, class_id=class_id, rtsp_url=rtsp_url, location=location,
        fps=fps, resolution_w=resolution_w, resolution_h=resolution_h,
    )
    session.add(c)
    await session.commit()
    await session.refresh(c)
    return {"id": c.id}
