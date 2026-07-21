import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import Session

from app.import_service import ImportStateError, apply_batch
from app.models import ImportBatch


def test_attrs_migration_upgrades_and_downgrades(tmp_path):
    database = tmp_path / "migration.db"
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", f"sqlite:///{database}")

    command.upgrade(config, "head")
    engine = create_engine(f"sqlite:///{database}")
    assert "attrs" in {column["name"] for column in inspect(engine).get_columns("folders")}
    assert "attrs" in {column["name"] for column in inspect(engine).get_columns("bookmarks")}
    assert "attrs" in {column["name"] for column in inspect(engine).get_columns("import_items")}
    assert "is_protected" in {
        column["name"] for column in inspect(engine).get_columns("backups")
    }
    assert {"is_admin", "is_active", "must_change_password"} <= {
        column["name"] for column in inspect(engine).get_columns("users")
    }
    for table in ("folders", "bookmarks", "import_batches", "operations"):
        assert "user_id" in {
            column["name"] for column in inspect(engine).get_columns(table)
        }
    engine.dispose()

    command.downgrade(config, "0003_import_preview")
    engine = create_engine(f"sqlite:///{database}")
    assert "attrs" not in {column["name"] for column in inspect(engine).get_columns("folders")}
    assert "attrs" not in {column["name"] for column in inspect(engine).get_columns("bookmarks")}
    assert "attrs" not in {column["name"] for column in inspect(engine).get_columns("import_items")}
    assert "is_protected" not in {
        column["name"] for column in inspect(engine).get_columns("backups")
    }
    engine.dispose()

    command.upgrade(config, "head")


def test_empty_folder_migration_invalidates_existing_previews(tmp_path):
    database = tmp_path / "pre-0006.db"
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", f"sqlite:///{database}")
    command.upgrade(config, "0005_backup_protection")
    engine = create_engine(f"sqlite:///{database}")
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO users (username, password_hash) "
                "VALUES ('migration-owner', 'not-a-login-hash')"
            )
        )
        connection.execute(
            text(
                "INSERT INTO import_batches "
                "(source_name, status, expires_at) "
                "VALUES ('sha256:legacy', 'previewed', '2099-01-01 00:00:00')"
            )
        )
    engine.dispose()

    command.upgrade(config, "head")
    engine = create_engine(f"sqlite:///{database}")
    with Session(engine) as session:
        batch = session.get(ImportBatch, 1)
        assert batch.status == "expired"
        with pytest.raises(ImportStateError, match="expired"):
            apply_batch(session, batch.user_id, batch, [])
    engine.dispose()


def test_multi_user_migration_preserves_nested_folders_and_bookmarks(tmp_path):
    database = tmp_path / "pre-0007.db"
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", f"sqlite:///{database}")
    command.upgrade(config, "0006_import_empty_folders")
    engine = create_engine(f"sqlite:///{database}")
    with engine.begin() as connection:
        connection.execute(text(
            "INSERT INTO users (id, username, password_hash) "
            "VALUES (1, 'migration-owner', 'not-a-login-hash')"
        ))
        connection.execute(text(
            "INSERT INTO folders (id, parent_id, base_name, position) VALUES "
            "(1, NULL, 'Root', 1), (2, 1, 'Child', 1), (3, 2, 'Grandchild', 1)"
        ))
        connection.execute(text(
            "INSERT INTO bookmarks "
            "(id, folder_id, title, url, normalized_url, position) VALUES "
            "(1, 2, 'Nested', 'https://nested.test', 'https://nested.test', 1), "
            "(2, 3, 'Deep', 'https://deep.test', 'https://deep.test', 1)"
        ))
    engine.dispose()

    command.upgrade(config, "head")

    engine = create_engine(f"sqlite:///{database}")
    with engine.connect() as connection:
        assert connection.execute(text("SELECT count(*) FROM folders")).scalar_one() == 3
        assert connection.execute(text("SELECT count(*) FROM bookmarks")).scalar_one() == 2
        assert connection.execute(text(
            "SELECT count(*) FROM folders WHERE user_id = 1"
        )).scalar_one() == 3
        assert connection.execute(text(
            "SELECT count(*) FROM bookmarks WHERE user_id = 1"
        )).scalar_one() == 2
        assert connection.execute(text(
            "SELECT count(*) FROM folders child JOIN folders parent "
            "ON child.parent_id = parent.id "
            "WHERE child.user_id != parent.user_id"
        )).scalar_one() == 0
        assert connection.execute(text("PRAGMA foreign_key_check")).all() == []
    engine.dispose()


def test_multi_user_migration_assigns_data_to_earliest_created_account(tmp_path):
    database = tmp_path / "pre-0007-user-order.db"
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", f"sqlite:///{database}")
    command.upgrade(config, "0006_import_empty_folders")
    engine = create_engine(f"sqlite:///{database}")
    with engine.begin() as connection:
        connection.execute(text(
            "INSERT INTO users (id, username, password_hash, created_at) VALUES "
            "(1, 'later-user', 'hash', '2026-01-02 00:00:00'), "
            "(9, 'earliest-user', 'hash', '2026-01-01 00:00:00')"
        ))
        connection.execute(text(
            "INSERT INTO folders (id, parent_id, base_name, position) "
            "VALUES (1, NULL, 'Legacy', 1)"
        ))
    engine.dispose()

    command.upgrade(config, "head")

    engine = create_engine(f"sqlite:///{database}")
    with engine.connect() as connection:
        assert connection.execute(text(
            "SELECT id FROM users WHERE is_admin = 1"
        )).scalar_one() == 9
        assert connection.execute(text(
            "SELECT user_id FROM folders WHERE id = 1"
        )).scalar_one() == 9
    engine.dispose()
