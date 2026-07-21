"""Initial persistence schema.

Revision ID: 0001_initial
"""

import sqlalchemy as sa
from alembic import op

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def _timestamps() -> tuple[sa.Column, sa.Column]:
    utc_now = sa.text("CURRENT_TIMESTAMP")
    return (
        sa.Column("created_at", sa.DateTime(), server_default=utc_now, nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=utc_now, nullable=False),
    )


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("username", sa.String(255), nullable=False),
        sa.Column("password_hash", sa.String(255), nullable=False),
        *_timestamps(),
        sa.UniqueConstraint("username"),
    )
    op.create_table(
        "folders",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("parent_id", sa.Integer(), nullable=True),
        sa.Column("base_name", sa.String(255), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        *_timestamps(),
        sa.ForeignKeyConstraint(["parent_id"], ["folders.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("parent_id", "base_name"),
        sa.UniqueConstraint("parent_id", "position"),
    )
    op.create_index(
        "uq_folders_parent_name",
        "folders",
        [sa.text("coalesce(parent_id, 0)"), "base_name"],
        unique=True,
    )
    op.create_index(
        "uq_folders_parent_position",
        "folders",
        [sa.text("coalesce(parent_id, 0)"), "position"],
        unique=True,
    )
    op.create_table(
        "bookmarks",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("folder_id", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(1024), nullable=False),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("normalized_url", sa.Text(), nullable=False),
        sa.Column("position", sa.Integer(), server_default="0", nullable=False),
        sa.Column("deleted_at", sa.DateTime(), nullable=True),
        *_timestamps(),
        sa.ForeignKeyConstraint(["folder_id"], ["folders.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_bookmarks_title", "bookmarks", ["title"])
    op.create_index("ix_bookmarks_normalized_url", "bookmarks", ["normalized_url"])
    op.create_index(
        "uq_bookmarks_active_normalized_url",
        "bookmarks",
        ["normalized_url"],
        unique=True,
        sqlite_where=sa.text("deleted_at IS NULL"),
    )
    op.create_table(
        "session_tokens",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("token_hash", sa.String(255), nullable=False),
        sa.Column("csrf_token", sa.String(255), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("token_hash"),
    )
    op.create_table(
        "import_batches",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("source_name", sa.String(1024), nullable=False),
        sa.Column("status", sa.String(50), server_default="pending", nullable=False),
        *_timestamps(),
    )
    op.create_table(
        "import_items",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("batch_id", sa.Integer(), nullable=False),
        sa.Column("bookmark_id", sa.Integer(), nullable=True),
        sa.Column("source_url", sa.Text(), nullable=False),
        sa.Column("status", sa.String(50), server_default="pending", nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        *_timestamps(),
        sa.ForeignKeyConstraint(["batch_id"], ["import_batches.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["bookmark_id"], ["bookmarks.id"], ondelete="SET NULL"),
    )
    op.create_table(
        "operations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("operation_type", sa.String(100), nullable=False),
        sa.Column("payload", sa.Text(), server_default="{}", nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
    )
    op.create_table(
        "backups",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("path", sa.Text(), nullable=False),
        sa.Column("checksum", sa.String(255), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.UniqueConstraint("path"),
    )


def downgrade() -> None:
    op.drop_table("backups")
    op.drop_table("operations")
    op.drop_table("import_items")
    op.drop_table("import_batches")
    op.drop_table("session_tokens")
    op.drop_index("uq_bookmarks_active_normalized_url", table_name="bookmarks")
    op.drop_index("ix_bookmarks_normalized_url", table_name="bookmarks")
    op.drop_index("ix_bookmarks_title", table_name="bookmarks")
    op.drop_table("bookmarks")
    op.drop_index("uq_folders_parent_position", table_name="folders")
    op.drop_index("uq_folders_parent_name", table_name="folders")
    op.drop_table("folders")
    op.drop_table("users")
