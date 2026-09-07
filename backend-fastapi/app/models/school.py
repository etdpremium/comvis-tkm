"""
app/models/school.py — School + ClassRoom
"""
from __future__ import annotations
from sqlalchemy import String, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db import Base
from app.models.base import TimestampMixin


class School(Base, TimestampMixin):
    __tablename__ = "schools"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False, unique=True)
    address: Mapped[str | None] = mapped_column(String(500), nullable=True)

    classes: Mapped[list["ClassRoom"]] = relationship(back_populates="school", cascade="all, delete-orphan")


class ClassRoom(Base, TimestampMixin):
    __tablename__ = "classes"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    grade: Mapped[str] = mapped_column(String(20), nullable=False)  # "TK A", "TK B"
    school_id: Mapped[int] = mapped_column(ForeignKey("schools.id", ondelete="CASCADE"), nullable=False)

    school: Mapped[School] = relationship(back_populates="classes")
    students: Mapped[list["Student"]] = relationship(back_populates="class_room")
