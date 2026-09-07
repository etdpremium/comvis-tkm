"""
app/models/base.py — shared mixin (TimestampMixin) + re-export Base dari app.db
"""
from __future__ import annotations
from datetime import datetime
from sqlalchemy import DateTime, func
from sqlalchemy.orm import Mapped, mapped_column
from app.db import Base  # re-export


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


__all__ = ["Base", "TimestampMixin"]
