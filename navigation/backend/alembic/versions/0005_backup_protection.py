"""Protect restore recovery anchors from retention.

Revision ID: 0005_backup_protection
"""

import sqlalchemy as sa
from alembic import op

revision = "0005_backup_protection"
down_revision = "0004_netscape_attrs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "backups",
        sa.Column(
            "is_protected",
            sa.Boolean(),
            nullable=False,
            server_default="0",
        ),
    )


def downgrade() -> None:
    op.drop_column("backups", "is_protected")
