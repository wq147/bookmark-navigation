from fastapi.testclient import TestClient

from app.main import app


def test_health_does_not_require_auth_or_leak_data():
    with TestClient(app) as client:
        response = client.get("/healthz")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
