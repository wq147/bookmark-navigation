"""Preserve Netscape bookmark, folder, and toolbar attributes.

Revision ID: 0004_netscape_attrs
"""

import sqlalchemy as sa
from alembic import op

revision = "0004_netscape_attrs"
down_revision = "0003_import_preview"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "folders", sa.Column("attrs", sa.JSON(), nullable=False, server_default="{}")
    )
    op.add_column(
        "folders",
        sa.Column("toolbar_attrs", sa.JSON(), nullable=False, server_default="{}"),
    )
    op.add_column(
        "bookmarks", sa.Column("attrs", sa.JSON(), nullable=False, server_default="{}")
    )
    op.add_column(
        "import_items", sa.Column("attrs", sa.JSON(), nullable=False, server_default="{}")
    )
    op.add_column(
        "import_items",
        sa.Column("folder_attrs", sa.JSON(), nullable=False, server_default="[]"),
    )
    op.add_column(
        "import_items",
        sa.Column("toolbar_attrs", sa.JSON(), nullable=False, server_default="{}"),
    )


def downgrade() -> None:
    op.drop_column("import_items", "toolbar_attrs")
    op.drop_column("import_items", "folder_attrs")
    op.drop_column("import_items", "attrs")
    op.drop_column("bookmarks", "attrs")
    op.drop_column("folders", "toolbar_attrs")
    op.drop_column("folders", "attrs")
