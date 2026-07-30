import asyncio
from types import SimpleNamespace

import pytest

from app.schemas.github import (
    BareRepositoryCreateRequest,
    TemplateRepositoryCreateRequest,
)


@pytest.fixture
def manager(monkeypatch):
    monkeypatch.setenv("GH_TOKEN", "test")
    from app.services.github_manager import GitHubRepositoryManager

    return GitHubRepositoryManager()


def _capture_files(manager, method, repository_name):
    files = {}
    manager._put_file_sync = lambda _, path, content, __: files.setdefault(path, content)
    method(repository_name)
    return files


def test_generates_springboot_scaffold(manager):
    files = _capture_files(manager, manager._put_springboot_scaffold_sync, "ms-orders-template")

    assert "README.md" in files
    assert "src/main/resources/application.properties" in files
    assert "OrdersApplication.java" in "\n".join(files)


def test_generates_android_scaffold(manager):
    files = _capture_files(manager, manager._put_android_scaffold_sync, "my-app-template")

    assert "app/src/main/AndroidManifest.xml" in files
    assert "applicationId = \"com.ourosapp.myapp\"" in files["app/build.gradle.kts"]


def test_generates_postgres_scaffold(manager):
    files = _capture_files(manager, manager._put_postgres_scaffold_sync, "orders-database")

    assert {"README.md", "config.yaml", "sql/versionamento.sql"} <= files.keys()


@pytest.mark.parametrize(
    ("repository_name", "application_name", "package_name", "class_name"),
    [
        ("ms-orders-template", "orders", "com.ourosapp.orders", "OrdersApplication"),
        ("123-api", "123-api", "com.ourosapp.app123api", "App123ApiApplication"),
    ],
)
def test_springboot_names(manager, repository_name, application_name, package_name, class_name):
    assert manager._springboot_application_name(repository_name) == application_name
    assert manager._springboot_package_name(repository_name) == package_name
    assert manager._springboot_application_class_name(repository_name) == class_name


def test_android_names_and_placeholders(manager):
    assert manager._android_namespace("my-app-template") == "com.ourosapp.myapp"
    assert manager._android_app_name("my-app-TEMPLATE") == "my app"
    assert manager._android_application_class_name("my-app") == "MyAppApplication"
    assert manager._replace_placeholders("{{PROJECT_NAME}}/{{APP_LABEL}}", {"{{PROJECT_NAME}}": "app", "{{APP_LABEL}}": "App"}) == "app/App"


def test_workflow_and_gitignore_helpers(manager):
    assert "pytest" in manager._workflow("fastapi")
    assert manager._workflow("unknown") == manager._workflow("generic")
    assert manager._gitignore_template("fastapi") == "Python"
    assert manager._gitignore_template("unknown") is None


@pytest.mark.parametrize("language", ["generic", "springboot", "android", "postgres"])
def test_bare_creation_flow(manager, language):
    async def run():
        state = await manager._create_state("orders-database" if language == "postgres" else "orders", "bare")
        manager._create_bare_repository_sync = lambda _: SimpleNamespace(name="orders", html_url="https://example.test/orders")
        manager._wait_until_repository_ready_sync = lambda _: None
        manager._put_springboot_scaffold_sync = lambda _: None
        manager._put_sonar_properties_sync = lambda _: None
        manager._put_android_scaffold_sync = lambda _: None
        manager._put_postgres_scaffold_sync = lambda _: None
        manager._put_file_sync = lambda *_: None
        manager._put_workflow_sync = lambda *_: None
        manager._protect_main_branch_sync = lambda _: None
        manager._create_sonarcloud_project_sync = lambda _: None

        await manager._create_bare_repository(
            state.creation_id,
            BareRepositoryCreateRequest(name=state.repository.rsplit("/", 1)[1], language=language),
        )

        assert (await manager.get_creation_status(state.creation_id)).status == "done"

    asyncio.run(run())


@pytest.mark.parametrize("template_name", ["ms-generic-template", "ms-spring-template", "ms-android-template", "ms-postgres-template"])
def test_template_creation_flow(manager, template_name):
    async def exists(_: str):
        return None

    async def run():
        state = await manager._create_state("orders-database" if "postgres" in template_name else "orders", "template")
        manager._assert_template_exists = exists
        manager._create_from_template_sync = lambda _: SimpleNamespace(name="orders", html_url="https://example.test/orders")
        manager._wait_until_repository_ready_sync = lambda _: None
        manager._wait_until_paths_exist_sync = lambda *_: None
        manager._clear_springboot_template_structure_sync = lambda _: None
        manager._wait_until_paths_absent_sync = lambda *_: None
        manager._put_springboot_scaffold_sync = lambda _: None
        manager._put_sonar_properties_sync = lambda _: None
        manager._initialize_android_template_sync = lambda _: None
        manager._put_postgres_scaffold_sync = lambda _: None
        manager._put_workflow_sync = lambda *_: None
        manager._protect_main_branch_sync = lambda _: None
        manager._create_sonarcloud_project_sync = lambda _: None

        await manager._create_repository_from_template(
            state.creation_id,
            TemplateRepositoryCreateRequest(name=state.repository.rsplit("/", 1)[1], template_name=template_name),
        )

        assert (await manager.get_creation_status(state.creation_id)).status == "done"

    asyncio.run(run())
