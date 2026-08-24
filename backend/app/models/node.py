# backend/app/models/node.py
from pydantic import BaseModel, Field, field_validator, model_validator
from typing import Optional, List
from datetime import datetime

class NodeCreate(BaseModel):
    content: Optional[str] = None
    pos_x: Optional[float] = None
    pos_y: Optional[float] = None
    depth: Optional[int] = 0
    order: Optional[int] = 0
    ai_prompt: Optional[str] = None
    parent_id: Optional[int] = None
    state: Optional[str] = None

class NodeUpdate(BaseModel):
    content: Optional[str] = None
    pos_x: Optional[float] = None
    pos_y: Optional[float] = None
    depth: Optional[int] = None
    order: Optional[int] = None
    expected_version: Optional[int] = Field(default=None, ge=0)

    @model_validator(mode="after")
    def require_change(self):
        mutable_fields = ("content", "pos_x", "pos_y", "depth", "order")
        if not any(getattr(self, field) is not None for field in mutable_fields):
            raise ValueError("at least one node field must be provided")
        return self

class NodeOut(BaseModel):
    id: int
    project_id: int
    author_id: Optional[int]
    content: str
    state: str
    pos_x: Optional[float]
    pos_y: Optional[float]
    depth: int
    order_index: int
    parent_id: Optional[int] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    tags: List[int] = Field(default_factory=list)
    version: int = Field(default=0, ge=0)

    @field_validator("state", mode="before")
    @classmethod
    def serialize_state_enum(cls, value):
        return getattr(value, "value", value)


    class Config:
        from_attributes = True
