from datetime import date
from typing import Literal
from uuid import UUID
from pydantic import ConfigDict, Field, field_validator
from app.models.fields import StoredTextModel


class Strict(StoredTextModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class TaskFields(Strict):
    title: str = Field(min_length=1, max_length=240)
    body: str = Field(default="", max_length=12000)
    status: Literal["TODO", "DOING", "DONE", "CANCELED"] = "TODO"
    priority: Literal["LOW", "MEDIUM", "HIGH"] = "MEDIUM"
    assignee_id: int | None = Field(default=None, gt=0)
    due_date: date | None = None
    node_id: int | None = Field(default=None, gt=0)


class TaskCreate(TaskFields):
    id: UUID


class TaskUpdate(TaskFields):
    expected_version: int = Field(ge=0)


class DiscussionCreate(Strict):
    id: UUID
    body: str = Field(min_length=1, max_length=8000)
    node_id: int | None = Field(default=None, gt=0)


class DiscussionUpdate(Strict):
    body: str = Field(min_length=1, max_length=8000)
    resolved: bool
    expected_version: int = Field(ge=0)


class ProposalCreate(Strict):
    id: UUID
    mode: Literal["EXPAND", "SUMMARY", "ACTION"]
    instruction: str = Field(default="", max_length=1000)
    node_ids: list[int] = Field(min_length=1, max_length=8)

    @field_validator("node_ids")
    @classmethod
    def unique_positive(cls, values):
        if len(set(values)) != len(values) or any(value < 1 for value in values):
            raise ValueError("Select unique positive node IDs")
        return values


class ProposalAccept(Strict):
    title: str = Field(min_length=1, max_length=240)
