"""
app/routes/materials.py
"""
from __future__ import annotations
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_session
from ..models import Material
from ..schemas import MaterialCreate, MaterialOut
from ..auth import get_current_user, require_teacher
from ..models import User

router = APIRouter(prefix="/api/v1/materials", tags=["materials"])


@router.get("", response_model=list[MaterialOut])
async def list_materials(
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    rows = (await session.execute(select(Material).order_by(Material.name))).scalars().all()
    return rows


@router.post("", response_model=MaterialOut, status_code=201)
async def create_material(
    payload: MaterialCreate,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_teacher),
):
    m = Material(**payload.model_dump())
    session.add(m)
    try:
        await session.commit()
    except Exception:
        await session.rollback()
        raise HTTPException(status_code=409, detail="Material name exists")
    await session.refresh(m)
    return m
