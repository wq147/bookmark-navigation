"""Store immutable import previews and their backup relationship.

Revision ID: 0003_import_preview
"""

import sqlalchemy as sa
from alembic import op

revision = "0003_import_preview"
down_revision = "0002_bookmark_notes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("import_batches") as batch:
        batch.add_column(sa.Column("expires_at", sa.DateTime(), nullable=True))
        batch.add_column(sa.Column("backup_id", sa.Integer(), nullable=True))
        batch.create_foreign_key(
            "fk_import_batches_backup_id",
            "backups",
            ["backup_id"],
            ["id"],
            ondelete="SET NULL",
        )
    op.execute("UPDATE import_batches SET expires_at = datetime('now', '+1 day')")
    with op.batch_alter_table("import_batches") as batch:
        batch.alter_column("expires_at", nullable=False)

    with op.batch_alter_table("import_items") as batch:
        batch.add_column(
            sa.Column("title", sa.String(1024), nullable=False, server_default="")
        )
        batch.add_column(sa.Column("notes", sa.Text(), nullable=False, server_default=""))
        batch.add_column(sa.Column("normalized_url", sa.Text(), nullable=False, server_default=""))
        batch.add_column(sa.Column("folder_path", sa.Text(), nullable=False, server_default="[]"))
        batch.add_column(
            sa.Column(
                "classification_method",
                sa.String(50),
                nullable=False,
                server_default="unclassified",
            )
        )


def downgrade() -> None:
    with op.batch_alter_table("import_items") as batch:
        batch.drop_column("classification_method")
        batch.drop_column("folder_path")
        batch.drop_column("normalized_url")
        batch.drop_column("notes")
        batch.drop_column("title")
    with op.batch_alter_table("import_batches") as batch:
        batch.drop_constraint("fk_import_batches_backup_id", type_="foreignkey")
        batch.drop_column("backup_id")
        batch.drop_column("expires_at")
