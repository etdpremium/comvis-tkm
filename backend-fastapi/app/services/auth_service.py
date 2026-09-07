"""
app/services/auth_service.py — JWT issuance + verify, password hashing
PRD F1.2 auth/JWT.
"""
from __future__ import annotations
from datetime import datetime, timedelta, timezone
from typing import Any
from jose import jwt, JWTError
import bcrypt
from ..config import settings


def _hash_bcrypt(plain: str) -> str:
    # bcrypt native 72-byte cap
    return bcrypt.hashpw(plain.encode("utf-8")[:72], bcrypt.gensalt(rounds=10)).decode("utf-8")


def _verify_bcrypt(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode("utf-8")[:72], hashed.encode("utf-8"))
    except Exception:
        return False


class AuthService:
    def hash_password(self, plain: str) -> str:
        return _hash_bcrypt(plain)

    def verify_password(self, plain: str, hashed: str) -> bool:
        return _verify_bcrypt(plain, hashed)

    def create_access_token(self, sub: str, extra: dict[str, Any] | None = None) -> str:
        now = datetime.now(timezone.utc)
        payload = {
            "sub": sub,
            "iat": int(now.timestamp()),
            "exp": int((now + timedelta(minutes=settings.jwt_access_expire_min)).timestamp()),
            "type": "access",
        }
        if extra:
            payload.update(extra)
        return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)

    def create_refresh_token(self, sub: str) -> str:
        now = datetime.now(timezone.utc)
        payload = {
            "sub": sub,
            "iat": int(now.timestamp()),
            "exp": int((now + timedelta(days=settings.jwt_refresh_expire_days)).timestamp()),
            "type": "refresh",
        }
        return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)

    def decode_token(self, token: str) -> dict[str, Any] | None:
        try:
            return jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
        except JWTError:
            return None


auth_service = AuthService()
