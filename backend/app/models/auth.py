# #backend/app/models/auth.py
from pydantic import BaseModel, EmailStr, Field, field_validator
from typing import Optional
from datetime import datetime

class UserCreate(BaseModel):
    email: EmailStr = Field(max_length=120)
    password: str = Field(min_length=8, max_length=72)
    name: Optional[str] = Field(default=None, max_length=80)

    @field_validator("password")
    @classmethod
    def password_bytes(cls, value: str) -> str:
        if len(value.encode("utf-8")) > 72 or "\x00" in value:
            raise ValueError("Password must fit within 72 UTF-8 bytes and contain no NUL")
        return value

class Token(BaseModel):
    access_token: str
    token_type: str = "Bearer"


class UserRead(BaseModel):
    id: int
    email: EmailStr
    name: Optional[str]
    created_at: datetime
    last_login_at: Optional[datetime] = None

    class Config:
        from_attributes = True
