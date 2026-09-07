"""
app/routes/auth.py — login, refresh, logout, me
"""
from __future__ import annotations
from fastapi import APIRouter, Cookie, Depends, HTTPException, Response
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Annotated, Optional

from ..db import get_session
from ..models import User
from ..schemas import LoginRequest, TokenOut, UserOut
from ..services.auth_service import auth_service
from ..config import settings

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])

ACCESS_COOKIE = "tkm_access"
REFRESH_COOKIE = "tkm_refresh"


def _set_cookies(response: Response, access: str, refresh: str) -> None:
    """Taruh JWT di HttpOnly cookie. Tidak bisa diakses JS — lebih aman dari localStorage."""
    common = dict(httponly=True, samesite="lax", path="/", secure=False)
    response.set_cookie(ACCESS_COOKIE, access, max_age=settings.jwt_access_expire_min * 60, **common)
    response.set_cookie(REFRESH_COOKIE, refresh, max_age=settings.jwt_refresh_expire_days * 24 * 3600, **common)


@router.post("/login", response_model=TokenOut)
async def login(
    response: Response,
    form: Annotated[OAuth2PasswordRequestForm, Depends()],
    session: AsyncSession = Depends(get_session),
):
    user = (await session.execute(select(User).where(User.email == form.username))).scalar_one_or_none()
    if not user or not auth_service.verify_password(form.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    if not user.is_active:
        raise HTTPException(status_code=403, detail="User inactive")
    access = auth_service.create_access_token(sub=str(user.id), extra={"role": user.role.value})
    refresh = auth_service.create_refresh_token(sub=str(user.id))
    _set_cookies(response, access, refresh)
    return TokenOut(
        access_token=access,
        refresh_token=refresh,
        expires_in=settings.jwt_access_expire_min * 60,
    )


@router.post("/login-json", response_model=TokenOut)
async def login_json(
    response: Response,
    payload: LoginRequest,
    session: AsyncSession = Depends(get_session),
):
    user = (await session.execute(select(User).where(User.email == payload.email))).scalar_one_or_none()
    if not user or not auth_service.verify_password(payload.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    if not user.is_active:
        raise HTTPException(status_code=403, detail="User inactive")
    access = auth_service.create_access_token(sub=str(user.id), extra={"role": user.role.value})
    refresh = auth_service.create_refresh_token(sub=str(user.id))
    _set_cookies(response, access, refresh)
    return TokenOut(
        access_token=access,
        refresh_token=refresh,
        expires_in=settings.jwt_access_expire_min * 60,
    )


@router.post("/logout")
async def logout(response: Response):
    response.delete_cookie(ACCESS_COOKIE, path="/")
    response.delete_cookie(REFRESH_COOKIE, path="/")
    return {"ok": True}


@router.get("/me")
async def me(
    tkm_access: Annotated[Optional[str], Cookie(alias=ACCESS_COOKIE)] = None,
    session: AsyncSession = Depends(get_session),
):
    """Cek session dari cookie. Dipakai dashboard untuk auto-redirect kalau belum login."""
    if not tkm_access:
        raise HTTPException(status_code=401, detail="Not authenticated")
    payload = auth_service.decode_token(tkm_access)
    if not payload or "sub" not in payload:
        raise HTTPException(status_code=401, detail="Invalid token")
    try:
        uid = int(payload["sub"])
    except (TypeError, ValueError):
        raise HTTPException(status_code=401, detail="Invalid subject")
    user = (await session.execute(select(User).where(User.id == uid))).scalar_one_or_none()
    if not user or not user.is_active:
        raise HTTPException(status_code=401, detail="Inactive user")
    return {"id": user.id, "email": user.email, "role": user.role.value, "full_name": user.full_name}
