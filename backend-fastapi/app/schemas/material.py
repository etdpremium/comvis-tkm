"""
app/schemas/material.py
"""
from __future__ import annotations
from pydantic import BaseModel
from typing import Optional


class MaterialCreate(BaseModel):
    name: str
    yolo_class_id: Optional[int] = None
    category: str = "general"
    description: Optional[str] = None


class MaterialOut(BaseModel):
    id: int
    name: str
    yolo_class_id: Optional[int] = None
    category: str
    description: Optional[str] = None

    model_config = {"from_attributes": True}
