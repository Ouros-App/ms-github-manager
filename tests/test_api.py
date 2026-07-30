from fastapi.testclient import TestClient


def test_health_endpoint(monkeypatch):
    monkeypatch.setenv("GH_TOKEN", "test")
    from app.main import app

    response = TestClient(app).get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_root_endpoint(monkeypatch):
    monkeypatch.setenv("GH_TOKEN", "test")
    from app.main import app

    response = TestClient(app).get("/")

    assert response.status_code == 200
    assert response.json()["message"] == "Ouros GitHub Repository Manager is running"
