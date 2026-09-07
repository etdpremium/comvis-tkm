"""
app/auth/__init__.py — FastAPI dependencies
"""
from .dependencies import (
    get_current_user,
    require_teacher,
    require_admin,
    require_service,
    audit,
)

__all__ = [
    "get_current_user", "require_teacher", "require_admin", "require_service", "audit",
]
