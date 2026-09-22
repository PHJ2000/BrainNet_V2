from typing import Literal
from uuid import UUID
from pydantic import Field, field_validator
from app.models.workspace import Strict, TaskCreate, DiscussionCreate


class ReplyCreate(Strict):
    id: UUID
    body: str = Field(min_length=1, max_length=8000)
    mentions: list[int] = Field(default_factory=list, max_length=20)

    @field_validator("mentions")
    @classmethod
    def members(cls, values):
        if len(set(values)) != len(values) or any(v < 1 for v in values):
            raise ValueError("Unique positive member IDs required")
        return values


class LinkCreate(Strict):
    target_id: int = Field(gt=0)
    label: str = Field(default="", max_length=120)


class Dependencies(Strict):
    expected_version: int = Field(ge=0)
    requires: list[UUID] = Field(max_length=50)


class VersionedTask(Strict):
    id: UUID
    expected_version: int = Field(ge=0)


class BulkTasks(Strict):
    tasks: list[VersionedTask] = Field(min_length=1, max_length=100)
    status: Literal["TODO", "DOING", "DONE", "CANCELED"]


class DraftWrite(Strict):
    expected_version: int = Field(ge=-1)
    base_version: int = Field(default=-1, ge=-1)
    resolved: bool = False
    item: TaskCreate | DiscussionCreate
    attempted: bool = False


class AIPolicyWrite(Strict):
    expected_version: int = Field(ge=0)
    daily_limit: int = Field(ge=0, le=100)
    input_limit: int = Field(ge=100, le=16000)
