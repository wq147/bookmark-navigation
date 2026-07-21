"""Add multi-user ownership, account state, and administrative audit.

Revision ID: 0007_multi_user
"""

import sqlalchemy as sa
from alembic import op


revision = "0007_multi_user"
down_revision = "0006_import_empty_folders"
branch_labels = None
depends_on = None


def _primary_user_id(connection) -> int | None:
    return connection.execute(
        sa.text("SELECT id FROM users ORDER BY created_at ASC, id ASC LIMIT 1")
    ).scalar()


def upgrade() -> None:
    connection = op.get_bind()
    op.add_column(
        "users", sa.Column("is_admin", sa.Boolean(), server_default="0", nullable=False)
    )
    op.add_column(
        "users", sa.Column("is_active", sa.Boolean(), server_default="1", nullable=False)
    )
    op.add_column(
        "users",
        sa.Column("must_change_password", sa.Boolean(), server_default="0", nullable=False),
    )
    primary_user_id = _primary_user_id(connection)
    if primary_user_id is not None:
        connection.execute(
            sa.text("UPDATE users SET is_admin = CASE WHEN id = :id THEN 1 ELSE 0 END"),
            {"id": primary_user_id},
        )

    for table in ("folders", "bookmarks", "import_batches", "operations"):
        op.add_column(table, sa.Column("user_id", sa.Integer(), nullable=True))
        if primary_user_id is not None:
            connection.execute(
                sa.text(f"UPDATE {table} SET user_id = :id"), {"id": primary_user_id}
            )
        elif connection.execute(sa.text(f"SELECT count(*) FROM {table}")).scalar():
            if table in {"import_batches", "operations"}:
                connection.execute(sa.text(f"DELETE FROM {table}"))
            else:
                raise RuntimeError(f"Cannot assign existing {table} rows without a user")

    op.drop_index("uq_folders_parent_name", table_name="folders")
    op.drop_index("uq_folders_parent_position", table_name="folders")
    with op.batch_alter_table(
        "folders",
        recreate="always",
        naming_convention={"uq": "uq_%(table_name)s_%(column_0_N_name)s"},
    ) as batch:
        batch.drop_constraint("uq_folders_parent_id_base_name", type_="unique")
        batch.drop_constraint("uq_folders_parent_id_position", type_="unique")
        batch.alter_column("user_id", existing_type=sa.Integer(), nullable=False)
        batch.create_foreign_key(
            "fk_folders_user_id", "users", ["user_id"], ["id"], ondelete="CASCADE"
        )
    op.drop_index("uq_bookmarks_active_normalized_url", table_name="bookmarks")
    with op.batch_alter_table("bookmarks", recreate="always") as batch:
        batch.alter_column("user_id", existing_type=sa.Integer(), nullable=False)
        batch.create_foreign_key(
            "fk_bookmarks_user_id", "users", ["user_id"], ["id"], ondelete="CASCADE"
        )
    op.create_index(
        "uq_bookmarks_active_normalized_url",
        "bookmarks",
        ["user_id", "normalized_url"],
        unique=True,
        sqlite_where=sa.text("deleted_at IS NULL"),
    )

    for table in ("import_batches", "operations"):
        with op.batch_alter_table(table, recreate="always") as batch:
            batch.alter_column("user_id", existing_type=sa.Integer(), nullable=False)
            batch.create_foreign_key(
                f"fk_{table}_user_id",
                "users",
                ["user_id"],
                ["id"],
                ondelete="CASCADE",
            )

    op.create_index(
        "uq_folders_parent_name",
        "folders",
        ["user_id", sa.text("coalesce(parent_id, 0)"), "base_name"],
        unique=True,
    )
    op.create_index(
        "uq_folders_parent_position",
        "folders",
        ["user_id", sa.text("coalesce(parent_id, 0)"), "position"],
        unique=True,
    )

    op.create_table(
        "admin_audits",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("actor_user_id", sa.Integer(), nullable=True),
        sa.Column("target_user_id", sa.Integer(), nullable=True),
        sa.Column("target_username", sa.String(255), nullable=False),
        sa.Column("action", sa.String(100), nullable=False),
        sa.Column("result", sa.String(50), server_default="success", nullable=False),
        sa.Column(
            "created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False
        ),
        sa.ForeignKeyConstraint(["actor_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["target_user_id"], ["users.id"], ondelete="SET NULL"),
    )


def downgrade() -> None:
    op.drop_table("admin_audits")
    op.drop_index("uq_folders_parent_name", table_name="folders")
    op.drop_index("uq_folders_parent_position", table_name="folders")
    for table in ("operations", "import_batches"):
        with op.batch_alter_table(table, recreate="always") as batch:
            batch.drop_column("user_id")

    op.drop_index("uq_bookmarks_active_normalized_url", table_name="bookmarks")
    with op.batch_alter_table("bookmarks", recreate="always") as batch:
        batch.drop_column("user_id")
    op.create_index(
        "uq_bookmarks_active_normalized_url",
        "bookmarks",
        ["normalized_url"],
        unique=True,
        sqlite_where=sa.text("deleted_at IS NULL"),
    )

    with op.batch_alter_table("folders", recreate="always") as batch:
        batch.drop_column("user_id")
        batch.create_unique_constraint(
            "uq_folders_parent_id_base_name", ["parent_id", "base_name"]
        )
        batch.create_unique_constraint(
            "uq_folders_parent_id_position", ["parent_id", "position"]
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
    for column in ("must_change_password", "is_active", "is_admin"):
        op.drop_column("users", column)
