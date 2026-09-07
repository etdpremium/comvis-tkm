"""
app/schemas/activity.py — output untuk dashboard
"""
from __future__ import annotations
from pydantic import BaseModel
from datetime import datetime
from typing import Optional


class ActivityOut(BaseModel):
    id: int
    student_id: int
    student_name: str | None = None
    material_name: str | None = None
    zone_name: str | None = None
    started_at: datetime
    ended_at: Optional[datetime] = None
    duration_sec: int
    behavior: str
    aruco_id: Optional[int] = None


class StudentToday(BaseModel):
    student_id: int
    name: str
    date: str
    total_focus_min: float
    total_freeplay_min: float
    total_idle_min: float
    total_social_min: float
    total_transition_min: float
    materials: list[dict]
    zones: list[dict]
    behavior_breakdown: dict[str, float]


class DashboardWeek(BaseModel):
    class_id: int | None
    days: list[dict]  # [{date, total_focus_min, total_freeplay_min, students_count}]
