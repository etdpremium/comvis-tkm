"""
app/auth/dependencies.py — JWT dependency + RBAC + audit
"""
from __future__ import annotations
from datetime import datetime, timezone
from fastapi import Cookie, Header, HTTPException, Depends, Request
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import Annotated, Optional

from ..db import get_session
from ..models import User, UserRole, AuditLog
from ..services.auth_service import auth_service
from ..config import settings

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login", auto_error=False)


async def _user_from_token(token: str, session: AsyncSession) -> User | None:
    payload = auth_service.decode_token(token)
    if not payload or "sub" not in payload:
        return None
    try:
        uid = int(payload["sub"])
    except (TypeError, ValueError):
        return None
    user = (await session.execute(select(User).where(User.id == uid))).scalar_one_or_none()
    return user


async def get_current_user(
    request: Request,
    token: Annotated[str | None, Depends(oauth2_scheme)] = None,
    tkm_access: Annotated[Optional[str], Cookie(alias="tkm_access")] = None,
    session: AsyncSession = Depends(get_session),
) -> User:
    # Prioritas: Authorization Bearer (worker/service) > cookie (browser)
    candidate = token or tkm_access
    if not candidate:
        raise HTTPException(status_code=401, detail="Missing bearer token")
    user = await _user_from_token(candidate, session)
    if not user or not user.is_active:
        raise HTTPException(status_code=401, detail="Invalid or inactive user")
    return user


async def require_teacher(user: User = Depends(get_current_user)) -> User:
    if user.role not in (UserRole.teacher, UserRole.admin, UserRole.principal):
        raise HTTPException(status_code=403, detail="Teacher role required")
    return user


async def require_admin(user: User = Depends(get_current_user)) -> User:
    if user.role not in (UserRole.admin, UserRole.principal):
        raise HTTPException(status_code=403, detail="Admin role required")
    return user


async def require_service(
    x_service_key: Annotated[str | None, Header()] = None,
    token: Annotated[str | None, Depends(oauth2_scheme)] = None,
    session: AsyncSession = Depends(get_session),
) -> User:
    """Worker uses either X-Service-Key or service-role JWT."""
    if x_service_key and x_service_key == settings.service_api_key:
        # Find or create a synthetic service user
        u = (await session.execute(select(User).where(User.email == "service@worker.local"))).scalar_one_or_none()
        if not u:
            u = User(
                email="service@worker.local",
                hashed_password=auth_service.hash_password("service"),
                full_name="CV Worker (Service)",
                role=UserRole.service,
                is_active=True,
            )
            session.add(u)
            await session.commit()
            await session.refresh(u)
        return u
    if token:
        user = await _user_from_token(token, session)
        if user and user.is_active and user.role in (UserRole.service, UserRole.admin):
            return user
    raise HTTPException(status_code=401, detail="Service auth required (X-Service-Key or service JWT)")


async def audit(
    request: Request,
    user: User | None = None,
    action: str = "view",
    extra: dict | None = None,
) -> None:
    """Optional audit log helper. Not wired as Depends to avoid N+1; routes call explicitly when needed."""
    pass  # no-op stub; route handlers can call _audit_log directly
