import asyncio
from types import SimpleNamespace

import pytest

from app.schemas.github import (
    BareRepositoryCreateRequest,
    MongoConnection,
    PostgresConnection,
    TemplateRepositoryCreateRequest,
    TemplateResponse,
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
    assert "execution_order: []" in files["config.yaml"]
    assert "pg_advisory_xact_lock(84729341)" in files["scripts/apply_sql.py"]
    assert "controle_scripts_sql" in files["scripts/apply_sql.py"]
    assert "return expand(yaml.safe_load(raw))" in files["scripts/apply_sql.py"]
    assert "path.relative_to(root / cfg[\"database\"][\"sql_path\"]).as_posix()" in files["scripts/apply_sql.py"]


def test_generated_postgres_runner_handles_secret_values_and_nested_sql(manager, monkeypatch, tmp_path):
    runner = manager._postgres_apply_sql_py().replace("import psycopg2", "psycopg2 = None")
    scope = {}
    exec(runner, scope)  # noqa: S102
    (tmp_path / "config.yaml").write_text("database:\n  host: ${POSTGRES_HOST}\n")
    monkeypatch.setenv("POSTGRES_HOST", "db: secure\nvalue")
    assert scope["load_config"](tmp_path)["database"]["host"] == "db: secure\nvalue"

    for path in (tmp_path / "sql/schema/init.sql", tmp_path / "sql/data/init.sql"):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("SELECT 1;")
    cfg = {"database": {"sql_path": "sql", "execution_order": [
        {"file": "schema/init.sql", "mode": "on_change"},
        {"file": "data/init.sql", "mode": "on_change"},
    ]}}

    class Cursor:
        def __init__(self):
            self.calls = []

        def execute(self, *args):
            self.calls.append(args)

        def fetchone(self):
            return None

    cursor = Cursor()
    scope["apply_sql_files"](tmp_path, cfg, cursor, "commit")
    assert [call[1][0] for call in cursor.calls if "WHERE arquivo" in call[0]] == ["schema/init.sql", "data/init.sql"]


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
        manager._configure_postgres_secrets_sync = lambda *_: None
        manager._put_file_sync = lambda *_: None
        manager._put_workflow_sync = lambda *_: None
        manager._protect_main_branch_sync = lambda *_: None
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
        manager._configure_postgres_secrets_sync = lambda *_: None
        manager._put_workflow_sync = lambda *_: None
        manager._protect_main_branch_sync = lambda *_: None
        manager._create_sonarcloud_project_sync = lambda _: None

        await manager._create_repository_from_template(
            state.creation_id,
            TemplateRepositoryCreateRequest(
                name=state.repository.rsplit("/", 1)[1],
                template_name=template_name,
                postgres=_postgres_connection() if "postgres" in template_name else None,
            ),
        )

        assert (await manager.get_creation_status(state.creation_id)).status == "done"

    asyncio.run(run())


class Item:
    def __init__(self, path, content="", item_type="file"):
        self.path = path
        self.sha = "sha"
        self.type = item_type
        self.decoded_content = content.encode()


def _postgres_connection():
    return PostgresConnection(
        host="db.example.test",
        database="orders",
        user="orders",
        password="app-password",
        root_user="postgres",
        root_password="root-password",
    )


def _mongodb_connection():
    return MongoConnection(host="mongo.example.test", database="orders-qa", user="orders", password="mongo-password")


def test_repository_file_operations(manager):
    from github.GithubException import UnknownObjectException

    calls = []

    class Repo:
        def get_contents(self, path, ref=None):
            if path == "missing.txt":
                raise UnknownObjectException(404, {"message": "Not Found"}, None)
            return Item(path)

        def update_file(self, *args, **kwargs):
            calls.append(("update", args, kwargs))

        def create_file(self, *args, **kwargs):
            calls.append(("create", args, kwargs))

        def delete_file(self, *args, **kwargs):
            calls.append(("delete", args, kwargs))

    manager._repo = lambda _: Repo()
    manager._put_file_sync("orders", "exists.txt", "content", "update")
    manager._put_file_sync("orders", "missing.txt", "content", "create")
    manager._delete_path_sync("orders", "exists.txt")

    assert [call[0] for call in calls] == ["update", "create", "delete"]


def test_repository_readiness_and_template_validation(manager):
    class Branch:
        commit = SimpleNamespace(sha="commit")

        def edit_protection(self, **kwargs):
            self.protection = kwargs

    class Repo:
        def __init__(self):
            self.branch = Branch()
            self.raw_data = {"is_template": True}

        def get_branch(self, _):
            return self.branch

        def get_commit(self, _):
            return None

        def get_contents(self, _, ref=None):
            return Item("path")

    repo = Repo()
    manager._repo = lambda _: repo
    manager._wait_until_repository_ready_sync("orders")
    manager._wait_until_paths_exist_sync("orders", ["path"])
    manager._protect_main_branch_sync("orders", "postgres")

    async def run():
        manager.list_templates = lambda: asyncio.sleep(0, result=[TemplateResponse(name="template", private=True, url="url")])
        await manager._assert_template_exists("template")

    asyncio.run(run())
    assert repo.branch.protection["required_approving_review_count"] == 1
    assert "sql" in repo.branch.protection["contexts"]

    manager._protect_main_branch_sync("orders", "mongodb")
    assert repo.branch.protection["contexts"] == ["ci", "conventional-commits", "sql"]


def test_android_template_helpers(manager):
    content = "pluginManagement { repositories { google() } }\nrootProject.name = \"app\"\n"

    assert manager._block_content("block { value }", "block") == " value "
    assert manager._insert_after_plugin_management(content, "value\n").endswith('value\nrootProject.name = "app"\n')


def test_github_creation_helpers(manager):
    created = {}

    class Org:
        def get_repos(self, **kwargs):
            created["repos"] = kwargs
            return [SimpleNamespace(name="api-template", description=None, private=True, html_url="url")]

        def create_repo(self, **kwargs):
            created["repo"] = kwargs
            return SimpleNamespace(name=kwargs["name"])

    class Requester:
        def requestJsonAndCheck(self, method, path, input):
            created["request"] = (method, path, input)
            return None, {"url": "https://api.github.test/repos/Ouros-App/orders"}

    manager._org = lambda: Org()
    manager._client = SimpleNamespace(
        requester=Requester(),
        get_repo=lambda _: SimpleNamespace(name="orders"),
    )

    assert len(manager._list_templates_sync()) == 1
    payload = BareRepositoryCreateRequest(name="orders", language="fastapi", description="orders\napi")
    manager._create_bare_repository_sync(payload)
    manager._create_from_template_sync(
        TemplateRepositoryCreateRequest(name="orders", template_name="api-template", description="orders\napi")
    )

    assert created["repo"]["gitignore_template"] == "Python"
    assert created["repo"]["description"] == "orders api"
    assert created["request"][2]["description"] == "orders api"
    assert created["request"][0] == "POST"


def test_workflow_polling_and_creation_state(manager):
    from github.GithubException import UnknownObjectException

    written = []
    manager._put_file_sync = lambda *args: written.append(args)
    manager._put_workflow_sync("orders", "fastapi")

    class Repo:
        def get_contents(self, *_args, **_kwargs):
            raise UnknownObjectException(404, {"message": "Not Found"}, None)

    manager._repo = lambda _: Repo()
    manager._wait_until_paths_absent_sync("orders", ["old-path"])

    async def run():
        state = await manager._create_state("orders", "bare")
        await manager._mark_running(state.creation_id)
        await manager._step(state.creation_id, "working")
        await manager._mark_succeeded(state.creation_id, "url")
        status = await manager.get_creation_status(state.creation_id)
        assert status.status == "done"
        assert status.current_step == "working"
        assert status.url == "url"
        assert await manager.get_creation_status("missing") is None

    asyncio.run(run())
    assert written[0][1] == ".github/workflows/ci-cd.yml"


def test_android_template_initialization_and_settings(manager):
    calls = []

    class Repo:
        def get_branch(self, _):
            return SimpleNamespace(commit=SimpleNamespace(sha="main"))

        def get_git_tree(self, *_args, **_kwargs):
            return SimpleNamespace(tree=[SimpleNamespace(type="blob", path="app/{{PROJECT_NAME}}.txt")])

        def get_contents(self, path, **_kwargs):
            return Item(path, "{{APP_LABEL}}")

        def create_file(self, **kwargs):
            calls.append(("create", kwargs))

        def delete_file(self, **kwargs):
            calls.append(("delete", kwargs))

        def update_file(self, **kwargs):
            calls.append(("update", kwargs))

    repo = Repo()
    manager._repo = lambda _: repo
    manager._initialize_android_template_sync("my-app-template")
    manager._ensure_android_settings_repositories_sync("my-app-template")

    assert {call[0] for call in calls} == {"create", "delete", "update"}
    assert "mavenCentral()" in calls[-1][1]["content"]


def test_repository_lookup_template_detection_and_directory_delete(manager):
    calls = []

    class Repo:
        def get_contents(self, path, **_kwargs):
            if path == "directory":
                return [Item(f"{path}/first"), Item(f"{path}/second")]
            return Item(path)

        def delete_file(self, **kwargs):
            calls.append(kwargs["path"])

    repo = Repo()
    manager._client = SimpleNamespace(get_organization=lambda _: "org", get_repo=lambda _: repo)

    assert manager._org() == "org"
    assert manager._repo("orders") is repo
    assert manager._is_template_repository(SimpleNamespace(raw_data={"is_template": True}))
    assert manager._is_template_repository(SimpleNamespace(raw_data={}, is_template=False)) is False
    assert manager._is_template_repository(SimpleNamespace(raw_data={})) is False
    manager._delete_path_sync("orders", "directory")

    assert calls == ["directory/first", "directory/second"]


def test_configures_postgres_secrets(manager):
    secrets = {}

    class Repo:
        def create_secret(self, name, value):
            secrets[name] = value

    manager._repo = lambda _: Repo()
    manager._configure_postgres_secrets_sync("orders-database", _postgres_connection())

    assert secrets["POSTGRES_HOST"] == "db.example.test"
    assert secrets["POSTGRES_PORT"] == "5432"
    assert secrets["POSTGRES_DB"] == "orders"
    assert secrets["POSTGRES_USER"] == "orders"
    assert secrets["POSTGRES_PASSWORD"] == "app-password"
    assert secrets["POSTGRES_ROOT_DB"] == "postgres"
    assert secrets["POSTGRES_ROOT_USER"] == "postgres"
    assert secrets["POSTGRES_ROOT_PASSWORD"] == "root-password"


def test_configures_mongodb_secrets(manager):
    secrets = {}

    class Repo:
        def create_secret(self, name, value):
            secrets[name] = value

    manager._repo = lambda _: Repo()
    manager._configure_mongodb_secrets_sync("orders-database", _mongodb_connection())

    assert secrets == {
        "MONGODB_HOST": "mongo.example.test",
        "MONGODB_PORT": "27017",
        "MONGODB_DB": "orders-qa",
        "MONGODB_USER": "orders",
        "MONGODB_PASSWORD": "mongo-password",
        "MONGODB_AUTH_DB": "admin",
    }


def test_debug_logging_paths(manager, monkeypatch):
    import app.services.github_manager as manager_module

    class Repo:
        def get_contents(self, path, **_kwargs):
            if path == "missing":
                from github.GithubException import UnknownObjectException

                raise UnknownObjectException(404, {"message": "Not Found"}, None)
            return Item(path)

        def update_file(self, **_kwargs):
            return None

        def create_file(self, **_kwargs):
            return None

    monkeypatch.setattr(manager_module, "DEBUG", True)
    monkeypatch.setattr(manager_module.settings, "SONAR_CLOUD_TOKEN", None)
    manager._put_file_sync = lambda *_: None
    manager._workflow = lambda _: "Disable Automatic Analysis"
    manager._put_workflow_sync("orders", "fastapi")
    manager._workflow = lambda _: "workflow"
    manager._put_workflow_sync("orders", "fastapi")
    manager._create_sonarcloud_project_sync("orders")
    manager._repo = lambda _: Repo()
    manager._put_file_sync("orders", "exists", "content", "update")
    manager._put_file_sync("orders", "missing", "content", "create")

    assert manager._template_language("fastapi-template") == "fastapi"
    assert manager._template_language("generic-template") == "generic"


@pytest.mark.parametrize("mode", ["bare", "template"])
def test_creation_failure_marks_status(manager, mode):
    async def run():
        state = await manager._create_state("orders", mode)
        if mode == "bare":
            manager._create_bare_repository_sync = lambda _: (_ for _ in ()).throw(RuntimeError("failed"))
            await manager._create_bare_repository(state.creation_id, BareRepositoryCreateRequest(name="orders"))
        else:
            manager._assert_template_exists = lambda _: (_ for _ in ()).throw(RuntimeError("failed"))
            await manager._create_repository_from_template(
                state.creation_id,
                TemplateRepositoryCreateRequest(name="orders", template_name="api-template"),
            )

        assert (await manager.get_creation_status(state.creation_id)).status == "failed"

    asyncio.run(run())
