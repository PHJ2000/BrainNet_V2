# backend/app/models/tag.py
from pydantic import BaseModel
from typing import Optional

class TagCreate(BaseModel):
    name: str
    color: Optional[str] = None

class TagUpdate(BaseModel):
    name: Optional[str] = None
    color: Optional[str] = None

class TagOut(BaseModel):
    id: int
    project_id: int
    name: str
    color: Optional[str]
    node_count: Optional[int] = None
    nodes: Optional[list[int]] = None

    class Config:
        from_attributes = True
