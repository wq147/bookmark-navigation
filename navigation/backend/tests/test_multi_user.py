import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.db import configure_sqlite, get_session
from app.main import app
from app.models import Base, SessionToken, User
from app.security import hash_password


@pytest.fixture
def session_factory(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'multi-user.db'}")
    configure_sqlite(engine)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    yield factory
    engine.dispose()


@pytest.fixture
def client(session_factory, monkeypatch):
    monkeypatch.setenv("NAV_TEST_MODE", "1")
    monkeypatch.setenv(
        "NAV_BACKUP_DIR", str(session_factory.kw["bind"].url.database) + "-backups"
    )

    def override_session():
        with session_factory() as session:
            yield session

    app.dependency_overrides[get_session] = override_session
    with TestClient(app, client=("127.0.0.1", 50100)) as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.fixture
def admin(client, session_factory):
    with session_factory() as session:
        session.add(
            User(
                username="admin",
                password_hash=hash_password("administrator passphrase"),
                is_admin=True,
                is_active=True,
                must_change_password=False,
            )
        )
        session.commit()
    response = client.post(
        "/api/v1/auth/login",
        json={"username": "admin", "password": "administrator passphrase"},
    )
    assert response.status_code == 200
    client.headers["X-CSRF-Token"] = response.json()["csrf_token"]
    return client


def test_admin_creates_user_and_temporary_password_requires_change(admin):
    created = admin.post(
        "/api/v1/admin/users",
        json={"username": "reader", "temporary_password": "temporary passphrase"},
    )
    assert created.status_code == 201
    assert created.json() == {
        "id": created.json()["id"],
        "username": "reader",
        "is_admin": False,
        "is_active": True,
        "must_change_password": True,
        "created_at": created.json()["created_at"],
        "updated_at": created.json()["updated_at"],
    }

    reader = TestClient(app, client=("127.0.0.1", 50101))
    login = reader.post(
        "/api/v1/auth/login",
        json={"username": "reader", "password": "temporary passphrase"},
    )
    reader.headers["X-CSRF-Token"] = login.json()["csrf_token"]
    assert reader.get("/api/v1/folders").json()["detail"]["code"] == "PASSWORD_CHANGE_REQUIRED"

    changed = reader.post(
        "/api/v1/auth/change-password",
        json={
            "current_password": "temporary passphrase",
            "new_password": "reader permanent passphrase",
        },
    )
    assert changed.status_code == 204
    assert reader.get("/api/v1/folders").status_code == 200


def test_users_cannot_read_or_mutate_each_others_folders(admin):
    created = admin.post(
        "/api/v1/folders", json={"base_name": "Administrator private"}
    )
    assert created.status_code == 201
    admin_folder_id = created.json()["id"]
    admin_bookmark_id = admin.post(
        "/api/v1/bookmarks",
        json={
            "title": "Administrator secret",
            "url": "https://administrator-secret.test",
            "folder_id": admin_folder_id,
        },
    ).json()["id"]
    preview = admin.post(
        "/api/v1/imports/preview",
        files={
            "file": (
                "admin.html",
                b'<!DOCTYPE NETSCAPE-Bookmark-file-1><DL><p><DT><A HREF="https://preview.test">Preview</A></DL><p>',
                "text/html",
            )
        },
    ).json()
    admin.post(
        "/api/v1/admin/users",
        json={"username": "reader", "temporary_password": "temporary passphrase"},
    )

    reader = TestClient(app, client=("127.0.0.1", 50102))
    login = reader.post(
        "/api/v1/auth/login",
        json={"username": "reader", "password": "temporary passphrase"},
    )
    reader.headers["X-CSRF-Token"] = login.json()["csrf_token"]
    reader.post(
        "/api/v1/auth/change-password",
        json={
            "current_password": "temporary passphrase",
            "new_password": "reader permanent passphrase",
        },
    )

    assert reader.get("/api/v1/folders").json() == []
    assert reader.get(f"/api/v1/folders/{admin_folder_id}").status_code == 404
    assert reader.patch(
        f"/api/v1/folders/{admin_folder_id}", json={"base_name": "stolen"}
    ).status_code == 404
    assert reader.get(f"/api/v1/bookmarks/{admin_bookmark_id}").status_code == 404
    assert reader.get(f"/api/v1/bookmarks?folder_id={admin_folder_id}").status_code == 404
    assert reader.get(f"/api/v1/search?q=secret&folder_id={admin_folder_id}").status_code == 404
    assert reader.get(f"/api/v1/imports/{preview['id']}").status_code == 404
    assert reader.post(
        f"/api/v1/imports/{preview['id']}/apply", json={"overrides": []}
    ).status_code == 404


def test_reset_and_disable_revoke_target_sessions(admin, session_factory):
    created = admin.post(
        "/api/v1/admin/users",
        json={"username": "reader", "temporary_password": "temporary passphrase"},
    ).json()
    reader = TestClient(app, client=("127.0.0.1", 50103))
    reader.post(
        "/api/v1/auth/login",
        json={"username": "reader", "password": "temporary passphrase"},
    )

    reset = admin.post(
        f"/api/v1/admin/users/{created['id']}/reset-password",
        json={"temporary_password": "replacement passphrase"},
    )
    assert reset.status_code == 204
    assert reader.get("/api/v1/auth/me").status_code == 401

    login = reader.post(
        "/api/v1/auth/login",
        json={"username": "reader", "password": "replacement passphrase"},
    )
    assert login.status_code == 200
    disabled = admin.patch(
        f"/api/v1/admin/users/{created['id']}/status", json={"is_active": False}
    )
    assert disabled.status_code == 200
    assert reader.get("/api/v1/auth/me").status_code == 401
    with session_factory() as session:
        assert session.scalars(
            select(SessionToken).where(SessionToken.user_id == created["id"])
        ).all() == []


def test_user_scoped_uniqueness_and_system_backups_are_admin_only(admin):
    admin_folder = admin.post(
        "/api/v1/folders", json={"base_name": "Shared name"}
    ).json()
    assert admin.post(
        "/api/v1/bookmarks",
        json={
            "title": "Admin",
            "url": "https://same.test",
            "folder_id": admin_folder["id"],
        },
    ).status_code == 201
    admin.post(
        "/api/v1/admin/users",
        json={"username": "reader", "temporary_password": "temporary passphrase"},
    )
    reader = TestClient(app, client=("127.0.0.1", 50104))
    login = reader.post(
        "/api/v1/auth/login",
        json={"username": "reader", "password": "temporary passphrase"},
    )
    reader.headers["X-CSRF-Token"] = login.json()["csrf_token"]
    reader.post(
        "/api/v1/auth/change-password",
        json={
            "current_password": "temporary passphrase",
            "new_password": "reader permanent passphrase",
        },
    )
    reader_folder = reader.post(
        "/api/v1/folders", json={"base_name": "Shared name"}
    ).json()
    assert reader.post(
        "/api/v1/bookmarks",
        json={
            "title": "Reader",
            "url": "https://same.test",
            "folder_id": reader_folder["id"],
        },
    ).status_code == 201
    assert [item["title"] for item in reader.get("/api/v1/search?q=same").json()["items"]] == [
        "Reader"
    ]
    assert reader.get("/api/v1/backups").status_code == 403


def test_delete_user_requires_confirmation_creates_backup_and_keeps_audit(
    admin, session_factory
):
    created = admin.post(
        "/api/v1/admin/users",
        json={"username": "obsolete", "temporary_password": "temporary passphrase"},
    ).json()
    assert admin.delete(f"/api/v1/admin/users/{created['id']}").status_code == 400
    deleted = admin.delete(
        f"/api/v1/admin/users/{created['id']}",
        headers={"X-Confirm-Username": "obsolete"},
    )
    assert deleted.status_code == 204
    assert any(
        entry["action"] == "user.delete" and entry["target_username"] == "obsolete"
        for entry in admin.get("/api/v1/admin/audit").json()
    )


def test_primary_admin_is_protected_and_audit_is_secret_free(admin):
    me = admin.get("/api/v1/auth/me").json()
    assert admin.patch(
        f"/api/v1/admin/users/{me['id']}/status", json={"is_active": False}
    ).status_code == 409
    assert admin.post(
        f"/api/v1/admin/users/{me['id']}/reset-password",
        json={"temporary_password": "replacement passphrase"},
    ).status_code == 409
    assert admin.delete(
        f"/api/v1/admin/users/{me['id']}",
        headers={"X-Confirm-Username": me["username"]},
    ).status_code == 409

    admin.post(
        "/api/v1/admin/users",
        json={"username": "audited", "temporary_password": "temporary passphrase"},
    )
    serialized = str(admin.get("/api/v1/admin/audit").json()).casefold()
    assert "temporary passphrase" not in serialized
    assert "password_hash" not in serialized
    assert "csrf" not in serialized
    assert "token" not in serialized
