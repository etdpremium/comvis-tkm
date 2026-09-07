"""
app/models/video.py — VideoBatch (raw + annotated clip per segment)
"""
from __future__ import annotations
import enum
from sqlalchemy import String, ForeignKey, Integer, BigInteger, Enum as SAEnum, DateTime
from sqlalchemy.orm import Mapped, mapped_column
from datetime import datetime
from app.db import Base
from app.models.base import TimestampMixin


class VideoStatus(str, enum.Enum):
    uploaded = "uploaded"
    processing = "processing"
    done = "done"
    failed = "failed"


class VideoBatch(Base, TimestampMixin):
    __tablename__ = "video_batches"

    id: Mapped[int] = mapped_column(primary_key=True)
    camera_id: Mapped[int | None] = mapped_column(ForeignKey("cameras.id", ondelete="SET NULL"), nullable=True)
    class_id: Mapped[int | None] = mapped_column(ForeignKey("classes.id", ondelete="SET NULL"), nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    duration_sec: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    fps: Mapped[int] = mapped_column(Integer, default=15, nullable=False)
    frames_total: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    detections_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    # MinIO keys
    raw_s3_key: Mapped[str | None] = mapped_column(String(500), nullable=True)
    annotated_s3_key: Mapped[str | None] = mapped_column(String(500), nullable=True)
    size_bytes: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)

    status: Mapped[VideoStatus] = mapped_column(
        SAEnum(VideoStatus, name="video_status"), default=VideoStatus.uploaded, nullable=False
    )
    error: Mapped[str | None] = mapped_column(String(1000), nullable=True)
