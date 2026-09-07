"""
app/schemas/auth.py
"""
from __future__ import annotations
from pydantic import BaseModel, EmailStr


class LoginRequest(BaseModel):
    email: str  # accept any non-empty string (EmailStr requires pydantic-extra; kept simple)
    password: str


class TokenOut(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int


class UserOut(BaseModel):
    id: int
    email: str
    full_name: str
    role: str
    is_active: bool

    model_config = {"from_attributes": True}
