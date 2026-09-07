"""
backend-fastapi/app/schemas/__init__.py — Pydantic v2 schemas
"""
from .detection import DetectionBatch, DetectionIn, ArucoIn, DetectionAck
from .activity import ActivityOut, StudentToday, DashboardWeek
from .student import StudentCreate, StudentOut, ArucoAssign
from .material import MaterialCreate, MaterialOut
from .zone import ZoneCreate, ZoneOut
from .auth import LoginRequest, TokenOut, UserOut

__all__ = [
    "DetectionBatch", "DetectionIn", "ArucoIn", "DetectionAck",
    "ActivityOut", "StudentToday", "DashboardWeek",
    "StudentCreate", "StudentOut", "ArucoAssign",
    "MaterialCreate", "MaterialOut",
    "ZoneCreate", "ZoneOut",
    "LoginRequest", "TokenOut", "UserOut",
]
