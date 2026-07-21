import hashlib
import stat
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

from app.db import configure_sqlite, database_session_barrier, get_session
from app.backup_service import create_backup
from app.main import app
from app.models import Backup, Base, Bookmark, Folder, ImportBatch, User
from app.security import hash_password


def netscape(*links: tuple[str, str], folder: str = "Imported") -> bytes:
    anchors = "\n".join(f'<DT><A HREF="{url}">{title}</A>' for title, url in links)
    return (
        "<!DOCTYPE NETSCAPE-Bookmark-file-1>\n"
        "<DL><p><DT><H3 PERSONAL_TOOLBAR_FOLDER=\"true\">书签栏</H3><DL><p>\n"
        f"<DT><H3>{folder}</H3><DL><p>{anchors}</DL><p>\n"
        "</DL><p></DL><p>"
    ).encode()


@pytest.fixture
def session_factory(tmp_path, monkeypatch):
    database_path = tmp_path / "bookmarks.db"
    engine = create_engine(f"sqlite:///{database_path}")
    configure_sqlite(engine)
    Base.metadata.create_all(engine)
    monkeypatch.setenv("NAV_BACKUP_DIR", str(tmp_path / "backups"))
    monkeypatch.setenv(
        "NAV_BOOKMARK_POLICY_PATH",
        str(Path(__file__).parents[3] / "bookmark_policy.json"),
    )
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    yield factory
    engine.dispose()


@pytest.fixture
def auth_client(session_factory, monkeypatch):
    monkeypatch.setenv("NAV_TEST_MODE", "1")

    def override_session():
        with database_session_barrier():
            with session_factory() as session:
                yield session

    app.dependency_overrides[get_session] = override_session
    with session_factory() as session:
        session.add(
            User(
                username="bookmark-user",
                password_hash=hash_password("secret"),
                is_admin=True,
            )
        )
        session.commit()
    with TestClient(app, client=("127.0.0.1", 50001)) as client:
        login = client.post(
            "/api/v1/auth/login",
            json={"username": "bookmark-user", "password": "secret"},
        )
        client.headers["X-CSRF-Token"] = login.json()["csrf_token"]
        yield client
    app.dependency_overrides.clear()


def bookmark_count(session_factory) -> int:
    with session_factory() as session:
        return session.scalar(select(func.count()).select_from(Bookmark)) or 0


def preview(auth_client, content: bytes):
    return auth_client.post(
        "/api/v1/imports/preview",
        files={"file": ("bookmarks.html", content, "text/html")},
    )


def test_preview_does_not_mutate_and_missing_urls_do_not_delete(auth_client, session_factory):
    with session_factory() as session:
        folder = Folder(user_id=1, base_name="01_常用", position=1)
        session.add(folder)
        session.flush()
        session.add(
            Bookmark(
                user_id=1,
                folder_id=folder.id,
                title="Keep me",
                url="https://keep.test",
                normalized_url="https://keep.test",
            )
        )
        session.commit()
    before = bookmark_count(session_factory)

    response = preview(auth_client, netscape(("New", "https://new.test"), folder="未知来源"))

    assert response.status_code == 200
    assert bookmark_count(session_factory) == before
    assert "delete" not in response.json()["summary"]
    assert response.json()["summary"]["new"] == 1


def test_existing_url_keeps_server_fields_by_default(auth_client, session_factory):
    with session_factory() as session:
        folder = Folder(user_id=1, base_name="01_常用", position=1)
        session.add(folder)
        session.flush()
        bookmark = Bookmark(
            user_id=1,
            folder_id=folder.id,
            title="Server title",
            url="https://same.test",
            normalized_url="https://same.test",
            notes="Server notes",
        )
        session.add(bookmark)
        session.commit()
        bookmark_id = bookmark.id

    batch = preview(
        auth_client,
        netscape(("Imported title", "https://same.test"), folder="02_AI 与智能开发"),
    )
    assert batch.status_code == 200
    item = batch.json()["items"][0]
    assert item["status"] in {"conflict", "suggested_move"}
    applied = auth_client.post(
        f"/api/v1/imports/{batch.json()['id']}/apply", json={"overrides": []}
    )
    assert applied.status_code == 200
    with session_factory() as session:
        stored = session.get(Bookmark, bookmark_id)
        assert stored.title == "Server title"
        assert stored.notes == "Server notes"
        assert stored.folder_id == folder.id


def test_explicit_per_field_conflict_choices_overwrite_selected_fields(
    auth_client, session_factory
):
    with session_factory() as session:
        server_folder = Folder(user_id=1, base_name="01_常用", position=1)
        session.add(server_folder)
        session.flush()
        bookmark = Bookmark(
            user_id=1,
            folder_id=server_folder.id,
            title="Server title",
            url="https://platform.openai.com/home",
            normalized_url="https://platform.openai.com/home",
            notes="Server notes",
        )
        session.add(bookmark)
        session.commit()
        bookmark_id = bookmark.id

    batch = preview(
        auth_client,
        netscape(("Imported title", "https://platform.openai.com/home"), folder="Anything"),
    ).json()
    item = batch["items"][0]
    applied = auth_client.post(
        f"/api/v1/imports/{batch['id']}/apply",
        json={
            "overrides": [
                {
                    "item_id": item["id"],
                    "overwrite_title": True,
                    "overwrite_folder": True,
                }
            ]
        },
    )
    assert applied.status_code == 200
    with session_factory() as session:
        stored = session.get(Bookmark, bookmark_id)
        folder = session.get(Folder, stored.folder_id)
        assert stored.title == "Imported title"
        assert stored.notes == "Server notes"
        assert folder.base_name == "模型、API 与算力"


def test_dd_notes_are_imported_and_can_explicitly_overwrite_server_notes(
    auth_client, session_factory
):
    new_html = netscape(("New note", "https://new-note.test")).replace(
        b"</A>", b"</A><DD>Uploaded private note", 1
    )
    new_batch = preview(auth_client, new_html).json()
    assert auth_client.post(
        f"/api/v1/imports/{new_batch['id']}/apply", json={"overrides": []}
    ).status_code == 200
    with session_factory() as session:
        imported = session.scalar(
            select(Bookmark).where(Bookmark.normalized_url == "https://new-note.test")
        )
        assert imported.notes == "Uploaded private note"

        folder = session.get(Folder, imported.folder_id)
        existing = Bookmark(
            user_id=1,
            folder_id=folder.id,
            title="Existing",
            url="https://note-conflict.test",
            normalized_url="https://note-conflict.test",
            notes="Server note",
        )
        session.add(existing)
        session.commit()

    conflict_html = netscape(("Existing", "https://note-conflict.test")).replace(
        b"</A>", b"</A><DD>Uploaded replacement", 1
    )
    conflict = preview(auth_client, conflict_html).json()
    assert conflict["items"][0]["status"] == "conflict"
    item_id = conflict["items"][0]["id"]
    applied = auth_client.post(
        f"/api/v1/imports/{conflict['id']}/apply",
        json={"overrides": [{"item_id": item_id, "overwrite_notes": True}]},
    )
    assert applied.status_code == 200
    with session_factory() as session:
        stored = session.scalar(
            select(Bookmark).where(
                Bookmark.normalized_url == "https://note-conflict.test"
            )
        )
        assert stored.notes == "Uploaded replacement"


def test_dd_note_conflict_preserves_server_note_without_override(
    auth_client, session_factory
):
    with session_factory() as session:
        folder = Folder(user_id=1, base_name="01_常用", position=1)
        session.add(folder)
        session.flush()
        session.add(
            Bookmark(
                user_id=1,
                folder_id=folder.id,
                title="Preserve",
                url="https://note-preserve.test",
                normalized_url="https://note-preserve.test",
                notes="Server note stays",
            )
        )
        session.commit()
    content = netscape(("Preserve", "https://note-preserve.test")).replace(
        b"</A>", b"</A><DD>Uploaded note is not automatic", 1
    )
    batch = preview(auth_client, content).json()
    assert batch["items"][0]["status"] == "conflict"
    response = auth_client.post(
        f"/api/v1/imports/{batch['id']}/apply", json={"overrides": []}
    )
    assert response.status_code == 200
    with session_factory() as session:
        stored = session.scalar(
            select(Bookmark).where(
                Bookmark.normalized_url == "https://note-preserve.test"
            )
        )
        assert stored.notes == "Server note stays"


def test_unclassified_new_url_goes_to_inbox(auth_client, session_factory):
    batch = preview(
        auth_client, netscape(("Unknown", "https://unknown.invalid/path"), folder="Mystery")
    )
    assert batch.status_code == 200
    assert batch.json()["summary"]["unclassified"] == 1
    result = auth_client.post(
        f"/api/v1/imports/{batch.json()['id']}/apply", json={"overrides": []}
    )
    assert result.status_code == 200
    assert result.json()["created"][0]["folder_path"] == ["00_待整理"]


def test_imported_folders_follow_policy_order(auth_client, session_factory):
    with session_factory() as session:
        session.add(Folder(user_id=1, base_name="01_常用", position=1))
        session.commit()
    batch = preview(
        auth_client, netscape(("Unknown", "https://order.invalid"), folder="Mystery")
    ).json()
    response = auth_client.post(
        f"/api/v1/imports/{batch['id']}/apply", json={"overrides": []}
    )
    assert response.status_code == 200
    with session_factory() as session:
        roots = session.scalars(
            select(Folder).where(Folder.parent_id.is_(None)).order_by(Folder.position)
        ).all()
        assert [(folder.base_name, folder.position) for folder in roots] == [
            ("00_待整理", 1),
            ("01_常用", 2),
        ]


def test_apply_preserves_empty_folder_attrs_and_toolbar_attrs(auth_client, session_factory):
    content = b"""<!DOCTYPE NETSCAPE-Bookmark-file-1>
<DL><p><DT><H3 PERSONAL_TOOLBAR_FOLDER="true" LAST_MODIFIED="100">Bookmarks bar</H3><DL><p>
<DT><H3 ADD_DATE="10" LAST_MODIFIED="11">00_\xe5\xbe\x85\xe6\x95\xb4\xe7\x90\x86</H3><DL><p>
<DT><H3 ADD_DATE="12">01_\xe5\xad\x90\xe7\x9b\xae\xe5\xbd\x95</H3><DL><p></DL><p>
</DL><p>
<DT><H3 ADD_DATE="20">01_\xe5\xb8\xb8\xe7\x94\xa8</H3><DL><p>
<DT><A HREF="https://example.test/preserved">Preserved</A>
</DL><p></DL><p></DL><p>"""
    batch = preview(auth_client, content).json()
    response = auth_client.post(
        f"/api/v1/imports/{batch['id']}/apply", json={"overrides": []}
    )
    assert response.status_code == 200

    with session_factory() as session:
        roots = session.scalars(
            select(Folder).where(Folder.parent_id.is_(None)).order_by(Folder.position)
        ).all()
        assert [(folder.base_name, folder.position) for folder in roots] == [
            ("00_\u5f85\u6574\u7406", 1),
            ("01_\u5e38\u7528", 2),
        ]
        assert roots[0].attrs == {"add_date": "10", "last_modified": "11"}
        assert roots[1].attrs == {"add_date": "20"}
        child = session.scalar(select(Folder).where(Folder.parent_id == roots[0].id))
        assert (child.base_name, child.position, child.attrs) == (
            "\u5b50\u76ee\u5f55",
            1,
            {"add_date": "12"},
        )
        assert roots[0].toolbar_attrs == {
            "personal_toolbar_folder": "true",
            "last_modified": "100",
        }


def test_empty_child_does_not_erase_populated_ancestor_attrs(auth_client, session_factory):
    content = b"""<!DOCTYPE NETSCAPE-Bookmark-file-1>
<DL><p><DT><H3 PERSONAL_TOOLBAR_FOLDER="true">Bookmarks bar</H3><DL><p>
<DT><H3 ADD_DATE="20" LAST_MODIFIED="21">01_\xe5\xb8\xb8\xe7\x94\xa8</H3><DL><p>
<DT><H3 ADD_DATE="30">01_Empty child</H3><DL><p></DL><p>
<DT><A HREF="https://example.test/populated">Populated</A>
</DL><p></DL><p></DL><p>"""
    batch = preview(auth_client, content).json()
    response = auth_client.post(
        f"/api/v1/imports/{batch['id']}/apply", json={"overrides": []}
    )
    assert response.status_code == 200

    with session_factory() as session:
        parent = session.scalar(select(Folder).where(Folder.base_name == "01_\u5e38\u7528"))
        child = session.scalar(select(Folder).where(Folder.parent_id == parent.id))
        assert parent.attrs == {"add_date": "20", "last_modified": "21"}
        assert child.attrs == {"add_date": "30"}


def test_batch_can_be_read_but_expired_or_applied_batch_cannot_be_applied_twice(
    auth_client, session_factory
):
    batch = preview(auth_client, netscape(("One", "https://one.test"))).json()
    fetched = auth_client.get(f"/api/v1/imports/{batch['id']}")
    assert fetched.status_code == 200
    assert fetched.json()["items"][0]["source_url"] == "https://one.test"
    assert auth_client.post(
        f"/api/v1/imports/{batch['id']}/apply", json={"overrides": []}
    ).status_code == 200
    assert auth_client.post(
        f"/api/v1/imports/{batch['id']}/apply", json={"overrides": []}
    ).status_code == 409

    expired = preview(auth_client, netscape(("Two", "https://two.test"))).json()
    with session_factory() as session:
        stored = session.get(ImportBatch, expired["id"])
        stored.expires_at = datetime.now(UTC).replace(tzinfo=None) - timedelta(seconds=1)
        session.commit()
    response = auth_client.post(
        f"/api/v1/imports/{expired['id']}/apply", json={"overrides": []}
    )
    assert response.status_code == 409
    assert bookmark_count(session_factory) == 1


def test_preview_rejects_non_html_and_oversized_upload(auth_client, monkeypatch):
    non_html = auth_client.post(
        "/api/v1/imports/preview",
        files={"file": ("bookmarks.txt", b"plain text", "text/plain")},
    )
    assert non_html.status_code == 415
    monkeypatch.setenv("NAV_IMPORT_MAX_BYTES", "64")
    oversized = preview(auth_client, netscape(("Large", "https://large.test")))
    assert oversized.status_code == 413


def test_preview_accepts_parameterized_html_media_type(auth_client):
    response = auth_client.post(
        "/api/v1/imports/preview",
        files={
            "file": (
                "bookmarks.html",
                netscape(("Typed", "https://typed.test")),
                "text/html; charset=UTF-8",
            )
        },
    )
    assert response.status_code == 200


def test_overrides_are_rejected_for_items_without_conflicts(auth_client):
    batch = preview(auth_client, netscape(("New", "https://not-conflict.test"))).json()
    response = auth_client.post(
        f"/api/v1/imports/{batch['id']}/apply",
        json={
            "overrides": [
                {"item_id": batch["items"][0]["id"], "overwrite_title": True}
            ]
        },
    )
    assert response.status_code == 400


def test_apply_creates_atomic_checksummed_sqlite_backup_before_mutation(
    auth_client, session_factory, tmp_path
):
    batch = preview(auth_client, netscape(("Backed up", "https://backup.test"))).json()
    result = auth_client.post(
        f"/api/v1/imports/{batch['id']}/apply", json={"overrides": []}
    )
    assert result.status_code == 200
    with session_factory() as session:
        applied_batch = session.get(ImportBatch, batch["id"])
        backup = session.get(Backup, applied_batch.backup_id)
        backup_path = Path(backup.path)
        assert backup_path.is_file()
        assert hashlib.sha256(backup_path.read_bytes()).hexdigest() == backup.checksum

        backup_engine = create_engine(f"sqlite:///{backup_path}")
        with backup_engine.connect() as connection:
            count = connection.execute(select(func.count()).select_from(Bookmark)).scalar_one()
        backup_engine.dispose()
        assert count == 0
        assert stat.S_IMODE(backup_path.stat().st_mode) == 0o600
        assert stat.S_IMODE((tmp_path / "backups").stat().st_mode) == 0o700


def test_apply_enforces_default_backup_retention(auth_client, monkeypatch):
    calls = []
    monkeypatch.setattr(
        "app.routers.imports.enforce_backup_retention",
        lambda session: calls.append(session),
    )
    batch = preview(auth_client, netscape(("Retained", "https://retained.test"))).json()
    response = auth_client.post(
        f"/api/v1/imports/{batch['id']}/apply", json={"overrides": []}
    )
    assert response.status_code == 200
    assert len(calls) == 1


def test_apply_rejects_preview_when_matching_bookmark_url_has_changed(
    auth_client, session_factory
):
    with session_factory() as session:
        folder = Folder(user_id=1, base_name="01_常用", position=1)
        session.add(folder)
        session.flush()
        bookmark = Bookmark(
            user_id=1,
            folder_id=folder.id,
            title="Server",
            url="https://stale.test",
            normalized_url="https://stale.test",
        )
        session.add(bookmark)
        session.commit()
        bookmark_id = bookmark.id
    batch = preview(
        auth_client, netscape(("Imported", "https://stale.test"), folder="Anything")
    ).json()
    with session_factory() as session:
        bookmark = session.get(Bookmark, bookmark_id)
        bookmark.url = "https://changed.test"
        bookmark.normalized_url = "https://changed.test"
        session.commit()

    response = auth_client.post(
        f"/api/v1/imports/{batch['id']}/apply", json={"overrides": []}
    )
    assert response.status_code == 409
    assert bookmark_count(session_factory) == 1


def test_apply_rejects_new_url_that_was_created_after_preview(
    auth_client, session_factory
):
    batch = preview(auth_client, netscape(("Imported", "https://race.test"))).json()
    with session_factory() as session:
        folder = Folder(user_id=1, base_name="01_常用", position=1)
        session.add(folder)
        session.flush()
        session.add(
            Bookmark(
                user_id=1,
                folder_id=folder.id,
                title="Concurrent",
                url="https://race.test",
                normalized_url="https://race.test",
            )
        )
        session.commit()
    response = auth_client.post(
        f"/api/v1/imports/{batch['id']}/apply", json={"overrides": []}
    )
    assert response.status_code == 409
    assert bookmark_count(session_factory) == 1


def test_failed_apply_removes_untracked_backup(
    auth_client, session_factory, tmp_path, monkeypatch
):
    batch = preview(auth_client, netscape(("Fail", "https://fail.test"))).json()
    monkeypatch.setattr(
        "app.import_service._assert_tree_is_valid",
        lambda _session, _user_id: (_ for _ in ()).throw(RuntimeError("forced failure")),
    )
    with pytest.raises(RuntimeError, match="forced failure"):
        auth_client.post(
            f"/api/v1/imports/{batch['id']}/apply", json={"overrides": []}
        )
    assert bookmark_count(session_factory) == 0
    assert list((tmp_path / "backups").glob("*.sqlite3")) == []


def test_backup_publish_is_removed_if_database_row_flush_fails(
    session_factory, tmp_path, monkeypatch
):
    with session_factory() as session:
        monkeypatch.setattr(
            session, "flush", lambda: (_ for _ in ()).throw(RuntimeError("flush failed"))
        )
        with pytest.raises(RuntimeError, match="flush failed"):
            create_backup(session, "flush-failure")
    assert list((tmp_path / "backups").glob("*.sqlite3")) == []
