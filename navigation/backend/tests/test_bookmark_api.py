from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.db import configure_sqlite, get_session
from app.main import app
from app.models import Base, Bookmark, Folder, Operation, User
from app.security import hash_password


@pytest.fixture
def session_factory(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'bookmarks.db'}")
    configure_sqlite(engine)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    yield factory
    engine.dispose()


@pytest.fixture
def client(session_factory, monkeypatch):
    monkeypatch.setenv("NAV_TEST_MODE", "1")

    def override_session():
        with session_factory() as session:
            yield session

    app.dependency_overrides[get_session] = override_session
    with TestClient(app, client=("127.0.0.1", 50001)) as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.fixture
def auth_client(client, session_factory):
    with session_factory() as session:
        session.add(User(username="bookmark-user", password_hash=hash_password("secret")))
        session.commit()
    response = client.post(
        "/api/v1/auth/login",
        json={"username": "bookmark-user", "password": "secret"},
    )
    client.headers["X-CSRF-Token"] = response.json()["csrf_token"]
    return client


@pytest.fixture
def folder(auth_client):
    response = auth_client.post("/api/v1/folders", json={"base_name": "网络工具"})
    assert response.status_code == 201
    return SimpleNamespace(**response.json())


@pytest.fixture
def tree(auth_client):
    root = auth_client.post("/api/v1/folders", json={"base_name": "Root"})
    assert root.status_code == 201
    child = auth_client.post(
        "/api/v1/folders",
        json={"base_name": "Child", "parent_id": root.json()["id"]},
    )
    assert child.status_code == 201
    return SimpleNamespace(root_id=root.json()["id"], child_id=child.json()["id"])


def test_management_routes_require_login(client):
    assert client.get("/api/v1/folders").status_code == 401
    assert client.get("/api/v1/bookmarks").status_code == 401
    assert client.get("/api/v1/search", params={"q": "x"}).status_code == 401


def test_folder_crud_renumbers_siblings_and_records_operations(auth_client, session_factory):
    first = auth_client.post("/api/v1/folders", json={"base_name": "First"})
    second = auth_client.post("/api/v1/folders", json={"base_name": "Second"})
    assert first.status_code == 201
    assert second.status_code == 201

    renamed = auth_client.patch(
        f"/api/v1/folders/{second.json()['id']}",
        json={"base_name": "Renamed"},
    )
    assert renamed.status_code == 200
    assert renamed.json()["base_name"] == "Renamed"
    assert auth_client.get(f"/api/v1/folders/{first.json()['id']}").status_code == 200

    assert auth_client.delete(f"/api/v1/folders/{first.json()['id']}").status_code == 204
    folders = auth_client.get("/api/v1/folders").json()
    assert [(item["base_name"], item["position"]) for item in folders] == [("Renamed", 1)]

    with session_factory() as session:
        operation_types = session.scalars(select(Operation.operation_type)).all()
    assert operation_types == [
        "folder.create",
        "folder.create",
        "folder.update",
        "folder.delete",
    ]


def test_folder_list_includes_direct_bookmark_count(auth_client, session_factory):
    folder = auth_client.post("/api/v1/folders", json={"base_name": "Counted"}).json()
    with session_factory() as session:
        session.add_all([
            Bookmark(user_id=1, folder_id=folder["id"], title="A", url="https://a.test", normalized_url="https://a.test"),
            Bookmark(user_id=1, folder_id=folder["id"], title="B", url="https://b.test", normalized_url="https://b.test"),
        ])
        session.commit()

    item = next(item for item in auth_client.get("/api/v1/folders").json() if item["id"] == folder["id"])
    assert item["bookmark_count"] == 2
    assert auth_client.get(f"/api/v1/folders/{folder['id']}").json()["bookmark_count"] == 2


def test_folder_write_requires_csrf(auth_client):
    del auth_client.headers["X-CSRF-Token"]
    assert auth_client.post("/api/v1/folders", json={"base_name": "Blocked"}).status_code == 403


def test_moving_folder_below_descendant_is_rejected(auth_client, tree):
    response = auth_client.patch(
        f"/api/v1/folders/{tree.root_id}", json={"parent_id": tree.child_id}
    )
    assert response.status_code == 409


def test_moving_folder_to_itself_is_rejected(auth_client, folder):
    response = auth_client.patch(
        f"/api/v1/folders/{folder.id}", json={"parent_id": folder.id}
    )
    assert response.status_code == 409


def test_only_empty_folder_can_be_deleted(auth_client, tree):
    response = auth_client.delete(f"/api/v1/folders/{tree.root_id}")
    assert response.status_code == 409
    assert auth_client.get(f"/api/v1/folders/{tree.root_id}").status_code == 200


def test_duplicate_sibling_folder_name_is_rejected(auth_client):
    assert auth_client.post("/api/v1/folders", json={"base_name": "Same"}).status_code == 201
    response = auth_client.post("/api/v1/folders", json={"base_name": "Same"})
    assert response.status_code == 409


def test_bookmark_crud_normalizes_url_and_soft_deletes(auth_client, folder, session_factory):
    created = auth_client.post(
        "/api/v1/bookmarks",
        json={
            "title": "Capture",
            "url": "https://EXAMPLE.com/docs/?utm_source=test",
            "folder_id": folder.id,
            "notes": "抓包说明",
        },
    )
    assert created.status_code == 201
    bookmark_id = created.json()["id"]
    assert created.json()["normalized_url"] == "https://example.com/docs"
    assert auth_client.get(f"/api/v1/bookmarks/{bookmark_id}").status_code == 200

    updated = auth_client.patch(
        f"/api/v1/bookmarks/{bookmark_id}",
        json={"title": "Packet capture", "url": "https://example.com/new/"},
    )
    assert updated.status_code == 200
    assert updated.json()["title"] == "Packet capture"
    assert updated.json()["normalized_url"] == "https://example.com/new"

    assert auth_client.delete(f"/api/v1/bookmarks/{bookmark_id}").status_code == 204
    assert auth_client.get(f"/api/v1/bookmarks/{bookmark_id}").status_code == 404
    with session_factory() as session:
        stored = session.get(Bookmark, bookmark_id)
        assert stored.deleted_at is not None
        bookmark_operations = session.scalars(
            select(Operation.operation_type).where(
                Operation.operation_type.like("bookmark.%")
            )
        ).all()
        assert bookmark_operations == [
            "bookmark.create",
            "bookmark.update",
            "bookmark.delete",
        ]


def test_bookmark_write_requires_csrf(auth_client, folder):
    del auth_client.headers["X-CSRF-Token"]
    response = auth_client.post(
        "/api/v1/bookmarks",
        json={"title": "Blocked", "url": "https://blocked.test", "folder_id": folder.id},
    )
    assert response.status_code == 403


def test_duplicate_url_returns_existing_bookmark(auth_client, folder):
    first = auth_client.post(
        "/api/v1/bookmarks",
        json={
            "title": "A",
            "url": "https://x.test/?utm_source=a",
            "folder_id": folder.id,
        },
    )
    assert first.status_code == 201
    response = auth_client.post(
        "/api/v1/bookmarks",
        json={"title": "B", "url": "https://x.test", "folder_id": folder.id},
    )
    assert response.status_code == 409
    assert response.json()["existing_id"] == first.json()["id"]


def test_database_duplicate_race_returns_existing_bookmark(
    auth_client, folder, monkeypatch
):
    first = auth_client.post(
        "/api/v1/bookmarks",
        json={"title": "A", "url": "https://race.test", "folder_id": folder.id},
    )
    monkeypatch.setattr("app.bookmark_service._duplicate_bookmark", lambda *args, **kwargs: None)

    response = auth_client.post(
        "/api/v1/bookmarks",
        json={"title": "B", "url": "https://race.test", "folder_id": folder.id},
    )

    assert response.status_code == 409
    assert response.json()["existing_id"] == first.json()["id"]


def test_database_folder_name_race_returns_conflict(auth_client, monkeypatch):
    assert auth_client.post("/api/v1/folders", json={"base_name": "Race"}).status_code == 201
    monkeypatch.setattr("app.bookmark_service._check_folder_name", lambda *args, **kwargs: None)

    response = auth_client.post("/api/v1/folders", json={"base_name": "Race"})

    assert response.status_code == 409


def test_bookmark_cannot_reference_missing_folder(auth_client):
    response = auth_client.post(
        "/api/v1/bookmarks",
        json={"title": "A", "url": "https://x.test", "folder_id": 9999},
    )
    assert response.status_code == 404
    assert response.json()["detail"] == "Folder not found"


def test_moving_bookmark_appends_after_destination_contents(auth_client, folder):
    destination = auth_client.post(
        "/api/v1/folders", json={"base_name": "Destination"}
    ).json()
    existing = auth_client.post(
        "/api/v1/bookmarks",
        json={
            "title": "Existing",
            "url": "https://existing.test",
            "folder_id": destination["id"],
        },
    )
    auth_client.post(
        "/api/v1/bookmarks",
        json={"title": "Before", "url": "https://before.test", "folder_id": folder.id},
    )
    moving = auth_client.post(
        "/api/v1/bookmarks",
        json={"title": "Moving", "url": "https://moving.test", "folder_id": folder.id},
    )
    assert existing.json()["position"] == 1
    assert moving.json()["position"] == 2

    response = auth_client.patch(
        f"/api/v1/bookmarks/{moving.json()['id']}",
        json={"folder_id": destination["id"]},
    )

    assert response.status_code == 200
    assert response.json()["position"] == 2


@pytest.mark.parametrize("field", ["title", "url", "folder_id", "position"])
def test_bookmark_patch_rejects_null_required_fields(auth_client, folder, field):
    bookmark = auth_client.post(
        "/api/v1/bookmarks",
        json={"title": "Valid", "url": "https://valid.test", "folder_id": folder.id},
    ).json()

    response = auth_client.patch(
        f"/api/v1/bookmarks/{bookmark['id']}", json={field: None}
    )

    assert response.status_code == 422


@pytest.mark.parametrize("field", ["base_name", "position"])
def test_folder_patch_rejects_null_required_fields(auth_client, folder, field):
    response = auth_client.patch(f"/api/v1/folders/{folder.id}", json={field: None})
    assert response.status_code == 422


@pytest.mark.parametrize(
    "payload",
    [
        {"title": " ", "url": "https://valid.test"},
        {"title": "Valid", "url": "   "},
    ],
)
def test_bookmark_create_rejects_whitespace_only_values(auth_client, folder, payload):
    response = auth_client.post(
        "/api/v1/bookmarks", json={**payload, "folder_id": folder.id}
    )
    assert response.status_code == 422


@pytest.mark.parametrize(
    ("query", "expected_title"),
    [
        ("抓包", "Notes match"),
        ("example.net", "URL match"),
        ("网络工具", "Folder match"),
        ("special_title", "special_title"),
    ],
)
def test_search_matches_title_url_folder_and_notes(auth_client, folder, query, expected_title):
    bookmarks = [
        ("Notes match", "https://notes.test", "抓包说明"),
        ("URL match", "https://example.net/docs", ""),
        ("Folder match", "https://folder.test", ""),
        ("special_title", "https://title.test", ""),
    ]
    for title, url, notes in bookmarks:
        response = auth_client.post(
            "/api/v1/bookmarks",
            json={"title": title, "url": url, "folder_id": folder.id, "notes": notes},
        )
        assert response.status_code == 201

    response = auth_client.get("/api/v1/search", params={"q": query})
    assert response.status_code == 200
    assert response.json()["total"] >= 1
    assert expected_title in [item["title"] for item in response.json()["items"]]


def test_search_escapes_like_wildcards_and_paginates(auth_client, folder):
    for title in ["literal_underscore", "literalXunderscore", "100% guide"]:
        response = auth_client.post(
            "/api/v1/bookmarks",
            json={
                "title": title,
                "url": f"https://{title.replace('%', 'percent').replace('_', '-')}.test",
                "folder_id": folder.id,
            },
        )
        assert response.status_code == 201

    literal = auth_client.get("/api/v1/search", params={"q": "_"}).json()
    assert literal["total"] == 1
    percent = auth_client.get("/api/v1/search", params={"q": "%"}).json()
    assert percent["total"] == 1
    page = auth_client.get(
        "/api/v1/search", params={"q": "literal", "limit": 1, "offset": 1}
    ).json()
    assert page["total"] == 2
    assert len(page["items"]) == 1


def test_search_can_filter_by_folder(auth_client, folder):
    other = auth_client.post("/api/v1/folders", json={"base_name": "Other"}).json()
    for folder_id in [folder.id, other["id"]]:
        assert auth_client.post(
            "/api/v1/bookmarks",
            json={"title": "Shared", "url": f"https://{folder_id}.test", "folder_id": folder_id},
        ).status_code == 201

    response = auth_client.get(
        "/api/v1/search", params={"q": "Shared", "folder_id": folder.id}
    )
    assert response.json()["total"] == 1
    assert response.json()["items"][0]["folder_id"] == folder.id
