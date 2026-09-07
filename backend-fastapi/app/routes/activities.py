"""
app/routes/activities.py
"""
from __future__ import annotations
from datetime import datetime, timezone, timedelta
from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_session
from ..models import Activity, Student, Material, Zone
from ..schemas import ActivityOut
from ..auth import get_current_user
from ..models import User

router = APIRouter(prefix="/api/v1/activities", tags=["activities"])


@router.get("", response_model=list[ActivityOut])
async def list_activities(
    student_id: int | None = None,
    class_id: int | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    limit: int = Query(200, le=1000),
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    stmt = select(Activity, Student.name, Material.name, Zone.name).outerjoin(
        Student, Activity.student_id == Student.id
    ).outerjoin(Material, Activity.material_id == Material.id).outerjoin(
        Zone, Activity.zone_id == Zone.id
    )
    if student_id is not None:
        stmt = stmt.where(Activity.student_id == student_id)
    if class_id is not None:
        stmt = stmt.where(Activity.class_id == class_id)
    if date_from is not None:
        stmt = stmt.where(Activity.started_at >= date_from)
    if date_to is not None:
        stmt = stmt.where(Activity.started_at <= date_to)
    stmt = stmt.order_by(Activity.started_at.desc()).limit(limit)
    rows = (await session.execute(stmt)).all()
    out: list[ActivityOut] = []
    for a, sname, mname, zname in rows:
        out.append(ActivityOut(
            id=a.id,
            student_id=a.student_id,
            student_name=sname,
            material_name=mname,
            zone_name=zname,
            started_at=a.started_at,
            ended_at=a.ended_at,
            duration_sec=a.duration_sec,
            behavior=a.behavior.value if hasattr(a.behavior, "value") else str(a.behavior),
            aruco_id=a.aruco_id,
        ))
    return out
