# backend/app/models/tag.py
from pydantic import BaseModel, Field
from typing import Optional
from app.models.fields import StoredTextModel, TAG_NAME_MAX, TAG_COLOR_MAX

class TagCreate(StoredTextModel):
    name: str = Field(max_length=TAG_NAME_MAX)
    color: Optional[str] = Field(default=None, max_length=TAG_COLOR_MAX)

class TagUpdate(StoredTextModel):
    name: Optional[str] = Field(default=None, max_length=TAG_NAME_MAX)
    color: Optional[str] = Field(default=None, max_length=TAG_COLOR_MAX)

class TagOut(BaseModel):
    id: int
    project_id: int
    name: str
    color: Optional[str]
    node_count: Optional[int] = None
    nodes: Optional[list[int]] = None

    class Config:
        from_attributes = True
