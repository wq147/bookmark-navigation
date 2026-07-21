"""Add bookmark notes used by editing and global search.

Revision ID: 0002_bookmark_notes
Revises: 0001_initial
"""

import sqlalchemy as sa
from alembic import op


revision = "0002_bookmark_notes"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "bookmarks",
        sa.Column("notes", sa.Text(), server_default="", nullable=False),
    )


def downgrade() -> None:
    op.drop_column("bookmarks", "notes")
