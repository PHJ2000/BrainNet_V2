# backend/app/models/invite_token.py
from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime


class JoinProject(BaseModel):
    token: str = Field(min_length=1, max_length=48, pattern=r"^[A-Za-z0-9_-]+$")

class InviteTokenOut(BaseModel):
    token: str
    project_id: int
    email: str
    role: str
    expires_at: datetime
    accepted_at: Optional[datetime]

    class Config:
        from_attributes = True
