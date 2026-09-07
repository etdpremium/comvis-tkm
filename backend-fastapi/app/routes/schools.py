"""
app/routes/schools.py
"""
from __future__ import annotations
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_session
from ..models import School, ClassRoom
from ..auth import get_current_user, require_teacher
from ..models import User

router = APIRouter(prefix="/api/v1/schools", tags=["schools"])


@router.get("")
async def list_schools(
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    rows = (await session.execute(select(School).order_by(School.name))).scalars().all()
    return [{"id": s.id, "name": s.name, "address": s.address} for s in rows]


@router.post("", status_code=201)
async def create_school(
    name: str,
    address: str | None = None,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_teacher),
):
    s = School(name=name, address=address)
    session.add(s)
    await session.commit()
    await session.refresh(s)
    return {"id": s.id, "name": s.name}


@router.get("/{school_id}/classes")
async def list_classes(
    school_id: int,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    rows = (await session.execute(
        select(ClassRoom).where(ClassRoom.school_id == school_id).order_by(ClassRoom.name)
    )).scalars().all()
    return [{"id": c.id, "name": c.name, "grade": c.grade} for c in rows]


@router.post("/{school_id}/classes", status_code=201)
async def create_class(
    school_id: int,
    name: str,
    grade: str,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_teacher),
):
    c = ClassRoom(name=name, grade=grade, school_id=school_id)
    session.add(c)
    await session.commit()
    await session.refresh(c)
    return {"id": c.id, "name": c.name, "grade": c.grade}
