from datetime import UTC, datetime, timedelta
from inspect import signature

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from app.db import get_session
from app.dependencies import require_user
from app.main import app
from app.models import Base, SessionToken, User
from app.security import hash_password


@pytest.fixture
def session_factory(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'auth.db'}")
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
    with TestClient(app, client=("127.0.0.1", 50000)) as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.fixture
def user(session_factory):
    with session_factory() as session:
        user = User(username="yong", password_hash=hash_password("correct horse"))
        session.add(user)
        session.commit()
        return user


def test_bookmark_content_requires_login(client):
    response = client.get("/api/v1/auth/me")
    assert response.status_code == 401


def test_unauthenticated_spa_route_redirects_to_login(client):
    response = client.get("/", follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"] == "/login"


def test_login_sets_httponly_cookie_and_returns_csrf(client, user):
    response = client.post(
        "/api/v1/auth/login",
        json={"username": "yong", "password": "correct horse"},
    )

    assert response.status_code == 200
    assert "HttpOnly" in response.headers["set-cookie"]
    assert "SameSite=strict" in response.headers["set-cookie"]
    assert response.json()["csrf_token"]


def test_login_stores_only_digest_and_argon2_password(client, user, session_factory):
    response = client.post(
        "/api/v1/auth/login",
        json={"username": "yong", "password": "correct horse"},
    )
    raw_token = response.cookies["navigation_session"]

    with session_factory() as session:
        stored_user = session.scalar(select(User).where(User.username == "yong"))
        token = session.scalar(select(SessionToken))
        assert stored_user.password_hash.startswith("$argon2")
        assert "correct horse" not in stored_user.password_hash
        assert token.token_hash != raw_token
        assert raw_token not in token.token_hash


def test_me_returns_authenticated_user(client, user):
    login = client.post(
        "/api/v1/auth/login",
        json={"username": "yong", "password": "correct horse"},
    )

    response = client.get("/api/v1/auth/me")

    assert response.status_code == 200
    assert response.json() == {
        "id": user.id,
        "username": "yong",
        "is_admin": False,
        "is_active": True,
        "must_change_password": False,
        "csrf_token": login.json()["csrf_token"],
    }


def test_fresh_tab_bootstraps_csrf_then_can_mutate_and_logout(client, user):
    login = client.post(
        "/api/v1/auth/login",
        json={"username": "yong", "password": "correct horse"},
    )
    cookie = login.cookies["navigation_session"]

    # A new tab has the cookie but no tab-scoped sessionStorage or in-memory token.
    with TestClient(app, client=("127.0.0.1", 50002)) as fresh_tab:
        fresh_tab.cookies.set("navigation_session", cookie)
        bootstrap = fresh_tab.get("/api/v1/auth/me")
        csrf = bootstrap.json()["csrf_token"]
        created = fresh_tab.post(
            "/api/v1/folders",
            json={"base_name": "Fresh tab"},
            headers={"X-CSRF-Token": csrf},
        )
        assert created.status_code == 201
        assert fresh_tab.post(
            "/api/v1/auth/logout", headers={"X-CSRF-Token": csrf}
        ).status_code == 204


def test_logout_requires_csrf_and_revokes_session(client, user):
    login = client.post(
        "/api/v1/auth/login",
        json={"username": "yong", "password": "correct horse"},
    )
    csrf = login.json()["csrf_token"]

    assert client.post("/api/v1/auth/logout").status_code == 403
    response = client.post("/api/v1/auth/logout", headers={"X-CSRF-Token": csrf})

    assert response.status_code == 204
    assert client.get("/api/v1/auth/me").status_code == 401


def test_expired_session_is_rejected(client, user, session_factory):
    client.post(
        "/api/v1/auth/login",
        json={"username": "yong", "password": "correct horse"},
    )
    with session_factory() as session:
        token = session.scalar(select(SessionToken))
        token.expires_at = datetime.now(UTC).replace(tzinfo=None) - timedelta(seconds=1)
        session.commit()

    assert client.get("/api/v1/auth/me").status_code == 401


def test_repeated_failures_are_rate_limited(client, user):
    for _ in range(5):
        response = client.post(
            "/api/v1/auth/login", json={"username": " YONG ", "password": "wrong"}
        )
        assert response.status_code == 401

    response = client.post(
        "/api/v1/auth/login", json={"username": "yong", "password": "wrong"}
    )
    assert response.status_code == 429


def test_unknown_user_still_runs_password_verification(client, monkeypatch):
    calls = []

    def record_verification(stored_hash, supplied_password):
        calls.append((stored_hash, supplied_password))
        return False

    monkeypatch.setattr(
        "app.routers.auth.verify_password",
        record_verification,
    )

    response = client.post(
        "/api/v1/auth/login",
        json={"username": "missing", "password": "secret"},
    )

    assert response.status_code == 401
    assert calls == [(None, "secret")]


def test_require_user_public_interface_is_request_and_session_only():
    assert list(signature(require_user).parameters) == ["request", "session"]
