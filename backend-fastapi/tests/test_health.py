"""
tests/test_health.py — smoke test untuk backend
Jalankan: `pytest tests/` atau `python -m pytest tests/ -v`
"""
import os
import sys
import pytest

# Add backend-fastapi to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend-fastapi"))


def test_import_app():
    from app.main import app
    assert app is not None
    assert app.title.startswith("TKM")


def test_routes_count():
    from app.main import app
    paths = {r.path for r in app.routes if hasattr(r, "path")}
    paths |= set(app.openapi().get("paths", {}).keys())  # include sub-routes
    expected = {
        "/health", "/docs", "/api/v1/health/full",
        "/api/v1/auth/login", "/api/v1/auth/login-json",
        "/api/v1/students", "/api/v1/students/aruco",
        "/api/v1/materials", "/api/v1/zones",
        "/api/v1/detections", "/api/v1/activities",
        "/api/v1/videos/upload",
        "/api/v1/dashboard/today", "/api/v1/dashboard/week",
        "/api/v1/dashboard/heatmap", "/api/v1/dashboard/videos",
        "/api/v1/cameras", "/api/v1/schools",
        "/api/v1/storage/buckets", "/api/v1/storage/objects",
    }
    missing = expected - paths
    assert not missing, f"Missing routes: {missing}"


def test_models_count():
    from app import models
    expected = {"School", "ClassRoom", "User", "Student", "Material", "Zone",
                "Camera", "VideoBatch", "VisionIdEvent", "Activity", "AuditLog"}
    actual = set(models.__all__)
    assert expected.issubset(actual), f"Missing: {expected - actual}"


def test_password_hash():
    from app.services.auth_service import auth_service
    h = auth_service.hash_password("test123")
    assert auth_service.verify_password("test123", h)
    assert not auth_service.verify_password("wrong", h)


def test_jwt_roundtrip():
    from app.services.auth_service import auth_service
    token = auth_service.create_access_token("42", extra={"role": "admin"})
    payload = auth_service.decode_token(token)
    assert payload is not None
    assert payload["sub"] == "42"
    assert payload["role"] == "admin"
    assert payload["type"] == "access"


def test_settings_load():
    from app.config import settings
    assert settings.postgres_host
    assert settings.minio_endpoint
    assert settings.jwt_secret


def test_summarizer_construct():
    from app.services.summarizer import summarizer
    assert summarizer.focus_min_sec == 60
