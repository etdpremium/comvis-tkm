"""
app/models/user.py — User (RBAC: parent/teacher/admin/principal)
"""
from __future__ import annotations
import enum
from sqlalchemy import String, Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column
from app.db import Base
from app.models.base import TimestampMixin


class UserRole(str, enum.Enum):
    parent = "parent"
    teacher = "teacher"
    admin = "admin"
    principal = "principal"
    service = "service"  # untuk X-Service-Key worker


class User(Base, TimestampMixin):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(200), nullable=False, unique=True)
    hashed_password: Mapped[str] = mapped_column(String(500), nullable=False)
    full_name: Mapped[str] = mapped_column(String(200), nullable=False)
    role: Mapped[UserRole] = mapped_column(SAEnum(UserRole, name="user_role"), nullable=False, default=UserRole.teacher)
    is_active: Mapped[bool] = mapped_column(default=True, nullable=False)
