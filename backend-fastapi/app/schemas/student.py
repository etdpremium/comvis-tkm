"""
app/schemas/student.py
"""
from __future__ import annotations
from pydantic import BaseModel
from datetime import datetime
from typing import Optional


class StudentCreate(BaseModel):
    name: str
    nis: Optional[str] = None
    aruco_id: Optional[int] = None
    class_id: int
    is_active: bool = True


class StudentOut(BaseModel):
    id: int
    name: str
    nis: Optional[str] = None
    aruco_id: Optional[int] = None
    class_id: int
    is_active: bool
    created_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class ArucoAssign(BaseModel):
    aruco_id: int
    student: str
