"""
app/models/camera.py — Camera (IP CCTV source)
"""
from __future__ import annotations
from sqlalchemy import String, ForeignKey, Integer, Boolean
from sqlalchemy.orm import Mapped, mapped_column
from app.db import Base
from app.models.base import TimestampMixin


class Camera(Base, TimestampMixin):
    __tablename__ = "cameras"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    rtsp_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    class_id: Mapped[int] = mapped_column(ForeignKey("classes.id", ondelete="CASCADE"), nullable=False)
    location: Mapped[str | None] = mapped_column(String(200), nullable=True)
    fps: Mapped[int] = mapped_column(Integer, default=15, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    resolution_w: Mapped[int] = mapped_column(Integer, default=1280, nullable=False)
    resolution_h: Mapped[int] = mapped_column(Integer, default=720, nullable=False)
