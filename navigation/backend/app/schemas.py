"""Public API request and response schemas."""

from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator


FolderName = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=255)
]
BookmarkTitle = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=1024)
]
BookmarkUrl = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


def _reject_explicit_nulls(data: object, fields: tuple[str, ...]) -> object:
    if isinstance(data, dict):
        null_fields = [field for field in fields if field in data and data[field] is None]
        if null_fields:
            raise ValueError(f"Fields cannot be null: {', '.join(null_fields)}")
    return data


class LoginRequest(BaseModel):
    username: str
    password: str


class LoginResponse(BaseModel):
    csrf_token: str


class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    is_admin: bool
    is_active: bool
    must_change_password: bool
    csrf_token: str


PasswordValue = Annotated[str, StringConstraints(min_length=12, max_length=1024)]


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: PasswordValue


class AdminUserCreate(BaseModel):
    username: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=255)]
    temporary_password: PasswordValue


class AdminUserStatusUpdate(BaseModel):
    is_active: bool


class AdminPasswordReset(BaseModel):
    temporary_password: PasswordValue


class AdminUserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    is_admin: bool
    is_active: bool
    must_change_password: bool
    created_at: datetime
    updated_at: datetime


class AdminAuditResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    actor_user_id: int | None
    target_user_id: int | None
    target_username: str
    action: str
    result: str
    created_at: datetime


class FolderCreate(BaseModel):
    base_name: FolderName
    parent_id: int | None = None
    position: int | None = Field(default=None, ge=1)


class FolderUpdate(BaseModel):
    base_name: FolderName | None = None
    parent_id: int | None = None
    position: int | None = Field(default=None, ge=1)

    @model_validator(mode="before")
    @classmethod
    def reject_null_required_fields(cls, data: object) -> object:
        return _reject_explicit_nulls(data, ("base_name", "position"))


class FolderResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    parent_id: int | None
    base_name: str
    position: int
    bookmark_count: int = 0
    created_at: datetime
    updated_at: datetime


class BookmarkCreate(BaseModel):
    title: BookmarkTitle
    url: BookmarkUrl
    folder_id: int
    notes: str = ""
    position: int | None = Field(default=None, ge=1)


class BookmarkUpdate(BaseModel):
    title: BookmarkTitle | None = None
    url: BookmarkUrl | None = None
    folder_id: int | None = None
    notes: str | None = None
    position: int | None = Field(default=None, ge=1)

    @model_validator(mode="before")
    @classmethod
    def reject_null_required_fields(cls, data: object) -> object:
        return _reject_explicit_nulls(data, ("title", "url", "folder_id", "position"))


class BookmarkResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    folder_id: int
    title: str
    url: str
    normalized_url: str
    notes: str
    position: int
    domain: str = ""
    created_at: datetime
    updated_at: datetime


class SearchResponse(BaseModel):
    items: list[BookmarkResponse]
    total: int
    limit: int
    offset: int
