"""Relational persistence model for private bookmark navigation."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, JSON, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint, func, text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(server_default=func.current_timestamp())
    updated_at: Mapped[datetime] = mapped_column(
        server_default=func.current_timestamp(), onupdate=func.current_timestamp()
    )


class User(TimestampMixin, Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(255), unique=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="1")
    must_change_password: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="0"
    )


class Folder(TimestampMixin, Base):
    __tablename__ = "folders"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    parent_id: Mapped[int | None] = mapped_column(ForeignKey("folders.id", ondelete="CASCADE"))
    base_name: Mapped[str] = mapped_column(String(255))
    position: Mapped[int] = mapped_column(Integer)
    attrs: Mapped[dict] = mapped_column(JSON, default=dict, server_default="{}")
    toolbar_attrs: Mapped[dict] = mapped_column(JSON, default=dict, server_default="{}")
    __table_args__ = (
        Index(
            "uq_folders_parent_name",
            "user_id",
            func.coalesce(parent_id, 0),
            "base_name",
            unique=True,
        ),
        Index(
            "uq_folders_parent_position",
            "user_id",
            func.coalesce(parent_id, 0),
            "position",
            unique=True,
        ),
    )


class Bookmark(TimestampMixin, Base):
    __tablename__ = "bookmarks"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    folder_id: Mapped[int] = mapped_column(ForeignKey("folders.id", ondelete="CASCADE"))
    title: Mapped[str] = mapped_column(String(1024))
    url: Mapped[str] = mapped_column(Text)
    normalized_url: Mapped[str] = mapped_column(Text)
    notes: Mapped[str] = mapped_column(Text, default="", server_default="")
    position: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    attrs: Mapped[dict] = mapped_column(JSON, default=dict, server_default="{}")
    deleted_at: Mapped[datetime | None]
    __table_args__ = (
        Index("ix_bookmarks_title", "title"),
        Index("ix_bookmarks_normalized_url", "normalized_url"),
        Index(
            "uq_bookmarks_active_normalized_url",
            "user_id",
            "normalized_url",
            unique=True,
            sqlite_where=text("deleted_at IS NULL"),
        ),
    )


class SessionToken(Base):
    __tablename__ = "session_tokens"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    token_hash: Mapped[str] = mapped_column(String(255), unique=True)
    csrf_token: Mapped[str] = mapped_column(String(255))
    expires_at: Mapped[datetime]
    created_at: Mapped[datetime] = mapped_column(server_default=func.current_timestamp())


class ImportBatch(TimestampMixin, Base):
    __tablename__ = "import_batches"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    source_name: Mapped[str] = mapped_column(String(1024))
    status: Mapped[str] = mapped_column(String(50), default="pending", server_default="pending")
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    backup_id: Mapped[int | None] = mapped_column(ForeignKey("backups.id", ondelete="SET NULL"))
    folder_manifest: Mapped[dict] = mapped_column(JSON, default=dict, server_default="{}")


class ImportItem(TimestampMixin, Base):
    __tablename__ = "import_items"
    id: Mapped[int] = mapped_column(primary_key=True)
    batch_id: Mapped[int] = mapped_column(ForeignKey("import_batches.id", ondelete="CASCADE"))
    bookmark_id: Mapped[int | None] = mapped_column(ForeignKey("bookmarks.id", ondelete="SET NULL"))
    source_url: Mapped[str] = mapped_column(Text)
    title: Mapped[str] = mapped_column(String(1024))
    notes: Mapped[str] = mapped_column(Text, default="", server_default="")
    normalized_url: Mapped[str] = mapped_column(Text)
    folder_path: Mapped[str] = mapped_column(Text)
    classification_method: Mapped[str] = mapped_column(String(50))
    attrs: Mapped[dict] = mapped_column(JSON, default=dict, server_default="{}")
    folder_attrs: Mapped[list] = mapped_column(JSON, default=list, server_default="[]")
    toolbar_attrs: Mapped[dict] = mapped_column(JSON, default=dict, server_default="{}")
    status: Mapped[str] = mapped_column(String(50), default="pending", server_default="pending")
    error: Mapped[str | None] = mapped_column(Text)


class Operation(Base):
    __tablename__ = "operations"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    operation_type: Mapped[str] = mapped_column(String(100))
    payload: Mapped[str] = mapped_column(Text, default="{}", server_default="{}")
    created_at: Mapped[datetime] = mapped_column(server_default=func.current_timestamp())


class AdminAudit(Base):
    __tablename__ = "admin_audits"
    id: Mapped[int] = mapped_column(primary_key=True)
    actor_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    target_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    target_username: Mapped[str] = mapped_column(String(255))
    action: Mapped[str] = mapped_column(String(100))
    result: Mapped[str] = mapped_column(String(50), default="success", server_default="success")
    created_at: Mapped[datetime] = mapped_column(server_default=func.current_timestamp())


class Backup(Base):
    __tablename__ = "backups"
    id: Mapped[int] = mapped_column(primary_key=True)
    path: Mapped[str] = mapped_column(Text, unique=True)
    checksum: Mapped[str] = mapped_column(String(255))
    is_protected: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="0"
    )
    created_at: Mapped[datetime] = mapped_column(server_default=func.current_timestamp())
