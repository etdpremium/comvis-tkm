"""
app/models/event.py — VisionIdEvent (raw detection) + Activity (aggregated)
"""
from __future__ import annotations
import enum
from datetime import datetime
from sqlalchemy import String, ForeignKey, Integer, Float, JSON, DateTime, Enum as SAEnum, BigInteger
from sqlalchemy.orm import Mapped, mapped_column
from app.db import Base
from app.models.base import TimestampMixin


class EventType(str, enum.Enum):
    person_seen = "person_seen"
    object_seen = "object_seen"
    aruco_seen = "aruco_seen"
    zone_enter = "zone_enter"
    zone_exit = "zone_exit"
    pick_up = "pick_up"
    return_object = "return_object"


class VisionIdEvent(Base):
    """Raw detection event dari worker — high volume."""
    __tablename__ = "vision_id_events"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    camera_id: Mapped[int | None] = mapped_column(ForeignKey("cameras.id", ondelete="SET NULL"), nullable=True, index=True)
    class_id: Mapped[int | None] = mapped_column(ForeignKey("classes.id", ondelete="SET NULL"), nullable=True, index=True)
    video_batch_id: Mapped[int | None] = mapped_column(ForeignKey("video_batches.id", ondelete="SET NULL"), nullable=True, index=True)
    student_id: Mapped[int | None] = mapped_column(ForeignKey("students.id", ondelete="SET NULL"), nullable=True, index=True)
    material_id: Mapped[int | None] = mapped_column(ForeignKey("materials.id", ondelete="SET NULL"), nullable=True, index=True)
    zone_id: Mapped[int | None] = mapped_column(ForeignKey("zones.id", ondelete="SET NULL"), nullable=True, index=True)
    event_type: Mapped[EventType] = mapped_column(SAEnum(EventType, name="event_type"), nullable=False, index=True)
    track_id: Mapped[int] = mapped_column(Integer, default=-1, nullable=False)
    class_name: Mapped[str] = mapped_column(String(50), nullable=False)
    confidence: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    bbox: Mapped[list] = mapped_column(JSON, nullable=False)  # [x1,y1,x2,y2]
    xyz: Mapped[list | None] = mapped_column(JSON, nullable=True)  # ArUco POSIT (skip dulu)
    extra: Mapped[dict | None] = mapped_column(JSON, nullable=True)


class BehaviorType(str, enum.Enum):
    focused_work = "focused_work"
    free_play = "free_play"
    transition = "transition"
    idle = "idle"
    social = "social"


class Activity(Base):
    """Aggregated activity per (student, material, zone) dengan durasi."""
    __tablename__ = "activities"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    student_id: Mapped[int] = mapped_column(ForeignKey("students.id", ondelete="CASCADE"), nullable=False, index=True)
    class_id: Mapped[int] = mapped_column(ForeignKey("classes.id", ondelete="CASCADE"), nullable=False, index=True)
    material_id: Mapped[int | None] = mapped_column(ForeignKey("materials.id", ondelete="SET NULL"), nullable=True)
    zone_id: Mapped[int | None] = mapped_column(ForeignKey("zones.id", ondelete="SET NULL"), nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    duration_sec: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    behavior: Mapped[BehaviorType] = mapped_column(
        SAEnum(BehaviorType, name="behavior_type"), default=BehaviorType.transition, nullable=False
    )
    aruco_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)


class HoldSession(Base):
    """Satu siklus 'anak pegang barang' (open → kembalikan/timeout).
    Sumber: worker HoldSessionTracker (worker.py). PRD F2.3 lanjutan.
    Kolom duration_sec riil dihitung open_ts → close_ts (detik)."""
    __tablename__ = "hold_sessions"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    video_batch_id: Mapped[int | None] = mapped_column(
        ForeignKey("video_batches.id", ondelete="SET NULL"), nullable=True, index=True
    )
    person_track_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    object_track_id: Mapped[int] = mapped_column(Integer, nullable=False)
    object_class: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    open_ts: Mapped[float] = mapped_column(Float, nullable=False)
    close_ts: Mapped[float] = mapped_column(Float, nullable=False)
    duration_sec: Mapped[float] = mapped_column(Float, nullable=False)
    end_reason: Mapped[str] = mapped_column(String(30), nullable=False)  # timeout | returned_to_rak | segment_end
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
