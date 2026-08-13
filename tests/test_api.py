from types import SimpleNamespace

from fastapi.testclient import TestClient


def authenticated_client(app):
    app.state.settings.AUTH_USERNAME = "admin"
    app.state.settings.AUTH_PASSWORD = "password"
    app.state.settings.SESSION_SECRET = "test-session-secret"
    app.state.settings.AUTH_COOKIE_SECURE = False
    client = TestClient(app)
    assert client.post("/auth/login", json={"username": "admin", "password": "password"}).status_code == 200
    return client


def test_health_endpoint(monkeypatch):
    monkeypatch.setenv("GH_TOKEN", "test")
    from app.main import app

    response = TestClient(app).get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_metrics_endpoint(monkeypatch):
    monkeypatch.setenv("GH_TOKEN", "test")
    from app.main import app

    app.state.settings.METRICS_TOKEN = "metrics-secret"
    response = TestClient(app).get("/metrics", headers={"Authorization": "Bearer metrics-secret"})

    assert response.status_code == 200
    assert "http_requests_total" in response.text


def test_metrics_endpoint_token(monkeypatch):
    monkeypatch.setenv("GH_TOKEN", "test")
    from app.main import app

    monkeypatch.setattr(app.state.settings, "METRICS_TOKEN", "metrics-secret")
    client = TestClient(app)

    assert client.get("/metrics").status_code == 401
    assert client.get("/metrics", headers={"Authorization": "Bearer metrics-secret"}).status_code == 200


def test_root_endpoint(monkeypatch):
    monkeypatch.setenv("GH_TOKEN", "test")
    from app.main import app

    response = authenticated_client(app).get("/")

    assert response.status_code == 200
    assert response.json()["message"] == "Ouros GitHub Repository Manager is running"


def test_repository_endpoints(monkeypatch):
    monkeypatch.setenv("GH_TOKEN", "test")
    from app.api import routes
    from app.main import app

    class Manager:
        async def list_templates(self):
            return []

        async def start_bare_creation(self, payload):
            return SimpleNamespace(creation_id="bare", status="queued", repository=f"Ouros-App/{payload.name}")

        async def start_template_creation(self, payload):
            return SimpleNamespace(creation_id="template", status="queued", repository=f"Ouros-App/{payload.name}")

        async def get_creation_status(self, creation_id):
            if creation_id == "missing":
                return None
            return SimpleNamespace(
                creation_id=creation_id,
                status="done",
                repository="Ouros-App/orders",
                mode="bare",
                started_at="2026-01-01T00:00:00Z",
                finished_at=None,
                current_step=None,
                steps=[],
                error=None,
                url=None,
            )

    monkeypatch.setattr(routes, "github_manager", Manager())
    client = authenticated_client(app)

    assert client.get("/templates").json() == []
    assert client.post("/repositories/bare", json={"name": "orders"}).status_code == 202
    assert client.post(
        "/repositories/from-template",
        json={"name": "orders", "template_name": "api-template"},
    ).status_code == 202
    assert client.get("/repositories/creations/bare").status_code == 200
    assert client.get("/repositories/creations/missing").status_code == 404
    assert client.get("/app", follow_redirects=False).status_code == 307
    assert client.get("/ui").status_code == 200


def test_validation_error_hides_postgres_password(monkeypatch):
    monkeypatch.setenv("GH_TOKEN", "test")
    from app.main import app

    response = authenticated_client(app).post(
        "/repositories/from-template",
        json={
            "name": "orders-database",
            "template_name": "postgres-template",
            "postgres": {
                "host": "db.example.test",
                "database": "orders",
                "user": "orders",
                "password": "private-password",
                "root_user": "postgres",
                "root_password": "",
            },
        },
    )

    assert response.status_code == 422
    assert "private-password" not in response.text
    assert "root_password" in response.text
    assert '"input"' not in response.text


def test_validation_error_with_context_returns_422(monkeypatch):
    monkeypatch.setenv("GH_TOKEN", "test")
    from app.main import app

    response = authenticated_client(app).post(
        "/repositories/from-template",
        json={
            "name": "orders",
            "template_name": "postgres-template",
            "postgres": {
                "host": "db.example.test",
                "database": "orders",
                "user": "orders",
                "password": "private-password",
                "root_user": "postgres",
                "root_password": "root-password",
            },
        },
    )

    assert response.status_code == 422
    assert '"input"' not in response.text
