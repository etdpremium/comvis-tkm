"""
backend-fastapi/app/config.py — Konfigurasi via pydantic-settings
PRD F1.1 + F1.2. Load dari env (override) atau .env (default).
"""
from __future__ import annotations
from pydantic_settings import BaseSettings, SettingsConfigDict
from pathlib import Path


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(Path(__file__).parent.parent / ".env"),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # App
    app_name: str = "TKM FullStack Backend"
    app_version: str = "4.1.0"
    debug: bool = True

    # Postgres
    postgres_host: str = "localhost"
    postgres_port: int = 5432
    postgres_user: str = "tkm"
    postgres_password: str = "tkm123"
    postgres_db: str = "tkm"

    # Redis
    redis_host: str = "localhost"
    redis_port: int = 6379
    redis_db: int = 0

    # MinIO (S3-compatible)
    minio_endpoint: str = "localhost:9000"
    minio_root_user: str = "minioadmin"
    minio_root_password: str = "minioadmin"
    minio_bucket_raw: str = "raw-videos"
    minio_bucket_annotated: str = "annotated"
    minio_bucket_crops: str = "crops"
    minio_bucket_models: str = "models"
    minio_secure: bool = False
    minio_presign_expiry_sec: int = 7 * 24 * 3600  # 7 days

    # Auth
    jwt_secret: str = "tkm-poc-secret-change-in-prod-please"
    jwt_algorithm: str = "HS256"
    jwt_access_expire_min: int = 60 * 8  # 8 hours
    jwt_refresh_expire_days: int = 14
    service_api_key: str = "tkm-service-key-local"  # X-Service-Key dari worker

    # Server
    fastapi_host: str = "0.0.0.0"
    fastapi_port: int = 8000

    # CV / worker
    yolo_imgsz: int = 640
    yolo_conf: float = 0.25
    yolo_iou: float = 0.45
    fps_target: int = 15
    segment_seconds: int = 60

    @property
    def database_url(self) -> str:
        return (
            f"postgresql+asyncpg://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    @property
    def database_url_sync(self) -> str:
        return (
            f"postgresql://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    @property
    def redis_url(self) -> str:
        return f"redis://{self.redis_host}:{self.redis_port}/{self.redis_db}"


settings = Settings()
