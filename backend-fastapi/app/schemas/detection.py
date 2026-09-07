"""
app/schemas/detection.py — input/output untuk /detections
"""
from __future__ import annotations
from pydantic import BaseModel, Field
from datetime import datetime
from typing import Optional


class ArucoIn(BaseModel):
    aruco_id: int
    bbox: list[float] = Field(default_factory=lambda: [0, 0, 0, 0])
    xyz: list[float] = Field(default_factory=lambda: [0, 0, 0])
    rvec: Optional[list[float]] = None
    tvec: Optional[list[float]] = None
    confidence: float = 0.98
    ts: Optional[datetime] = None


class DetectionIn(BaseModel):
    track_id: int = -1
    class_id: int = 0
    class_name: str
    bbox: list[float] = Field(default_factory=lambda: [0, 0, 0, 0])
    confidence: float = 0.0
    zone_id: Optional[int] = None
    extra: Optional[dict] = None
    in_zone_main: bool = False
    in_rak: bool = False
    ts: Optional[datetime] = None
    crop_s3_key: Optional[str] = None


class DetectionBatch(BaseModel):
    """Payload dari worker — 1 frame, ~15 frame per detik."""
    frame: int
    ts: datetime
    camera_id: Optional[str] = None
    detections: list[DetectionIn] = Field(default_factory=list)
    aruco_detections: list[ArucoIn] = Field(default_factory=list)
    video_batch_id: Optional[int] = None


class DetectionAck(BaseModel):
    ok: bool
    tracked: int
    aruco: int
    activities: int
