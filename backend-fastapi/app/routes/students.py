"""
app/routes/students.py — CRUD + ArUco assign
"""
from __future__ import annotations
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional

from ..db import get_session
from ..models import Student
from ..schemas import StudentCreate, StudentOut, ArucoAssign
from ..auth import get_current_user, require_teacher, require_service
from ..models import User

router = APIRouter(prefix="/api/v1/students", tags=["students"])


@router.get("", response_model=list[StudentOut])
async def list_students(
    class_id: Optional[int] = None,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    stmt = select(Student)
    if class_id is not None:
        stmt = stmt.where(Student.class_id == class_id)
    rows = (await session.execute(stmt.order_by(Student.name))).scalars().all()
    return rows


@router.post("", response_model=StudentOut, status_code=201)
async def create_student(
    payload: StudentCreate,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_teacher),
):
    s = Student(**payload.model_dump())
    session.add(s)
    await session.commit()
    await session.refresh(s)
    return s


@router.get("/{student_id}", response_model=StudentOut)
async def get_student(
    student_id: int,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    s = (await session.execute(select(Student).where(Student.id == student_id))).scalar_one_or_none()
    if not s:
        raise HTTPException(status_code=404, detail="Student not found")
    return s


@router.put("/{student_id}", response_model=StudentOut)
async def update_student(
    student_id: int,
    payload: StudentCreate,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_teacher),
):
    s = (await session.execute(select(Student).where(Student.id == student_id))).scalar_one_or_none()
    if not s:
        raise HTTPException(status_code=404, detail="Student not found")
    for k, v in payload.model_dump().items():
        setattr(s, k, v)
    await session.commit()
    await session.refresh(s)
    return s


@router.delete("/{student_id}", status_code=204)
async def delete_student(
    student_id: int,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_teacher),
):
    s = (await session.execute(select(Student).where(Student.id == student_id))).scalar_one_or_none()
    if not s:
        raise HTTPException(status_code=404, detail="Student not found")
    await session.delete(s)
    await session.commit()
    return None


@router.post("/aruco", response_model=StudentOut)
async def assign_aruco(
    payload: ArucoAssign,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_teacher),
):
    """Map aruco_id → student name (creates student if not exists)."""
    stmt = select(Student).where(Student.name == payload.student)
    s = (await session.execute(stmt)).scalar_one_or_none()
    if s is None:
        # create in default class 1 (caller should pre-create)
        s = Student(name=payload.student, aruco_id=payload.aruco_id, class_id=1)
        session.add(s)
    else:
        s.aruco_id = payload.aruco_id
    await session.commit()
    await session.refresh(s)
    return s
