"""
app/models/student.py — Student (anak TK, 1 baris per anak, dengan aruco_id)
"""
from __future__ import annotations
from sqlalchemy import String, ForeignKey, Integer
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db import Base
from app.models.base import TimestampMixin


class Student(Base, TimestampMixin):
    __tablename__ = "students"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    nis: Mapped[str | None] = mapped_column(String(50), nullable=True, unique=True)
    aruco_id: Mapped[int | None] = mapped_column(Integer, nullable=True, unique=True, index=True)
    class_id: Mapped[int] = mapped_column(ForeignKey("classes.id", ondelete="CASCADE"), nullable=False)
    is_active: Mapped[bool] = mapped_column(default=True, nullable=False)

    class_room: Mapped["ClassRoom"] = relationship(back_populates="students")  # noqa
