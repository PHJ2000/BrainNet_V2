# backend/app/models/project.py
from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime
from app.models.fields import StoredTextModel, PROJECT_NAME_MAX

class ProjectCreate(StoredTextModel):
    name: str = Field(..., min_length=1, max_length=PROJECT_NAME_MAX, example="새 프로젝트")
    description: Optional[str] = None

class ProjectUpdate(StoredTextModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=PROJECT_NAME_MAX)
    description: Optional[str] = None

class ProjectOut(BaseModel):
    id: int
    name: str
    description: Optional[str]
    owner_id: int
    created_at: datetime
    updated_at: datetime
    is_deleted: Optional[bool] = None
    my_role: Optional[str] = None
    ai_enabled: bool = False
    member_count: Optional[int] = None
    node_count: Optional[int] = None
    tag_count: Optional[int] = None

    class Config:
        from_attributes = True
