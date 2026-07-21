import hashlib
import os
import sqlite3
import threading
import time
from contextlib import closing
from urllib.parse import quote
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import func, select

import app.backup_service as backup_service
from app.backup_service import (
    BackupError,
    create_backup,
    enforce_backup_retention,
    prune_backups,
    sha256_file,
)
from app.db import database_session_barrier
from app.bookmark_domain import FolderNode, normalize_url, parse_html
from app.models import Backup, Bookmark, Folder, Operation, User
from test_imports import auth_client, session_factory  # noqa: F401

RESTORE_HEADERS = {"X-Confirm-Restore": "RESTORE ALL USERS"}
PRIVATE_FIXTURE_VALUE = os.getenv("NAV_PRIVATE_BOOKMARK_FIXTURE")
PRIVATE_FIXTURE_PATH = (
    Path(PRIVATE_FIXTURE_VALUE).expanduser() if PRIVATE_FIXTURE_VALUE else None
)


def _folder_attrs(tree):
    result = {}

    def walk(folder, path):
        for child in folder.children:
            if isinstance(child, FolderNode):
                child_path = path + (child.title,)
                result[child_path] = dict(child.attrs)
                walk(child, child_path)

    walk(tree.root, ())
    return result


def _populate(session_factory):
    with session_factory() as session:
        root = Folder(user_id=1, base_name="01_Root", position=1)
        session.add(root)
        session.flush()
        child = Folder(user_id=1, parent_id=root.id, base_name="Child", position=1)
        session.add(child)
        session.flush()
        session.add_all(
            [
                Bookmark(
                    user_id=1,
                    folder_id=root.id,
                    title="Escaped & title",
                    url="https://example.test/a?x=1&y=2",
                    normalized_url="https://example.test/a?x=1&y=2",
                    notes="private <note>",
                    position=1,
                ),
                Bookmark(
                    user_id=1,
                    folder_id=child.id,
                    title="Second",
                    url="https://second.test/path/",
                    normalized_url="https://second.test/path",
                    position=1,
                ),
            ]
        )
        session.commit()
        return root.id, child.id


def test_create_backup_closes_every_raw_sqlite_connection(
    session_factory, monkeypatch
):
    real_connect = sqlite3.connect
    connections = []

    class TrackingConnection(sqlite3.Connection):
        was_closed = False

        def close(self):
            self.was_closed = True
            super().close()

    class TrackingSqlite:
        DatabaseError = sqlite3.DatabaseError

        @staticmethod
        def connect(*args, **kwargs):
            kwargs["factory"] = TrackingConnection
            connection = real_connect(*args, **kwargs)
            connections.append(connection)
            return connection

    monkeypatch.setattr(backup_service, "sqlite3", TrackingSqlite)
    with session_factory() as session:
        create_backup(session, "connection-lifecycle")
        session.rollback()

    assert len(connections) == 2
    assert all(connection.was_closed for connection in connections)


def test_exports_require_authentication():
    from fastapi.testclient import TestClient
    from app.main import app

    with TestClient(app) as client:
        assert client.get("/api/v1/exports/bookmarks.html").status_code == 401
        assert client.get("/api/v1/exports/backup.json").status_code == 401
        assert client.get("/api/v1/backups").status_code == 401


def test_html_export_round_trip_preserves_urls_paths_and_notes(auth_client, session_factory):
    _populate(session_factory)
    response = auth_client.get("/api/v1/exports/bookmarks.html")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    tree = parse_html(response.text)
    records = tree.bookmarks()
    assert len(records) == 2
    assert {normalize_url(item.url) for item in records} == {
        "https://example.test/a?x=1&y=2",
        "https://second.test/path",
    }
    assert {item.path for item in records} == {
        ("01_Root",),
        ("01_Root", "01_Child"),
    }
    example = next(item for item in records if item.url.startswith("https://example.test"))
    assert example.notes == "private <note>"
    assert example.attrs["href"] == "https://example.test/a?x=1&y=2"


def test_json_export_is_audited_portable_document(auth_client, session_factory):
    _populate(session_factory)
    with session_factory() as session:
        session.add(Operation(user_id=1, operation_type="bookmark.update", payload='{"bookmark_id": 7}'))
        session.commit()
    response = auth_client.get("/api/v1/exports/backup.json")
    assert response.status_code == 200
    document = response.json()
    assert document["format"] == "private-bookmark-navigation"
    assert document["version"] == 1
    assert len(document["folders"]) == 2
    assert len(document["bookmarks"]) == 2
    assert document["bookmarks"][0]["notes"] == "private <note>"
    assert "attrs" in document["bookmarks"][0]
    assert "attrs" in document["folders"][0]
    assert document["audit"] == {"bookmark_count": 2, "folder_count": 2}
    assert document["operations"] == [{
        "id": 1,
        "operation_type": "bookmark.update",
        "payload": {"bookmark_id": 7},
        "created_at": document["operations"][0]["created_at"],
    }]


def test_restore_creates_pre_restore_backup_and_restores_database(
    auth_client, session_factory
):
    _populate(session_factory)
    with session_factory() as session:
        original = create_backup(session, "manual")
        session.commit()
        original_id = original.id
        session.add(Operation(user_id=1, operation_type="after-backup", payload="{}"))
        session.commit()

    response = auth_client.post(
        f"/api/v1/backups/{original_id}/restore", headers=RESTORE_HEADERS
    )
    assert response.status_code == 200
    pre_restore_id = response.json()["pre_restore_backup_id"]
    assert pre_restore_id != original_id
    with session_factory() as session:
        assert session.scalar(
            select(func.count()).select_from(Operation).where(
                Operation.operation_type == "after-backup"
            )
        ) == 0
        pre_restore = session.get(Backup, pre_restore_id)
        assert pre_restore is not None
        assert Path(pre_restore.path).is_file()


def test_restore_revokes_every_session_including_the_initiating_admin(
    auth_client, session_factory
):
    with session_factory() as session:
        backup = create_backup(session, "session-revocation")
        session.commit()

    response = auth_client.post(
        f"/api/v1/backups/{backup.id}/restore", headers=RESTORE_HEADERS
    )

    assert response.status_code == 200
    assert auth_client.get("/api/v1/auth/me").status_code == 401


def test_restore_requires_explicit_all_users_confirmation(auth_client, session_factory):
    with session_factory() as session:
        backup = create_backup(session, "confirmation-required")
        session.commit()

    response = auth_client.post(f"/api/v1/backups/{backup.id}/restore")

    assert response.status_code == 400
    assert response.json()["detail"] == (
        "X-Confirm-Restore must exactly equal RESTORE ALL USERS"
    )
    assert auth_client.get("/api/v1/auth/me").status_code == 200


def test_restore_upgrades_a_v6_snapshot_before_publishing(
    auth_client, session_factory, tmp_path
):
    legacy_path = tmp_path / "legacy-v6.sqlite3"
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", f"sqlite:///{legacy_path}")
    command.upgrade(config, "0006_import_empty_folders")
    with closing(sqlite3.connect(legacy_path)) as legacy:
        legacy.execute(
            "INSERT INTO users (id, username, password_hash) VALUES (1, ?, ?)",
            ("bookmark-user", "legacy-hash"),
        )
        legacy.execute(
            "INSERT INTO folders (id, parent_id, base_name, position) "
            "VALUES (1, NULL, 'Legacy folder', 1)"
        )
        legacy.commit()
    with session_factory() as session:
        backup = Backup(path=str(legacy_path), checksum=sha256_file(legacy_path))
        session.add(backup)
        session.commit()
        backup_id = backup.id

    response = auth_client.post(
        f"/api/v1/backups/{backup_id}/restore", headers=RESTORE_HEADERS
    )

    assert response.status_code == 200
    with session_factory() as session:
        restored = session.scalar(select(Folder).where(Folder.base_name == "Legacy folder"))
        assert restored.user_id == 1
        assert session.get(User, 1).is_admin is True


def test_concurrent_database_request_waits_for_restore_then_reads_restored_database(
    auth_client, session_factory, monkeypatch
):
    with session_factory() as session:
        restored = Folder(user_id=1, base_name="Restored", position=1)
        session.add(restored)
        session.commit()
        source = create_backup(session, "concurrency")
        session.commit()
        source_id = source.id
        session.add(Folder(user_id=1, base_name="Current only", position=2))
        session.commit()

    replace_entered = threading.Event()
    allow_replace = threading.Event()
    real_replace = os.replace

    def paused_replace(source, destination):
        if str(source).endswith(".restore"):
            replace_entered.set()
            assert allow_replace.wait(5)
        return real_replace(source, destination)

    monkeypatch.setattr("app.backup_service.os.replace", paused_replace)
    restore_result = {}
    read_result = {}
    restore_thread = threading.Thread(
        target=lambda: restore_result.setdefault(
            "response",
            auth_client.post(
                f"/api/v1/backups/{source_id}/restore", headers=RESTORE_HEADERS
            ),
        )
    )
    with database_session_barrier(), session_factory() as active_session:
        assert active_session.scalar(select(func.count()).select_from(Folder)) == 2
        restore_thread.start()
        time.sleep(0.1)
        assert restore_thread.is_alive(), "restore did not wait for the active session"
        assert not replace_entered.is_set()
    assert replace_entered.wait(5)
    read_thread = threading.Thread(
        target=lambda: read_result.setdefault("response", auth_client.get("/api/v1/folders"))
    )
    read_thread.start()
    time.sleep(0.1)
    assert read_thread.is_alive(), "concurrent request used the database during replacement"

    allow_replace.set()
    restore_thread.join(5)
    read_thread.join(5)
    assert restore_result["response"].status_code == 200
    assert read_result["response"].status_code == 401
    login = auth_client.post(
        "/api/v1/auth/login",
        json={"username": "bookmark-user", "password": "secret"},
    )
    auth_client.headers["X-CSRF-Token"] = login.json()["csrf_token"]
    assert [
        folder["base_name"] for folder in auth_client.get("/api/v1/folders").json()
    ] == ["Restored"]


def test_restore_enforces_default_retention(auth_client, session_factory, monkeypatch):
    with session_factory() as session:
        backup = create_backup(session, "retained-restore")
        session.commit()
        backup_id = backup.id
    calls = []
    monkeypatch.setattr(
        "app.routers.backups.enforce_backup_retention",
        lambda session: calls.append(session),
    )
    response = auth_client.post(
        f"/api/v1/backups/{backup_id}/restore", headers=RESTORE_HEADERS
    )
    assert response.status_code == 200
    assert len(calls) == 1


def test_restore_merges_catalog_and_retention_preserves_recovery_history(
    auth_client, session_factory
):
    with session_factory() as session:
        backups = []
        for index in range(35):
            backup = create_backup(session, f"history-{index}")
            session.commit()
            backups.append(
                {
                    "id": backup.id,
                    "path": backup.path,
                    "checksum": backup.checksum,
                }
            )
        source = backups[0]
        newest_thirty = backups[-30:]

    restored = auth_client.post(
        f"/api/v1/backups/{source['id']}/restore", headers=RESTORE_HEADERS
    )
    assert restored.status_code == 200
    pre_restore_id = restored.json()["pre_restore_backup_id"]

    def assert_catalog_consistent():
        with session_factory() as session:
            rows = list(session.scalars(select(Backup)).all())
            by_path = {row.path: row for row in rows}
            assert source["path"] in by_path
            assert by_path[source["path"]].is_protected is True
            pre_restore = session.get(Backup, pre_restore_id)
            assert pre_restore is not None
            assert pre_restore.is_protected is True
            for expected in newest_thirty:
                assert expected["path"] in by_path
            for row in rows:
                path = Path(row.path)
                assert path.is_file()
                assert hashlib.sha256(path.read_bytes()).hexdigest() == row.checksum
                with closing(sqlite3.connect(path)) as snapshot:
                    assert snapshot.execute("PRAGMA quick_check").fetchone() == ("ok",)
            return len(rows)

    first_count = assert_catalog_consistent()
    with session_factory() as session:
        enforce_backup_retention(session)
    assert assert_catalog_consistent() == first_count

    # The protected old source remains usable after repeated retention.
    with session_factory() as session:
        source_id = session.scalar(
            select(Backup.id).where(Backup.path == source["path"])
        )
    login = auth_client.post(
        "/api/v1/auth/login",
        json={"username": "bookmark-user", "password": "secret"},
    )
    auth_client.headers["X-CSRF-Token"] = login.json()["csrf_token"]
    assert (
        auth_client.post(
            f"/api/v1/backups/{source_id}/restore", headers=RESTORE_HEADERS
        ).status_code
        == 200
    )


def test_restore_rejects_checksum_mismatch(auth_client, session_factory):
    with session_factory() as session:
        backup = create_backup(session, "tamper")
        session.commit()
        backup_id = backup.id
        Path(backup.path).write_bytes(b"tampered")
    response = auth_client.post(
        f"/api/v1/backups/{backup_id}/restore", headers=RESTORE_HEADERS
    )
    assert response.status_code == 409
    assert "checksum" in response.json()["detail"].lower()


def test_recursive_folder_delete_requires_exact_confirmation_and_creates_backup(
    auth_client, session_factory
):
    root_id, _ = _populate(session_factory)
    rejected = auth_client.delete(f"/api/v1/folders/{root_id}?recursive=true")
    assert rejected.status_code == 400
    response = auth_client.delete(
        f"/api/v1/folders/{root_id}?recursive=true",
        headers={"X-Confirm-Delete": "01_Root"},
    )
    assert response.status_code == 200
    assert response.json()["backup_id"]
    with session_factory() as session:
        assert session.get(Folder, root_id) is None
        assert session.scalar(select(func.count()).select_from(Bookmark)) == 0


def test_recursive_folder_delete_decodes_utf8_confirmation_before_exact_comparison(
    auth_client, session_factory
):
    with session_factory() as session:
        folder = Folder(user_id=1, base_name="工具", position=1)
        session.add(folder)
        session.commit()
        folder_id = folder.id

    response = auth_client.delete(
        f"/api/v1/folders/{folder_id}?recursive=true",
        headers={"X-Confirm-Delete": quote("工具", safe="")},
    )

    assert response.status_code == 200
    with session_factory() as session:
        assert session.get(Folder, folder_id) is None


@pytest.mark.parametrize("confirmation", ["%ZZ", "%E5%B7%A5%E5%85"])
def test_recursive_folder_delete_rejects_malformed_encoded_confirmation(
    auth_client, session_factory, confirmation
):
    with session_factory() as session:
        folder = Folder(user_id=1, base_name="工具", position=1)
        session.add(folder)
        session.commit()
        folder_id = folder.id

    response = auth_client.delete(
        f"/api/v1/folders/{folder_id}?recursive=true",
        headers={"X-Confirm-Delete": confirmation},
    )

    assert response.status_code == 400
    with session_factory() as session:
        assert session.get(Folder, folder_id) is not None


def test_recursive_delete_enforces_default_retention(
    auth_client, session_factory, monkeypatch
):
    root_id, _ = _populate(session_factory)
    calls = []
    monkeypatch.setattr(
        "app.routers.folders.enforce_backup_retention",
        lambda session: calls.append(session),
    )
    response = auth_client.delete(
        f"/api/v1/folders/{root_id}?recursive=true",
        headers={"X-Confirm-Delete": "01_Root"},
    )
    assert response.status_code == 200
    assert len(calls) == 1


def test_backup_list_does_not_expose_absolute_paths(auth_client, session_factory):
    with session_factory() as session:
        backup = create_backup(session, "listed")
        session.commit()
    response = auth_client.get("/api/v1/backups")
    assert response.status_code == 200
    item = response.json()[0]
    assert item["id"] == backup.id
    assert item["filename"] == Path(backup.path).name
    assert "path" not in item
    assert item["checksum"] == backup.checksum


def test_prune_keeps_newest_30_plus_one_daily_for_30_days(session_factory, tmp_path):
    now = datetime(2026, 7, 13, 12, tzinfo=UTC)
    with session_factory() as session:
        for index in range(45):
            path = tmp_path / f"snapshot-{index}.sqlite3"
            path.write_bytes(str(index).encode())
            backup = Backup(
                path=str(path), checksum=hashlib.sha256(path.read_bytes()).hexdigest()
            )
            session.add(backup)
            session.flush()
            backup.created_at = (now - timedelta(days=index)).replace(tzinfo=None)
        session.commit()
        result = prune_backups(session, now)
        remaining = list(session.scalars(select(Backup)).all())
    assert result.deleted == 15
    assert result.kept == 30
    assert len(remaining) == 30
    assert all(Path(item.path).exists() for item in remaining)


def test_prune_commit_failure_keeps_rows_and_files(session_factory, tmp_path, monkeypatch):
    now = datetime(2026, 7, 13, 12, tzinfo=UTC)
    with session_factory() as session:
        for index in range(31):
            path = tmp_path / f"commit-failure-{index}.sqlite3"
            path.write_bytes(str(index).encode())
            session.add(
                Backup(path=str(path), checksum=hashlib.sha256(path.read_bytes()).hexdigest())
            )
        session.commit()
        real_commit = session.commit
        monkeypatch.setattr(
            session,
            "commit",
            lambda: (_ for _ in ()).throw(RuntimeError("forced commit failure")),
        )
        with pytest.raises(RuntimeError, match="forced commit failure"):
            prune_backups(session, now, daily_days=0)
        monkeypatch.setattr(session, "commit", real_commit)
        assert session.scalar(select(func.count()).select_from(Backup)) == 31
    assert len(list(tmp_path.glob("commit-failure-*.sqlite3"))) == 31


def test_prune_retries_orphan_cleanup_on_later_run(session_factory, tmp_path, monkeypatch):
    now = datetime(2026, 7, 13, 12, tzinfo=UTC)
    victim = tmp_path / "retry-0.sqlite3"
    with session_factory() as session:
        for index in range(31):
            path = tmp_path / f"retry-{index}.sqlite3"
            path.write_bytes(str(index).encode())
            session.add(
                Backup(path=str(path), checksum=hashlib.sha256(path.read_bytes()).hexdigest())
            )
        session.commit()
        real_unlink = Path.unlink

        def fail_victim_once(path, *args, **kwargs):
            if path == victim:
                raise OSError("forced cleanup failure")
            return real_unlink(path, *args, **kwargs)

        monkeypatch.setattr(Path, "unlink", fail_victim_once)
        first = prune_backups(session, now, daily_days=0)
        assert first.cleanup_failed == 1
        assert victim.exists()
        monkeypatch.setattr(Path, "unlink", real_unlink)
        second = prune_backups(session, now, daily_days=0)
        assert second.cleanup_failed == 0
        assert not victim.exists()


def test_backup_finalization_failure_removes_published_snapshot(
    session_factory, tmp_path, monkeypatch
):
    real_open = os.open

    def fail_directory_open(path, flags):
        if Path(path) == tmp_path / "backups":
            raise OSError("directory fsync failed")
        return real_open(path, flags)

    monkeypatch.setattr(os, "open", fail_directory_open)
    with session_factory() as session:
        with pytest.raises(OSError, match="directory fsync failed"):
            create_backup(session, "publish-failure")
    assert list((tmp_path / "backups").glob("*.sqlite3")) == []


def test_import_export_preserves_netscape_bookmark_and_folder_attrs(
    auth_client, session_factory, tmp_path, monkeypatch
):
    policy = tmp_path / "attrs-policy.json"
    policy.write_text(
        '{"top_level_order": [], "classification": '
        '{"fallback_path_map": {"Imported": ["Imported"]}}}',
        encoding="utf-8",
    )
    monkeypatch.setenv("NAV_BOOKMARK_POLICY_PATH", str(policy))
    content = b"""<!DOCTYPE NETSCAPE-Bookmark-file-1>
<DL><p><DT><H3 PERSONAL_TOOLBAR_FOLDER="true" LAST_MODIFIED="100">Toolbar</H3><DL><p>
<DT><H3 ADD_DATE="101" LAST_MODIFIED="102">Imported</H3><DL><p>
<DT><A HREF="https://attrs.test" ADD_DATE="103" LAST_MODIFIED="104" ICON="data:image/png;base64,AA==">Attrs</A>
</DL><p></DL><p></DL><p>"""
    preview = auth_client.post(
        "/api/v1/imports/preview",
        files={"file": ("attrs.html", content, "text/html")},
    )
    assert preview.status_code == 200
    assert auth_client.post(
        f"/api/v1/imports/{preview.json()['id']}/apply", json={"overrides": []}
    ).status_code == 200

    exported = parse_html(auth_client.get("/api/v1/exports/bookmarks.html").text)
    record = exported.bookmarks()[0]
    assert record.attrs["add_date"] == "103"
    assert record.attrs["last_modified"] == "104"
    assert record.attrs["icon"] == "data:image/png;base64,AA=="
    assert exported.root.attrs["personal_toolbar_folder"] == "true"
    assert exported.root.attrs["last_modified"] == "100"
    folder = next(child for child in exported.root.children if isinstance(child, FolderNode))
    assert folder.attrs["add_date"] == "101"
    assert folder.attrs["last_modified"] == "102"

    with session_factory() as session:
        stored_folder = session.scalar(select(Folder))
        stored_bookmark = session.scalar(select(Bookmark))
        assert stored_folder.attrs["last_modified"] == "102"
        assert stored_folder.toolbar_attrs["last_modified"] == "100"
        assert stored_bookmark.attrs["icon"] == "data:image/png;base64,AA=="


def test_nested_folder_prefix_is_regenerated_after_reorder(auth_client, session_factory):
    with session_factory() as session:
        session.add(Folder(user_id=1, base_name="01_常用", position=1))
        root = Folder(user_id=1, base_name="02_AI 与智能开发", position=2)
        session.add(root)
        session.flush()
        stale = Folder(user_id=1, parent_id=root.id, base_name="02_Stale", position=1)
        session.add(stale)
        session.flush()
        session.add(
            Bookmark(
                user_id=1,
                folder_id=stale.id,
                title="Reordered",
                url="https://reordered.test",
                normalized_url="https://reordered.test",
                position=1,
            )
        )
        session.commit()
    record = parse_html(auth_client.get("/api/v1/exports/bookmarks.html").text).bookmarks()[0]
    assert record.path == ("02_AI 与智能开发", "01_Stale")


@pytest.mark.skipif(
    PRIVATE_FIXTURE_PATH is None or not PRIVATE_FIXTURE_PATH.is_file(),
    reason="set NAV_PRIVATE_BOOKMARK_FIXTURE to a private Netscape HTML fixture",
)
def test_private_fixture_html_export_round_trip_preserves_unique_urls_and_folders(
    auth_client, session_factory
):
    content = PRIVATE_FIXTURE_PATH.read_bytes()
    preview = auth_client.post(
        "/api/v1/imports/preview",
        files={"file": ("private-fixture.html", content, "text/html")},
    )
    assert preview.status_code == 200
    applied = auth_client.post(
        f"/api/v1/imports/{preview.json()['id']}/apply", json={"overrides": []}
    )
    assert applied.status_code == 200

    exported = auth_client.get("/api/v1/exports/bookmarks.html")
    assert exported.status_code == 200
    exported_tree = parse_html(exported.text)
    records = exported_tree.bookmarks()
    normalized = [normalize_url(record.url) for record in records]
    baseline_tree = parse_html(content.decode("utf-8-sig"))
    baseline_records = baseline_tree.bookmarks()
    assert len(records) == len(baseline_records)
    assert len(normalized) == len(set(normalized))
    assert set(normalized) == {
        normalize_url(record.url) for record in baseline_records
    }
    assert {record.path for record in records} == {
        record.path for record in baseline_records
    }
    baseline_by_url = {normalize_url(record.url): record for record in baseline_records}
    exported_by_url = {normalize_url(record.url): record for record in records}
    for url, baseline_record in baseline_by_url.items():
        assert exported_by_url[url].attrs == baseline_record.attrs
    baseline_folders = _folder_attrs(baseline_tree)
    exported_folders = _folder_attrs(exported_tree)
    attr_path = next(
        path
        for path, attrs in baseline_folders.items()
        if attrs and path in exported_folders
    )
    assert exported_folders[attr_path] == baseline_folders[attr_path]
    assert exported_tree.root.attrs == baseline_tree.root.attrs
    with session_factory() as session:
        parent_ids = [None, *session.scalars(select(Folder.id)).all()]
        for parent_id in parent_ids:
            clause = (
                Folder.parent_id.is_(None)
                if parent_id is None
                else Folder.parent_id == parent_id
            )
            positions = list(
                session.scalars(select(Folder.position).where(clause).order_by(Folder.position))
            )
            assert positions == list(range(1, len(positions) + 1))
