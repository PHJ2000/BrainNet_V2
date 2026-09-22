"""Storage constraints shared by ordinary writes and project backups."""
from pydantic import BaseModel, field_validator

PROJECT_NAME_MAX = 120
TAG_NAME_MAX = 80
TAG_COLOR_MAX = 7
ORDER_MAX = 2147483647


class StoredTextModel(BaseModel):
    @field_validator("*", mode="after")
    @classmethod
    def valid_storage_text(cls, value):
        if isinstance(value, str):
            if "\x00" in value:
                raise ValueError("NUL characters are not supported by PostgreSQL")
            try:
                value.encode("utf-8")
            except UnicodeEncodeError:
                raise ValueError("Unpaired Unicode surrogate is not valid UTF-8") from None
        return value
