"""
app/models/zone.py — Zone (polygon area di kelas)
"""
from __future__ import annotations
from sqlalchemy import String, ForeignKey, JSON
from sqlalchemy.orm import Mapped, mapped_column
from app.db import Base
from app.models.base import TimestampMixin


class Zone(Base, TimestampMixin):
    __tablename__ = "zones"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    zone_type: Mapped[str] = mapped_column(String(50), default="general", nullable=False)  # rak, meja, circle, dll
    class_id: Mapped[int] = mapped_column(ForeignKey("classes.id", ondelete="CASCADE"), nullable=False)
    polygon: Mapped[list] = mapped_column(JSON, nullable=False)  # [[x1,y1],[x2,y2],...] normalized 0-1
    color: Mapped[str | None] = mapped_column(String(20), nullable=True)
