"""
app/models/audit.py — AuditLog (catat setiap akses data sensitif)
"""
from __future__ import annotations
from datetime import datetime
from sqlalchemy import String, Integer, DateTime, ForeignKey, JSON
from sqlalchemy.orm import Mapped, mapped_column
from app.db import Base


class AuditLog(Base):
    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    action: Mapped[str] = mapped_column(String(50), nullable=False, index=True)  # login, view_student, export_pdf
    resource: Mapped[str] = mapped_column(String(200), nullable=False)  # "/api/v1/students/1"
    method: Mapped[str] = mapped_column(String(10), nullable=False)  # GET, POST
    ip: Mapped[str | None] = mapped_column(String(64), nullable=True)
    extra: Mapped[dict | None] = mapped_column(JSON, nullable=True)
