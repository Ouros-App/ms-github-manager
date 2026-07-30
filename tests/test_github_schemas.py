import pytest
from pydantic import ValidationError

from app.schemas.github import (
    BareRepositoryCreateRequest,
    TemplateRepositoryCreateRequest,
)


def test_postgres_repository_requires_database_suffix():
    with pytest.raises(ValidationError, match="terminar com '-database'"):
        BareRepositoryCreateRequest(name="orders", language="postgres")


def test_postgres_repository_accepts_database_suffix():
    request = BareRepositoryCreateRequest(name="orders-database", language="postgres")
    assert request.name == "orders-database"


def test_postgres_template_requires_database_suffix():
    with pytest.raises(ValidationError, match="terminar com '-database'"):
        TemplateRepositoryCreateRequest(name="orders", template_name="ms-postgres-template")


def test_non_postgres_template_allows_regular_name():
    request = TemplateRepositoryCreateRequest(name="orders", template_name="ms-fastapi-template")
    assert request.name == "orders"


@pytest.mark.parametrize(
    ("template_name", "expected"),
    [
        ("ms-react-template", "frontend"),
        ("ms-spring-template", "springboot"),
        ("ms-android-template", "android"),
        ("ms-fastapi-template", "fastapi"),
        ("ms-postgres-template", "postgres"),
        ("ms-generic-template", "generic"),
    ],
)
def test_template_language(monkeypatch, template_name, expected):
    monkeypatch.setenv("GH_TOKEN", "test")
    from app.services.github_manager import GitHubRepositoryManager

    assert GitHubRepositoryManager()._template_language(template_name) == expected


def test_springboot_scaffold_uses_shared_readme_path(monkeypatch):
    monkeypatch.setenv("GH_TOKEN", "test")
    from app.services.github_manager import GitHubRepositoryManager

    files = {}
    manager = GitHubRepositoryManager()
    manager._put_file_sync = lambda _, path, content, __: files.setdefault(path, content)
    manager._put_springboot_scaffold_sync("ms-orders")

    assert "README.md" in files
    assert files["src/main/resources/application.properties"] == files[
        "src/main/resources/application-local.properties"
    ]


def test_android_scaffold_normalizes_uppercase_template_suffix(monkeypatch):
    monkeypatch.setenv("GH_TOKEN", "test")
    from app.services.github_manager import GitHubRepositoryManager

    files = {}
    manager = GitHubRepositoryManager()
    manager._put_file_sync = lambda _, path, content, __: files.setdefault(path, content)
    manager._put_android_scaffold_sync("My-App-TEMPLATE")

    assert manager._android_app_name("My-App-TEMPLATE") == "My App"
    assert "app/src/main/AndroidManifest.xml" in files
