"""Preserve empty folders in import previews.

Existing previews are expired because their original HTML and empty-folder
metadata cannot be reconstructed. Downgrade drops the manifest column but does
not reactivate those batches; a new preview is required in either direction.

Revision ID: 0006_import_empty_folders
"""

import sqlalchemy as sa
from alembic import op

revision = "0006_import_empty_folders"
down_revision = "0005_backup_protection"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "import_batches",
        sa.Column("folder_manifest", sa.JSON(), nullable=False, server_default="{}"),
    )
    op.execute(
        "UPDATE import_batches SET status = 'expired' WHERE status = 'previewed'"
    )


def downgrade() -> None:
    op.drop_column("import_batches", "folder_manifest")
