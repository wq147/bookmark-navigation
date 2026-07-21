from datetime import UTC, datetime
import threading

import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import db
from app.db import configure_sqlite
from app.models import Base, Bookmark, Folder, User


@pytest.fixture
def session(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'models.db'}")
    try:
        configure_sqlite(engine)
        Base.metadata.create_all(engine)
        with Session(engine) as database_session:
            database_session.add(User(id=1, username="owner", password_hash="test"))
            database_session.commit()
            yield database_session
    finally:
        engine.dispose()


def test_duplicate_active_normalized_url_is_rejected(session):
    folder = Folder(user_id=1, base_name="Root", position=1)
    session.add(folder)
    session.flush()
    session.add_all(
        [
            Bookmark(
                user_id=1,
                title="A",
                url="https://x.test/",
                normalized_url="https://x.test",
                folder_id=folder.id,
            ),
            Bookmark(
                user_id=1,
                title="B",
                url="https://x.test",
                normalized_url="https://x.test",
                folder_id=folder.id,
            ),
        ]
    )
    with pytest.raises(IntegrityError):
        session.commit()


def test_folder_renumbering_does_not_change_id(session):
    folder = Folder(user_id=1, base_name="Codex", position=2)
    session.add(folder)
    session.commit()
    stable_id = folder.id

    folder.position = 3
    session.commit()

    assert folder.id == stable_id


def test_sibling_folder_name_and_position_are_unique(session):
    parent = Folder(user_id=1, base_name="Parent", position=1)
    session.add(parent)
    session.flush()
    session.add_all(
        [
            Folder(user_id=1, parent_id=parent.id, base_name="Same", position=1),
            Folder(user_id=1, parent_id=parent.id, base_name="Same", position=2),
        ]
    )
    with pytest.raises(IntegrityError):
        session.commit()


def test_root_folder_name_is_unique(session):
    session.add_all(
        [Folder(user_id=1, base_name="Same", position=1), Folder(user_id=1, base_name="Same", position=2)]
    )
    with pytest.raises(IntegrityError):
        session.commit()


def test_sibling_folder_position_is_unique(session):
    parent = Folder(user_id=1, base_name="Parent", position=1)
    session.add(parent)
    session.flush()
    session.add_all(
        [
            Folder(user_id=1, parent_id=parent.id, base_name="First", position=1),
            Folder(user_id=1, parent_id=parent.id, base_name="Second", position=1),
        ]
    )
    with pytest.raises(IntegrityError):
        session.commit()


def test_root_folder_position_is_unique(session):
    session.add_all(
        [Folder(user_id=1, base_name="First", position=1), Folder(user_id=1, base_name="Second", position=1)]
    )
    with pytest.raises(IntegrityError):
        session.commit()


def test_deleted_bookmark_does_not_reserve_normalized_url(session):
    folder = Folder(user_id=1, base_name="Root", position=1)
    session.add(folder)
    session.flush()
    session.add_all(
        [
            Bookmark(
                user_id=1,
                title="Old",
                url="https://x.test",
                normalized_url="https://x.test",
                folder_id=folder.id,
                deleted_at=datetime(2024, 1, 1, tzinfo=UTC),
            ),
            Bookmark(
                user_id=1,
                title="New",
                url="https://x.test",
                normalized_url="https://x.test",
                folder_id=folder.id,
            ),
        ]
    )

    session.commit()


def test_sqlite_connection_pragmas_are_configured(tmp_path, request):
    engine = create_engine(f"sqlite:///{tmp_path / 'pragmas.db'}")
    request.addfinalizer(engine.dispose)
    configure_sqlite(engine)

    with engine.connect() as connection:
        pragmas = connection.exec_driver_sql(
            "SELECT * FROM pragma_foreign_keys"
        ).scalar_one()
        timeout = connection.exec_driver_sql("PRAGMA busy_timeout").scalar_one()
        journal_mode = connection.exec_driver_sql("PRAGMA journal_mode").scalar_one()

    assert pragmas == 1
    assert timeout == 5000
    assert journal_mode == "wal"


def test_get_session_can_be_entered_and_finalized_on_different_threads(
    tmp_path, monkeypatch, request
):
    engine = create_engine(f"sqlite:///{tmp_path / 'cross-thread.db'}")
    request.addfinalizer(engine.dispose)
    factory = lambda: Session(engine)  # noqa: E731
    monkeypatch.setattr(db, "SessionLocal", factory)
    dependency = db.get_session()
    entered = threading.Event()
    release_enter_thread = threading.Event()
    errors: list[BaseException] = []

    def enter() -> None:
        try:
            next(dependency)
            entered.set()
            release_enter_thread.wait(5)
        except BaseException as error:
            errors.append(error)

    def finalize() -> None:
        try:
            dependency.close()
        except BaseException as error:
            errors.append(error)

    first = threading.Thread(target=enter)
    first.start()
    assert entered.wait(5)
    second = threading.Thread(target=finalize)
    second.start()
    second.join(5)
    release_enter_thread.set()
    first.join(5)

    assert not second.is_alive()
    assert errors == []
    with db.database_session_barrier():
        pass
