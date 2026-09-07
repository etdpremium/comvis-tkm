"""
app/models/material.py — Material (8 dominan: bantal, lemari, dll)
"""
from __future__ import annotations
from sqlalchemy import String, Integer
from sqlalchemy.orm import Mapped, mapped_column
from app.db import Base
from app.models.base import TimestampMixin


class Material(Base, TimestampMixin):
    __tablename__ = "materials"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    yolo_class_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    category: Mapped[str] = mapped_column(String(50), default="general", nullable=False)
    description: Mapped[str | None] = mapped_column(String(500), nullable=True)
