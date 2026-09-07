"""
app/routes/zones.py
"""
from __future__ import annotations
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_session
from ..models import Zone
from ..schemas import ZoneCreate, ZoneOut
from ..auth import get_current_user, require_teacher
from ..models import User

router = APIRouter(prefix="/api/v1/zones", tags=["zones"])


@router.get("", response_model=list[ZoneOut])
async def list_zones(
    class_id: int | None = None,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    stmt = select(Zone)
    if class_id is not None:
        stmt = stmt.where(Zone.class_id == class_id)
    rows = (await session.execute(stmt.order_by(Zone.name))).scalars().all()
    return rows


@router.post("", response_model=ZoneOut, status_code=201)
async def create_zone(
    payload: ZoneCreate,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_teacher),
):
    z = Zone(**payload.model_dump())
    session.add(z)
    await session.commit()
    await session.refresh(z)
    return z


@router.get("/{zone_id}", response_model=ZoneOut)
async def get_zone(
    zone_id: int,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    z = (await session.execute(select(Zone).where(Zone.id == zone_id))).scalar_one_or_none()
    if not z:
        raise HTTPException(status_code=404, detail="Zone not found")
    return z


@router.get("/{zone_id}/polygon", response_model=list)
async def get_zone_polygon(
    zone_id: int,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    z = (await session.execute(select(Zone).where(Zone.id == zone_id))).scalar_one_or_none()
    if not z:
        raise HTTPException(status_code=404, detail="Zone not found")
    return z.polygon
