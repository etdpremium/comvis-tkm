"""
backend-fastapi/app/models/__init__.py — SQLAlchemy models (12 tabel sesuai PRD section 12 ERD)
"""
from app.db import Base
from .base import TimestampMixin  # noqa
from .school import School, ClassRoom  # noqa
from .user import User, UserRole  # noqa
from .student import Student  # noqa
from .material import Material  # noqa
from .zone import Zone  # noqa
from .camera import Camera  # noqa
from .video import VideoBatch, VideoStatus  # noqa
from .event import VisionIdEvent, Activity, EventType, BehaviorType, HoldSession  # noqa
from .audit import AuditLog  # noqa

__all__ = [
    "Base", "TimestampMixin",
    "School", "ClassRoom",
    "User", "UserRole",
    "Student",
    "Material",
    "Zone",
    "Camera",
    "VideoBatch", "VideoStatus",
    "VisionIdEvent", "Activity", "EventType", "BehaviorType", "HoldSession",
    "AuditLog",
]
