"""
app/schemas/zone.py
"""
from __future__ import annotations
from pydantic import BaseModel
from typing import Optional


class ZoneCreate(BaseModel):
    name: str
    zone_type: str = "general"
    class_id: int
    polygon: list
    color: Optional[str] = None


class ZoneOut(BaseModel):
    id: int
    name: str
    zone_type: str
    class_id: int
    polygon: list
    color: Optional[str] = None

    model_config = {"from_attributes": True}
