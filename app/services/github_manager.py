import asyncio
import logging
import os
import re
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

import httpx
from github import Auth, Github
from github.GithubException import GithubException, UnknownObjectException

from app.core.config import settings

DEBUG = os.getenv("DEBUG_GITHUB_MANAGER", "").lower() in ("1", "true", "yes")
logger = logging.getLogger(__name__)
if DEBUG:
    logging.basicConfig(level=logging.DEBUG)
    logger.setLevel(logging.DEBUG)
from app.schemas.github import (
    BareRepositoryCreateRequest,
    CreationStatusValue,
    MongoConnection,
    PostgresConnection,
    RepositoryCreationStatusResponse,
    TemplateRepositoryCreateRequest,
    TemplateResponse,
)


class GitHubManagerError(RuntimeError):
    pass


@dataclass
class CreationState:
    creation_id: str
    repository: str
    mode: Literal["bare", "template"]
    status: CreationStatusValue = "queued"
    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    finished_at: datetime | None = None
    steps: list[str] = field(default_factory=list)
    error: str | None = None
    url: str | None = None


class GitHubRepositoryManager:
    _WORKFLOW_DIR = Path(__file__).resolve().parents[1] / "templates" / "workflows"
    _REPOSITORY_READY_INTERVAL_SECONDS = 2
    _README_PATH = "README.md"
    _TEMPLATE_SUFFIX_PATTERN = r"[-_.]?template$"
    _TEMPLATE_KEYWORDS = (
        ("frontend", ("frontend", "react", "vite", "typescript")),
        ("springboot", ("spring", "java")),
        ("android", ("android", "kotlin", "mobile")),
        ("fastapi", ("fastapi",)),
        ("mongodb", ("mongodb", "mongo")),
        ("postgres", ("postgres", "postgresql")),
    )

    def __init__(self) -> None:
        self._creations: dict[str, CreationState] = {}
        self._lock = asyncio.Lock()
        if not settings.GH_TOKEN:
            raise GitHubManagerError("GH_TOKEN ou GITHUB_TOKEN nao configurado no ambiente.")
        self._client = Github(
            auth=Auth.Token(settings.GH_TOKEN),
            timeout=settings.GH_TIMEOUT_SECONDS,
        )

    async def list_templates(self) -> list[TemplateResponse]:
        repos = await asyncio.to_thread(self._list_templates_sync)
        return [
            TemplateResponse(
                name=repo.name,
                description=repo.description,
                private=repo.private,
                url=repo.html_url,
            )
            for repo in repos
            if repo.name.endswith(settings.TEMPLATE_SUFFIX)
        ]

    async def start_bare_creation(self, payload: BareRepositoryCreateRequest) -> CreationState:
        state = await self._create_state(payload.name, "bare")
        asyncio.create_task(self._create_bare_repository(state.creation_id, payload))
        return state

    async def start_template_creation(self, payload: TemplateRepositoryCreateRequest) -> CreationState:
        state = await self._create_state(payload.name, "template")
        asyncio.create_task(self._create_repository_from_template(state.creation_id, payload))
        return state

    async def get_creation_status(self, creation_id: str) -> RepositoryCreationStatusResponse | None:
        async with self._lock:
            state = self._creations.get(creation_id)
            if state is None:
                return None
            return self._serialize_state(state)

    async def _create_state(self, repository_name: str, mode: Literal["bare", "template"]) -> CreationState:
        state = CreationState(
            creation_id=str(uuid.uuid4()),
            repository=f"{settings.GITHUB_ORG_LOGIN}/{repository_name}",
            mode=mode,
        )
        async with self._lock:
            self._creations[state.creation_id] = state
        return state

    async def _create_bare_repository(
        self,
        creation_id: str,
        payload: BareRepositoryCreateRequest,
    ) -> None:
        try:
            await self._mark_running(creation_id)
            await self._step(creation_id, "Criando repositorio cru")
            repo = await asyncio.to_thread(self._create_bare_repository_sync, payload)
            await self._step(creation_id, "Aguardando branch main")
            await asyncio.to_thread(self._wait_until_repository_ready_sync, repo.name)

            if payload.language == "springboot":
                await self._step(creation_id, "Aplicando estrutura Spring REST")
                await asyncio.to_thread(self._put_springboot_scaffold_sync, repo.name)
                await self._step(creation_id, "Configurando sonar-project.properties")
                await asyncio.to_thread(self._put_sonar_properties_sync, repo.name)
            if payload.language == "android":
                await self._step(creation_id, "Aplicando estrutura Android Kotlin")
                await asyncio.to_thread(self._put_android_scaffold_sync, repo.name)
            if payload.language == "postgres":
                await self._step(creation_id, "Aplicando estrutura PostgreSQL")
                await asyncio.to_thread(self._put_postgres_scaffold_sync, repo.name)

            if self._gitignore_template(payload.language) is None:
                await self._step(creation_id, "Criando .gitignore generico")
                await asyncio.to_thread(
                    self._put_file_sync,
                    repo.name,
                    ".gitignore",
                    self._generic_gitignore(),
                    "Add generic gitignore",
                )

            await self._step(creation_id, "Aplicando CI/CD")
            await asyncio.to_thread(self._put_workflow_sync, repo.name, payload.language)

            await self._step(creation_id, "Aplicando protecao da branch main")
            await asyncio.to_thread(self._protect_main_branch_sync, repo.name, payload.language)

            if payload.language == "springboot":
                await self._step(creation_id, "Criando projeto no SonarCloud")
                await asyncio.to_thread(self._create_sonarcloud_project_sync, repo.name)

            await self._mark_succeeded(creation_id, repo.html_url)
        except Exception as exc:  # noqa: BLE001
            await self._mark_failed(creation_id, str(exc))

    async def _create_repository_from_template(
        self,
        creation_id: str,
        payload: TemplateRepositoryCreateRequest,
    ) -> None:
        try:
            await self._mark_running(creation_id)
            await self._assert_template_exists(payload.template_name)

            await self._step(creation_id, "Criando repositorio a partir do template")
            repo = await asyncio.to_thread(self._create_from_template_sync, payload)
            await self._step(creation_id, "Aguardando copia do template")
            await asyncio.to_thread(self._wait_until_repository_ready_sync, repo.name)
            template_language = self._template_language(payload.template_name)

            if template_language == "springboot":
                await self._step(creation_id, "Aguardando arquivos Spring do template")
                await asyncio.to_thread(
                    self._wait_until_paths_exist_sync,
                    repo.name,
                    ["build.gradle", "settings.gradle", "src/main/java", "src/test/java"],
                )
                await self._step(creation_id, "Limpando estrutura Spring do template")
                await asyncio.to_thread(self._clear_springboot_template_structure_sync, repo.name)
                await self._step(creation_id, "Aguardando remocao da estrutura Spring antiga")
                await asyncio.to_thread(self._wait_until_paths_absent_sync, repo.name, ["src/main/java", "src/test/java"])
                await self._step(creation_id, "Aplicando estrutura Spring REST")
                await asyncio.to_thread(self._put_springboot_scaffold_sync, repo.name)
                await self._step(creation_id, "Configurando sonar-project.properties")
                await asyncio.to_thread(self._put_sonar_properties_sync, repo.name)

            if template_language == "android":
                await self._step(creation_id, "Inicializando template Android Kotlin")
                await asyncio.to_thread(self._initialize_android_template_sync, repo.name)
            if template_language == "postgres":
                await self._step(creation_id, "Inicializando template PostgreSQL")
                await asyncio.to_thread(self._put_postgres_scaffold_sync, repo.name)
                await self._step(creation_id, "Configurando secrets PostgreSQL")
                await asyncio.to_thread(self._configure_postgres_secrets_sync, repo.name, payload.postgres)
            if template_language == "mongodb":
                await self._step(creation_id, "Configurando secrets MongoDB")
                await asyncio.to_thread(self._configure_mongodb_secrets_sync, repo.name, payload.mongodb)

            await self._step(creation_id, "Aplicando CI/CD")
            await asyncio.to_thread(
                self._put_workflow_sync,
                repo.name,
                template_language,
            )

            await self._step(creation_id, "Aplicando protecao da branch main")
            await asyncio.to_thread(self._protect_main_branch_sync, repo.name, template_language)

            if template_language == "springboot":
                await self._step(creation_id, "Criando projeto no SonarCloud")
                await asyncio.to_thread(self._create_sonarcloud_project_sync, repo.name)

            await self._mark_succeeded(creation_id, repo.html_url)
        except Exception as exc:  # noqa: BLE001
            await self._mark_failed(creation_id, str(exc))

    async def _assert_template_exists(self, template_name: str) -> None:
        templates = await self.list_templates()
        if template_name not in {template.name for template in templates}:
            raise ValueError(
                f"Template '{template_name}' nao encontrado em {settings.GITHUB_ORG_LOGIN} "
                f"com sufixo '{settings.TEMPLATE_SUFFIX}'."
            )

        repo = await asyncio.to_thread(self._repo, template_name)
        if not self._is_template_repository(repo):
            raise ValueError(
                f"Repositorio '{settings.GITHUB_ORG_LOGIN}/{template_name}' existe, "
                "mas nao esta marcado como template no GitHub."
            )

    def _list_templates_sync(self):
        return list(self._org().get_repos(type="all"))

    def _create_bare_repository_sync(self, payload: BareRepositoryCreateRequest):
        kwargs = {
            "name": payload.name,
            "description": self._github_description(payload.description),
            "private": False,
            "auto_init": True,
            "license_template": "mit",
        }
        gitignore_template = self._gitignore_template(payload.language)
        if gitignore_template is not None:
            kwargs["gitignore_template"] = gitignore_template
        try:
            return self._org().create_repo(**kwargs)
        except GithubException as exc:
            raise GitHubManagerError(self._format_github_error(exc)) from exc

    def _create_from_template_sync(self, payload: TemplateRepositoryCreateRequest):
        try:
            _, data = self._client.requester.requestJsonAndCheck(
                "POST",
                f"/repos/{settings.GITHUB_ORG_LOGIN}/{payload.template_name}/generate",
                input={
                    "owner": settings.GITHUB_ORG_LOGIN,
                    "name": payload.name,
                    "description": self._github_description(payload.description),
                    "private": False,
                    "include_all_branches": False,
                },
            )
            repo_url = data["url"] if isinstance(data, dict) else None
            if not repo_url:
                raise GitHubManagerError("Resposta invalida ao gerar repositorio por template.")
            return self._client.get_repo(f"{settings.GITHUB_ORG_LOGIN}/{payload.name}")
        except GithubException as exc:
            if getattr(exc, "status", None) == 404:
                raise GitHubManagerError(
                    f"GitHub retornou 404 ao gerar o repositorio a partir de "
                    f"'{settings.GITHUB_ORG_LOGIN}/{payload.template_name}'. "
                    "Verifique se o template existe, se esta marcado como template "
                    "e se o token tem acesso ao repositorio."
                ) from exc
            raise GitHubManagerError(self._format_github_error(exc)) from exc

    def _put_workflow_sync(self, repository_name: str, language: str) -> None:
        workflow_content = self._workflow(language)
        if DEBUG:
            logger.debug(f"[_put_workflow_sync] repo={repository_name} language={language} workflow_path={self._WORKFLOW_DIR / f'{language}.yml'} exists={(self._WORKFLOW_DIR / f'{language}.yml').exists()} content_len={len(workflow_content)}")
            if "Disable Automatic Analysis" in workflow_content:
                logger.debug("[_put_workflow_sync] Workflow CONTAINS 'Disable Automatic Analysis' step")
            else:
                logger.debug("[_put_workflow_sync] Workflow MISSING 'Disable Automatic Analysis' step!")
        self._put_file_sync(
            repository_name,
            ".github/workflows/ci-cd.yml",
            workflow_content,
            "Configure CI/CD",
        )

    def _github_description(self, value: str | None) -> str:
        return re.sub(r"[\x00-\x1f\x7f]+", " ", value or "").strip()

    def _put_springboot_scaffold_sync(self, repository_name: str) -> None:
        application_name = self._springboot_application_name(repository_name)
        package_name = self._springboot_package_name(repository_name)
        package_path = package_name.replace(".", "/")
        application_class_name = self._springboot_application_class_name(repository_name)
        files = {
            self._README_PATH: (
                f"# {repository_name}\n\n"
                "Projeto inicial Spring REST API com Gradle.\n\n"
                "## Comandos\n\n"
                "```bash\n"
                "./gradlew clean build\n"
                "./gradlew bootRun\n"
                "```\n"
            ),
            "build.gradle": self._springboot_build_gradle(),
            "settings.gradle": self._springboot_settings_gradle(repository_name),
            f"src/main/java/{package_path}/{application_class_name}.java": self._springboot_application_java(
                package_name,
                application_class_name,
            ),
            f"src/main/java/{package_path}/controller/HomeController.java": self._springboot_home_controller_java(
                package_name
            ),
            f"src/main/java/{package_path}/controller/HealthController.java": self._springboot_health_controller_java(
                package_name
            ),
            "src/main/resources/application.properties": self._springboot_application_properties(application_name),
            "src/main/resources/application-local.properties": self._springboot_application_properties(application_name),
            f"src/test/java/{package_path}/{application_class_name}Tests.java": self._springboot_application_tests_java(
                package_name,
                application_class_name,
            ),
        }
        for path, content in files.items():
            self._put_file_sync(
                repository_name,
                path,
                content,
                f"Add Spring REST scaffold: {Path(path).name}",
            )

    def _clear_springboot_template_structure_sync(self, repository_name: str) -> None:
        for path in (
            "src",
            "src/main/resources/application.properties",
            "src/main/resources/application-local.properties",
        ):
            self._delete_path_sync(repository_name, path)

    def _create_sonar_properties_sync(self, repository_name: str) -> str:
        project_key = f"{settings.GITHUB_ORG_LOGIN}_{repository_name}"
        return f"""sonar.organization={settings.GITHUB_ORG_LOGIN.lower()}
sonar.projectKey={project_key}
sonar.projectName={repository_name}
sonar.sources=src/main
sonar.tests=src/test
sonar.java.binaries=build/classes
sonar.junit.reportPaths=build/test-results/test
sonar.coverage.jacoco.xmlReportPaths=build/reports/jacoco/test/jacocoTestReport.xml
sonar.sourceEncoding=UTF-8
"""

    def _put_sonar_properties_sync(self, repository_name: str) -> None:
        content = self._create_sonar_properties_sync(repository_name)
        self._put_file_sync(
            repository_name,
            "sonar-project.properties",
            content,
            "ci: configure SonarCloud analysis",
        )

    def _create_sonarcloud_project_sync(self, repository_name: str) -> None:
        if not settings.SONAR_CLOUD_TOKEN:
            if DEBUG:
                logger.debug("[_create_sonarcloud_project_sync] SONAR_CLOUD_TOKEN not set, skipping")
            return
        project_key = f"{settings.GITHUB_ORG_LOGIN}_{repository_name}"
        org = settings.GITHUB_ORG_LOGIN.lower()
        url = "https://sonarcloud.io/api/projects/create"
        data = {
            "organization": org,
            "project": project_key,
            "name": repository_name,
            "visibility": "public",
        }
        try:
            resp = httpx.post(
                url,
                data=data,
                auth=(settings.SONAR_CLOUD_TOKEN, ""),
                timeout=30.0,
            )
            if resp.status_code in (200, 400):
                if DEBUG:
                    logger.debug(f"[_create_sonarcloud_project_sync] project created/exists: {project_key} status={resp.status_code}")
            else:
                raise GitHubManagerError(f"SonarCloud project creation failed: {resp.status_code} {resp.text}")
        except httpx.RequestError as exc:
            raise GitHubManagerError(f"SonarCloud API request failed: {exc}") from exc

    def _springboot_build_gradle(self) -> str:
        return """plugins {
    id 'java'
    id 'jacoco'
    id 'org.springframework.boot' version '3.4.0'
    id 'io.spring.dependency-management' version '1.1.6'
    id 'org.sonarqube' version '6.2.0.5505'
}

group = 'com.ourosapp'
version = '0.0.1-SNAPSHOT'

repositories {
    mavenCentral()
}

dependencies {
    implementation 'org.springframework.boot:spring-boot-starter-web'
    testImplementation 'org.springframework.boot:spring-boot-starter-test'
}

tasks.named('test') {
    useJUnitPlatform()
}

tasks.named('jacocoTestReport') {
    dependsOn tasks.named('test')
    reports {
        xml.required = true
        html.required = true
    }
}

tasks.withType(JavaCompile).configureEach {
    options.release = 17
}
"""

    def _springboot_settings_gradle(self, repository_name: str) -> str:
        return f"rootProject.name = '{repository_name}'\n"

    def _springboot_application_java(self, package_name: str, class_name: str) -> str:
        return """package PACKAGE_NAME;

import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;

@SpringBootApplication
public class CLASS_NAME {

    public static void main(String[] args) {
        SpringApplication.run(CLASS_NAME.class, args);
    }
}
""".replace("PACKAGE_NAME", package_name).replace("CLASS_NAME", class_name)

    def _springboot_home_controller_java(self, package_name: str) -> str:
        return """package PACKAGE_NAME.controller;

import java.util.Map;

import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
public class HomeController {

    @GetMapping("/")
    public Map<String, String> home() {
        return Map.of(
            "message",
            "Spring REST API com Gradle pronta para evoluir."
        );
    }
}
""".replace("PACKAGE_NAME", package_name)

    def _springboot_health_controller_java(self, package_name: str) -> str:
        return """package PACKAGE_NAME.controller;

import java.util.Map;

import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
public class HealthController {

    @GetMapping("/health")
    public Map<String, String> health() {
        return Map.of("status", "ok");
    }
}
""".replace("PACKAGE_NAME", package_name)

    def _springboot_application_properties(self, application_name: str) -> str:
        return f"""spring.application.name={application_name}
server.port=${{SERVER_PORT:8080}}
"""

    def _springboot_application_tests_java(self, package_name: str, class_name: str) -> str:
        return """package PACKAGE_NAME;

import org.junit.jupiter.api.Test;
import org.springframework.boot.test.context.SpringBootTest;

@SpringBootTest
class CLASS_NAMETests {

    @Test
    void contextLoads() {
    }
}
""".replace("PACKAGE_NAME", package_name).replace("CLASS_NAME", class_name)

    def _put_android_scaffold_sync(self, repository_name: str) -> None:
        namespace = self._android_namespace(repository_name)
        app_name = self._android_app_name(repository_name)
        files = {
            self._README_PATH: self._android_readme(repository_name),
            "settings.gradle.kts": self._android_settings_gradle(repository_name),
            "build.gradle.kts": self._android_root_build_gradle(),
            "gradle.properties": self._android_gradle_properties(),
            "app/build.gradle.kts": self._android_app_build_gradle(namespace),
            "app/src/main/AndroidManifest.xml": self._android_manifest(),
            "app/proguard-rules.pro": "",
            "app/src/main/java/{}/MainActivity.kt".format(namespace.replace(".", "/")): self._android_main_activity(
                namespace
            ),
            "app/src/main/res/values/strings.xml": self._android_strings(app_name),
            "app/src/main/res/values/colors.xml": self._android_colors(),
            "app/src/main/res/values/themes.xml": self._android_themes(),
            "app/src/test/java/{}/ExampleUnitTest.kt".format(namespace.replace(".", "/")): self._android_unit_test(
                namespace
            ),
        }
        for path, content in files.items():
            self._put_file_sync(
                repository_name,
                path,
                content,
                f"Add Android Kotlin scaffold: {Path(path).name}",
            )

    def _android_readme(self, repository_name: str) -> str:
        return f"""# {repository_name}

Projeto Android Kotlin com Gradle, no formato padrao do Android Studio.

## Comandos

```bash
gradle :app:assembleDebug
gradle :app:testDebugUnitTest
```
"""

    def _android_settings_gradle(self, repository_name: str) -> str:
        return f"""pluginManagement {{
    repositories {{
        google()
        mavenCentral()
        gradlePluginPortal()
    }}
}}

dependencyResolutionManagement {{
    repositoriesMode.set(RepositoriesMode.FAIL_ON_PROJECT_REPOS)
    repositories {{
        google()
        mavenCentral()
    }}
}}

rootProject.name = "{repository_name}"
include(":app")
"""

    def _android_root_build_gradle(self) -> str:
        return """plugins {
    id("com.android.application") version "8.7.3" apply false
    id("org.jetbrains.kotlin.android") version "2.0.21" apply false
}
"""

    def _android_gradle_properties(self) -> str:
        return """org.gradle.jvmargs=-Xmx2048m -Dfile.encoding=UTF-8
android.useAndroidX=true
kotlin.code.style=official
android.nonTransitiveRClass=true
"""

    def _android_app_build_gradle(self, namespace: str) -> str:
        return f"""plugins {{
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
}}

android {{
    namespace = "{namespace}"
    compileSdk = 35

    defaultConfig {{
        applicationId = "{namespace}"
        minSdk = 24
        targetSdk = 35
        versionCode = 1
        versionName = "1.0"

        testInstrumentationRunner = "androidx.test.runner.AndroidJUnitRunner"
    }}

    buildTypes {{
        release {{
            isMinifyEnabled = false
            proguardFiles(
                getDefaultProguardFile("proguard-android-optimize.txt"),
                "proguard-rules.pro"
            )
        }}
    }}
    compileOptions {{
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }}
    kotlinOptions {{
        jvmTarget = "17"
    }}
}}

dependencies {{
    implementation("androidx.core:core-ktx:1.15.0")
    implementation("androidx.appcompat:appcompat:1.7.0")
    implementation("com.google.android.material:material:1.12.0")
    testImplementation("junit:junit:4.13.2")
    androidTestImplementation("androidx.test.ext:junit:1.2.1")
    androidTestImplementation("androidx.test.espresso:espresso-core:3.6.1")
}}
"""

    def _android_manifest(self) -> str:
        return """<?xml version="1.0" encoding="utf-8"?>
<manifest xmlns:android="http://schemas.android.com/apk/res/android">
    <application
        android:allowBackup="true"
        android:label="@string/app_name"
        android:supportsRtl="true"
        android:theme="@style/Theme.App">
        <activity
            android:name=".MainActivity"
            android:exported="true">
            <intent-filter>
                <action android:name="android.intent.action.MAIN" />
                <category android:name="android.intent.category.LAUNCHER" />
            </intent-filter>
        </activity>
    </application>
</manifest>
"""

    def _android_main_activity(self, namespace: str) -> str:
        return f"""package {namespace}

import android.os.Bundle
import android.widget.TextView
import androidx.appcompat.app.AppCompatActivity

class MainActivity : AppCompatActivity() {{
    override fun onCreate(savedInstanceState: Bundle?) {{
        super.onCreate(savedInstanceState)
        setContentView(TextView(this).apply {{
            text = getString(R.string.app_name)
            textSize = 24f
        }})
    }}
}}
"""

    def _android_strings(self, app_name: str) -> str:
        return f"""<resources>
    <string name="app_name">{app_name}</string>
</resources>
"""

    def _android_colors(self) -> str:
        return """<resources>
    <color name="purple_500">#6200EE</color>
    <color name="purple_700">#3700B3</color>
    <color name="teal_200">#03DAC5</color>
</resources>
"""

    def _android_themes(self) -> str:
        return """<resources xmlns:tools="http://schemas.android.com/tools">
    <style name="Theme.App" parent="Theme.MaterialComponents.DayNight.NoActionBar">
        <item name="colorPrimary">@color/purple_500</item>
        <item name="colorPrimaryVariant">@color/purple_700</item>
        <item name="colorOnPrimary">#FFFFFF</item>
        <item name="colorSecondary">@color/teal_200</item>
        <item name="android:statusBarColor" tools:targetApi="l">?attr/colorPrimaryVariant</item>
    </style>
</resources>
"""

    def _android_unit_test(self, namespace: str) -> str:
        return f"""package {namespace}

import org.junit.Assert.assertEquals
import org.junit.Test

class ExampleUnitTest {{
    @Test
    fun addition_isCorrect() {{
        assertEquals(4, 2 + 2)
    }}
}}
"""

    def _initialize_android_template_sync(self, repository_name: str) -> None:
        repo = self._repo(repository_name)
        placeholders = self._android_template_placeholders(repository_name)
        branch = repo.get_branch(settings.DEFAULT_BRANCH)
        tree = repo.get_git_tree(branch.commit.sha, recursive=True)
        remaining: list[str] = []

        for item in tree.tree:
            if item.type != "blob":
                continue
            self._replace_android_template_file_sync(repo, item.path, placeholders, remaining)

        if remaining:
            display = ", ".join(sorted(set(remaining)))
            raise GitHubManagerError(f"Placeholders Android nao substituidos: {display}")

        self._ensure_android_settings_repositories_sync(repository_name)

    def _replace_android_template_file_sync(self, repo, path: str, placeholders: dict[str, str], remaining: list[str]) -> None:
        try:
            item = repo.get_contents(path, ref=settings.DEFAULT_BRANCH)
        except UnknownObjectException:
            return
        except GithubException as exc:
            raise GitHubManagerError(self._format_github_error(exc)) from exc

        if isinstance(item, list):
            return

        try:
            original_content = item.decoded_content.decode("utf-8")
        except UnicodeDecodeError:
            return

        new_path = self._replace_placeholders(path, placeholders)
        new_content = self._replace_placeholders(original_content, placeholders)
        leftovers = re.findall(r"\{\{[A-Z_]+\}\}", new_content)
        if leftovers:
            remaining.extend(f"{placeholder} em {new_path}" for placeholder in leftovers)

        if new_path == path and new_content == original_content:
            return

        try:
            if new_path == path:
                repo.update_file(
                    path=path,
                    message=f"Initialize Android template: {Path(path).name}",
                    content=new_content,
                    sha=item.sha,
                    branch=settings.DEFAULT_BRANCH,
                )
                return

            repo.create_file(
                path=new_path,
                message=f"Initialize Android template: {Path(new_path).name}",
                content=new_content,
                branch=settings.DEFAULT_BRANCH,
            )
            repo.delete_file(
                path=path,
                message=f"Remove Android template placeholder path: {path}",
                sha=item.sha,
                branch=settings.DEFAULT_BRANCH,
            )
        except GithubException as exc:
            raise GitHubManagerError(self._format_github_error(exc)) from exc

    def _ensure_android_settings_repositories_sync(self, repository_name: str) -> None:
        repo = self._repo(repository_name)
        path = "settings.gradle.kts"
        try:
            item = repo.get_contents(path, ref=settings.DEFAULT_BRANCH)
        except UnknownObjectException:
            self._put_file_sync(
                repository_name,
                path,
                self._android_settings_gradle(repository_name),
                "Configure Android Gradle repositories",
            )
            return
        except GithubException as exc:
            raise GitHubManagerError(self._format_github_error(exc)) from exc

        if isinstance(item, list):
            return

        try:
            content = item.decoded_content.decode("utf-8")
        except UnicodeDecodeError:
            raise GitHubManagerError("settings.gradle.kts Android nao esta em UTF-8.")

        if self._has_android_gradle_repositories(content):
            return

        updated = self._merge_android_gradle_repositories(content)
        try:
            repo.update_file(
                path=path,
                message="Configure Android Gradle repositories",
                content=updated,
                sha=item.sha,
                branch=settings.DEFAULT_BRANCH,
            )
        except GithubException as exc:
            raise GitHubManagerError(self._format_github_error(exc)) from exc

    def _has_android_gradle_repositories(self, content: str) -> bool:
        dependency_block = self._block_content(content, "dependencyResolutionManagement")
        if not dependency_block:
            return False
        return self._has_android_plugin_repositories(content) and "google()" in dependency_block and "mavenCentral()" in dependency_block

    def _has_android_plugin_repositories(self, content: str) -> bool:
        plugin_block = self._block_content(content, "pluginManagement")
        if not plugin_block:
            return False
        return "google()" in plugin_block and "mavenCentral()" in plugin_block and "gradlePluginPortal()" in plugin_block

    def _merge_android_gradle_repositories(self, content: str) -> str:
        content = self._merge_android_plugin_repositories(content)
        dependency_block = """dependencyResolutionManagement {
    repositoriesMode.set(RepositoriesMode.FAIL_ON_PROJECT_REPOS)
    repositories {
        google()
        mavenCentral()
    }
}

"""
        if "dependencyResolutionManagement" not in content:
            return self._insert_after_plugin_management(content, dependency_block)

        pattern = r"dependencyResolutionManagement\s*\{(?:[^{}]|\{[^{}]*\})*\}\s*"
        return re.sub(pattern, dependency_block, content, count=1, flags=re.DOTALL)

    def _merge_android_plugin_repositories(self, content: str) -> str:
        plugin_block = """pluginManagement {
    repositories {
        google()
        mavenCentral()
        gradlePluginPortal()
    }
}

"""
        if "pluginManagement" not in content:
            return plugin_block + content.lstrip()

        pattern = r"pluginManagement\s*\{(?:[^{}]|\{[^{}]*\})*\}\s*"
        return re.sub(pattern, plugin_block, content, count=1, flags=re.DOTALL)

    def _insert_after_plugin_management(self, content: str, value: str) -> str:
        match = re.search(r"pluginManagement\s*\{(?:[^{}]|\{[^{}]*\})*\}\s*", content, flags=re.DOTALL)
        if not match:
            return value + content.lstrip()
        return content[:match.end()] + value + content[match.end():]

    def _block_content(self, content: str, block_name: str) -> str | None:
        match = re.search(rf"{re.escape(block_name)}\s*\{{", content)
        if not match:
            return None

        depth = 0
        for index in range(match.end() - 1, len(content)):
            char = content[index]
            if char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
                if depth == 0:
                    return content[match.end():index]
        return None

    def _android_template_placeholders(self, repository_name: str) -> dict[str, str]:
        package_name = self._android_namespace(repository_name)
        return {
            "{{PROJECT_NAME}}": repository_name,
            "{{APP_LABEL}}": self._android_app_name(repository_name),
            "{{PACKAGE_NAME}}": package_name,
            "{{PACKAGE_PATH}}": package_name.replace(".", "/"),
            "{{APPLICATION_CLASS_NAME}}": self._android_application_class_name(repository_name),
        }

    def _replace_placeholders(self, value: str, placeholders: dict[str, str]) -> str:
        for placeholder, replacement in placeholders.items():
            value = value.replace(placeholder, replacement)
        return value

    def _android_namespace(self, repository_name: str) -> str:
        normalized = re.sub(self._TEMPLATE_SUFFIX_PATTERN, "", repository_name.lower())
        normalized = re.sub(r"[^a-z0-9]+", "", normalized)
        if not normalized:
            normalized = "app"
        if normalized[0].isdigit():
            normalized = f"app{normalized}"
        return f"com.ourosapp.{normalized}"

    def _android_app_name(self, repository_name: str) -> str:
        normalized = re.sub(self._TEMPLATE_SUFFIX_PATTERN, "", repository_name, flags=re.IGNORECASE)
        normalized = re.sub(r"[-_.]+", " ", normalized).strip()
        return normalized or "Ouros App"

    def _android_application_class_name(self, repository_name: str) -> str:
        parts = re.findall(r"[A-Za-z0-9]+", self._android_app_name(repository_name))
        class_name = "".join(part[:1].upper() + part[1:] for part in parts) or "Ouros"
        if class_name[0].isdigit():
            class_name = f"App{class_name}"
        return f"{class_name}Application"

    def _springboot_package_name(self, repository_name: str) -> str:
        normalized = self._springboot_application_name(repository_name)
        normalized = re.sub(r"[^a-z0-9]+", "", normalized)
        if not normalized:
            normalized = "app"
        if normalized[0].isdigit():
            normalized = f"app{normalized}"
        return f"com.ourosapp.{normalized}"

    def _springboot_application_name(self, repository_name: str) -> str:
        normalized = re.sub(r"^ms[-_.]?", "", repository_name.lower())
        normalized = re.sub(self._TEMPLATE_SUFFIX_PATTERN, "", normalized)
        normalized = re.sub(r"[^a-z0-9-]+", "-", normalized)
        normalized = re.sub(r"-{2,}", "-", normalized).strip("-")
        return normalized or "app"

    def _springboot_application_class_name(self, repository_name: str) -> str:
        sanitized_name = self._springboot_application_name(repository_name)
        parts = re.findall(r"[A-Za-z0-9]+", sanitized_name)
        class_name = "".join(part[:1].upper() + part[1:] for part in parts) or "Application"
        if class_name[0].isdigit():
            class_name = f"App{class_name}"
        return f"{class_name}Application"

    def _put_file_sync(
        self,
        repository_name: str,
        path: str,
        content: str,
        message: str,
    ) -> None:
        repo = self._repo(repository_name)
        if DEBUG:
            logger.debug(f"[_put_file_sync] repo={repository_name} path={path} content_len={len(content)}")
        try:
            existing = repo.get_contents(path, ref=settings.DEFAULT_BRANCH)
            if DEBUG:
                logger.debug(f"[_put_file_sync] File EXISTS, updating... sha={existing.sha}")
            repo.update_file(
                path=path,
                message=message,
                content=content,
                sha=existing.sha,
                branch=settings.DEFAULT_BRANCH,
            )
            if DEBUG:
                logger.debug("[_put_file_sync] File UPDATED successfully")
        except UnknownObjectException:
            if DEBUG:
                logger.debug("[_put_file_sync] File NOT FOUND, creating...")
            try:
                repo.create_file(
                    path=path,
                    message=message,
                    content=content,
                    branch=settings.DEFAULT_BRANCH,
                )
                if DEBUG:
                    logger.debug("[_put_file_sync] File CREATED successfully")
            except GithubException as exc:
                raise GitHubManagerError(self._format_github_error(exc)) from exc
        except GithubException as exc:
            raise GitHubManagerError(self._format_github_error(exc)) from exc

    def _delete_path_sync(self, repository_name: str, path: str) -> None:
        repo = self._repo(repository_name)
        try:
            item = repo.get_contents(path, ref=settings.DEFAULT_BRANCH)
        except UnknownObjectException:
            return
        except GithubException as exc:
            raise GitHubManagerError(self._format_github_error(exc)) from exc

        if isinstance(item, list):
            for child in item:
                self._delete_path_sync(repository_name, child.path)
            return

        try:
            repo.delete_file(
                path=item.path,
                message=f"Remove template scaffold: {item.path}",
                sha=item.sha,
                branch=settings.DEFAULT_BRANCH,
            )
        except GithubException as exc:
            raise GitHubManagerError(self._format_github_error(exc)) from exc

    def _protect_main_branch_sync(self, repository_name: str, language: str = "generic") -> None:
        repo = self._repo(repository_name)
        contexts = ["ci", "conventional-commits"]
        if language != "mongodb":
            contexts.extend(["sonarcloud", "codeql"])
        if language in {"postgres", "mongodb"}:
            contexts.append("sql")
        try:
            branch = repo.get_branch(settings.DEFAULT_BRANCH)
            branch.edit_protection(
                strict=True,
                contexts=contexts,
                enforce_admins=True,
                dismiss_stale_reviews=True,
                require_code_owner_reviews=False,
                required_approving_review_count=1,
                require_last_push_approval=True,
                required_linear_history=True,
                allow_force_pushes=False,
                required_conversation_resolution=True,
                allow_deletions=False,
                block_creations=False,
            )
        except GithubException as exc:
            raise GitHubManagerError(self._format_github_error(exc)) from exc

    def _wait_until_repository_ready_sync(self, repository_name: str) -> None:
        deadline = time.monotonic() + settings.GH_TIMEOUT_SECONDS
        last_error = "Repositorio ainda nao esta pronto."

        while time.monotonic() < deadline:
            try:
                repo = self._repo(repository_name)
                branch = repo.get_branch(settings.DEFAULT_BRANCH)
                repo.get_commit(branch.commit.sha)
                return
            except GithubException as exc:
                last_error = self._format_github_error(exc)
                time.sleep(self._REPOSITORY_READY_INTERVAL_SECONDS)

        raise GitHubManagerError(
            f"Repositorio '{settings.GITHUB_ORG_LOGIN}/{repository_name}' nao ficou pronto: {last_error}"
        )

    def _wait_until_paths_exist_sync(self, repository_name: str, paths: list[str]) -> None:
        deadline = time.monotonic() + settings.GH_TIMEOUT_SECONDS
        repo = self._repo(repository_name)

        while time.monotonic() < deadline:
            missing: list[str] = []
            for path in paths:
                try:
                    repo.get_contents(path, ref=settings.DEFAULT_BRANCH)
                except UnknownObjectException:
                    missing.append(path)
                except GithubException as exc:
                    raise GitHubManagerError(self._format_github_error(exc)) from exc

            if not missing:
                return

            time.sleep(self._REPOSITORY_READY_INTERVAL_SECONDS)

        missing_display = ", ".join(paths)
        raise GitHubManagerError(
            f"Arquivos do template nao ficaram disponiveis em '{settings.GITHUB_ORG_LOGIN}/{repository_name}': "
            f"{missing_display}"
        )

    def _wait_until_paths_absent_sync(self, repository_name: str, paths: list[str]) -> None:
        deadline = time.monotonic() + settings.GH_TIMEOUT_SECONDS
        repo = self._repo(repository_name)

        while time.monotonic() < deadline:
            remaining: list[str] = []
            for path in paths:
                try:
                    repo.get_contents(path, ref=settings.DEFAULT_BRANCH)
                    remaining.append(path)
                except UnknownObjectException:
                    continue
                except GithubException as exc:
                    raise GitHubManagerError(self._format_github_error(exc)) from exc

            if not remaining:
                return

            time.sleep(self._REPOSITORY_READY_INTERVAL_SECONDS)

        remaining_display = ", ".join(paths)
        raise GitHubManagerError(
            f"Estrutura antiga do template ainda existe em '{settings.GITHUB_ORG_LOGIN}/{repository_name}': "
            f"{remaining_display}"
        )

    async def _mark_running(self, creation_id: str) -> None:
        async with self._lock:
            self._creations[creation_id].status = "running"

    async def _mark_succeeded(self, creation_id: str, url: str) -> None:
        async with self._lock:
            state = self._creations[creation_id]
            state.status = "done"
            state.finished_at = datetime.now(timezone.utc)
            state.url = url

    async def _mark_failed(self, creation_id: str, error: str) -> None:
        async with self._lock:
            state = self._creations[creation_id]
            state.status = "failed"
            state.finished_at = datetime.now(timezone.utc)
            state.error = error

    async def _step(self, creation_id: str, message: str) -> None:
        async with self._lock:
            self._creations[creation_id].steps.append(message)

    def _serialize_state(self, state: CreationState) -> RepositoryCreationStatusResponse:
        return RepositoryCreationStatusResponse(
            creation_id=state.creation_id,
            status=state.status,
            repository=state.repository,
            mode=state.mode,
            started_at=state.started_at,
            finished_at=state.finished_at,
            current_step=state.steps[-1] if state.steps else None,
            steps=state.steps,
            error=state.error,
            url=state.url,
        )

    def _gitignore_template(self, language: str) -> str | None:
        templates = {
            "frontend": "Node",
            "springboot": "Java",
            "fastapi": "Python",
            "android": "Android",
            "postgres": "Python",
            "mongodb": "Python",
        }
        return templates.get(language)

    def _template_language(self, template_name: str) -> str:
        normalized_name = template_name.lower()
        if DEBUG:
            logger.debug(f"[_template_language] template_name={template_name} normalized={normalized_name}")
        for language, keywords in self._TEMPLATE_KEYWORDS:
            if any(keyword in normalized_name for keyword in keywords):
                if DEBUG:
                    logger.debug("[_template_language] detected: %s", language)
                return language
        if DEBUG:
            logger.debug("[_template_language] detected: generic")
        return "generic"

    def _put_postgres_scaffold_sync(self, repository_name: str) -> None:
        files = {
            self._README_PATH: self._postgres_readme(repository_name),
            "config.yaml": self._postgres_config_yaml(repository_name),
            ".env.example": self._postgres_env_example(),
            "requirements.txt": self._postgres_requirements_txt(),
            "scripts/apply_sql.py": self._postgres_apply_sql_py(),
            "sql/versionamento.sql": self._postgres_versioning_sql(),
        }
        for path, content in files.items():
            self._put_file_sync(repository_name, path, content, f"Add PostgreSQL template file: {path}")

    def _configure_postgres_secrets_sync(self, repository_name: str, connection: PostgresConnection | None) -> None:
        if connection is None:
            return
        values = {
            "POSTGRES_HOST": connection.host,
            "POSTGRES_PORT": str(connection.port),
            "POSTGRES_DB": connection.database,
            "POSTGRES_USER": connection.user,
            "POSTGRES_PASSWORD": connection.password,
            "POSTGRES_ROOT_DB": connection.root_database,
            "POSTGRES_ROOT_USER": connection.root_user,
            "POSTGRES_ROOT_PASSWORD": connection.root_password,
        }
        repo = self._repo(repository_name)
        for name, value in values.items():
            repo.create_secret(name, value)

    def _configure_mongodb_secrets_sync(self, repository_name: str, connection: MongoConnection | None) -> None:
        if connection is None:
            return
        values = {"MONGODB_URI": connection.connection_url}
        repo = self._repo(repository_name)
        for name, value in values.items():
            repo.create_secret(name, value)

    def _postgres_readme(self, repository_name: str) -> str:
        app_name = self._postgres_app_name(repository_name)
        return f"""# {app_name}

Template para banco PostgreSQL versionado por arquivos SQL locais.

## Estrutura

- `sql/`: arquivos SQL
- `scripts/apply_sql.py`: orquestrador local
- `config.yaml`: ordem de execucao e configuracao
- `.env.example`: variaveis sensiveis

## Uso

```bash
pip install -r requirements.txt
python scripts/apply_sql.py
```
"""

    def _postgres_config_yaml(self, repository_name: str) -> str:
        return f"""project: {repository_name}
database:
  engine: postgresql
  host: ${{POSTGRES_HOST}}
  port: ${{POSTGRES_PORT}}
  name: ${{POSTGRES_DB}}
  bootstrap:
    db: ${{POSTGRES_ROOT_DB}}
    user: ${{POSTGRES_ROOT_USER}}
    password: ${{POSTGRES_ROOT_PASSWORD}}
  owner:
    user: ${{POSTGRES_USER}}
    password: ${{POSTGRES_PASSWORD}}
  sql_path: sql
  version_table: controle_versoes
  version_schema_file: versionamento.sql
  execution_order: []
"""

    def _postgres_env_example(self) -> str:
        return """POSTGRES_HOST=localhost
POSTGRES_PORT=5432
POSTGRES_DB=app
POSTGRES_USER=app
POSTGRES_PASSWORD=app
POSTGRES_ROOT_DB=root_db
POSTGRES_ROOT_USER=ouros_root
POSTGRES_ROOT_PASSWORD=senha-para-root
"""

    def _postgres_requirements_txt(self) -> str:
        return """psycopg2-binary==2.9.9
PyYAML==6.0.2
python-dotenv==1.0.1
"""

    def _postgres_apply_sql_py(self) -> str:
        return """#!/usr/bin/env python3
import hashlib
import os
import re
import subprocess
from pathlib import Path

import psycopg2
import yaml
from dotenv import load_dotenv


ENV_RE = re.compile(r"\\$\\{([A-Z0-9_]+)\\}")


def qident(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def load_config(root: Path) -> dict:
    raw = (root / "config.yaml").read_text(encoding="utf-8")
    def replace(match):
        value = os.getenv(match.group(1))
        if value is None:
            raise RuntimeError(f"Variavel de ambiente obrigatoria ausente: {match.group(1)}")
        return value
    def expand(value):
        if isinstance(value, str):
            return ENV_RE.sub(replace, value)
        if isinstance(value, list):
            return [expand(item) for item in value]
        if isinstance(value, dict):
            return {key: expand(item) for key, item in value.items()}
        return value
    return expand(yaml.safe_load(raw))


def git_value(root: Path, *args: str) -> str:
    res = subprocess.run(["git", *args], cwd=root, capture_output=True, text=True, check=False)
    return res.stdout.strip() if res.returncode == 0 else "unknown"


def connect(cfg: dict, dbname: str, user: str, password: str):
    db = cfg["database"]
    return psycopg2.connect(host=db["host"], port=db["port"], dbname=dbname, user=user, password=password)


def ensure_database(cfg: dict) -> None:
    db = cfg["database"]
    boot = db["bootstrap"]
    owner = db["owner"]
    conn = connect(cfg, boot["db"], boot["user"], boot["password"])
    conn.autocommit = True
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (owner["user"],))
            if cur.fetchone() is None:
                cur.execute(f"CREATE ROLE {qident(owner['user'])} LOGIN PASSWORD %s", (owner["password"],))
            cur.execute("SELECT 1 FROM pg_database WHERE datname = %s", (db["name"],))
            if cur.fetchone() is None:
                cur.execute(f"CREATE DATABASE {qident(db['name'])} OWNER {qident(owner['user'])}")
    finally:
        conn.close()


def ensure_version_table(cur, root: Path, cfg: dict) -> None:
    db = cfg["database"]
    path = root / db["sql_path"] / db["version_schema_file"]
    if not path.is_file():
        raise FileNotFoundError(f"SQL de versionamento nao encontrado: {path}")
    cur.execute(path.read_text(encoding="utf-8"))


def sql_entries(root: Path, cfg: dict) -> list[tuple[Path, str]]:
    db = cfg["database"]
    sql_dir = root / db["sql_path"]
    entries, seen = [], set()
    for item in db["execution_order"]:
        name, mode = (item, "on_change") if isinstance(item, str) else (item.get("file"), item.get("mode", "on_change")) if isinstance(item, dict) else (None, None)
        if not isinstance(name, str) or not name or mode not in {"always", "on_change", "once", "never"}:
            raise ValueError("Cada script exige file e mode valido (always, on_change, once ou never).")
        path = Path(name)
        identity = path.as_posix()
        if path.is_absolute() or ".." in path.parts or path.suffix != ".sql" or identity in seen:
            raise ValueError(f"Script SQL invalido ou duplicado: {name}")
        seen.add(identity)
        path = sql_dir / path
        if not path.is_file():
            raise FileNotFoundError(f"SQL nao encontrado: {path}")
        entries.append((path, mode))
    return entries


def apply_sql_files(root: Path, cfg: dict, cur, commit_id: str) -> None:
    cur.execute("SELECT pg_advisory_xact_lock(84729341)")
    cur.execute("CREATE TABLE IF NOT EXISTS controle_scripts_sql ("
                "arquivo TEXT PRIMARY KEY, checksum VARCHAR(64) NOT NULL, "
                "commit_id VARCHAR(64) NOT NULL, executado_em TIMESTAMPTZ NOT NULL DEFAULT NOW())")
    for path, mode in sql_entries(root, cfg):
        identity = path.relative_to(root / cfg["database"]["sql_path"]).as_posix()
        content = path.read_text(encoding="utf-8")
        checksum = hashlib.sha256(content.encode("utf-8")).hexdigest()
        if mode == "never":
            print(f"[SKIP] {identity}: modo never")
            continue
        cur.execute("SELECT checksum FROM controle_scripts_sql WHERE arquivo = %s", (identity,))
        row = cur.fetchone()
        if mode == "once" and row:
            print(f"[SKIP] {identity}: modo once")
            continue
        if mode == "on_change" and row and row[0] == checksum:
            print(f"[SKIP] {identity}: sem alteracoes")
            continue
        reason = "modo always" if mode == "always" else "modo once" if mode == "once" else "arquivo novo" if not row else "conteudo alterado"
        print(f"[RUN] {identity}: {reason}")
        cur.execute(content)
        cur.execute("INSERT INTO controle_scripts_sql (arquivo, checksum, commit_id) "
                    "VALUES (%s, %s, %s) ON CONFLICT (arquivo) DO UPDATE SET "
                    "checksum = EXCLUDED.checksum, commit_id = EXCLUDED.commit_id, executado_em = NOW()",
                    (identity, checksum, commit_id))


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    load_dotenv(root / ".env")
    cfg = load_config(root)
    db = cfg["database"]
    table = db["version_table"]
    commit_id = os.getenv("GITHUB_SHA") or git_value(root, "rev-parse", "HEAD")
    commit_msg = os.getenv("GITHUB_COMMIT_MESSAGE") or git_value(root, "log", "-1", "--pretty=%B")
    if commit_id == "unknown":
        raise RuntimeError("Nao foi possivel identificar o commit atual.")
    ensure_database(cfg)
    conn = connect(cfg, db["name"], db["owner"]["user"], db["owner"]["password"])
    try:
        with conn:
            with conn.cursor() as cur:
                ensure_version_table(cur, root, cfg)
                apply_sql_files(root, cfg, cur, commit_id)
                cur.execute(
                    f"INSERT INTO {qident(table)} (commit_id, comentario_commit) VALUES (%s, %s)",
                    (commit_id, commit_msg),
                )
        print(f"SQL aplicado no banco {db['name']} e versao registrada para commit {commit_id}")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
"""

    def _postgres_versioning_sql(self) -> str:
        return """CREATE TABLE IF NOT EXISTS controle_versoes (
    id BIGINT GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
    versao BIGINT GENERATED BY DEFAULT AS IDENTITY UNIQUE NOT NULL,
    commit_id VARCHAR(64) NOT NULL,
    comentario_commit TEXT NOT NULL,
    aplicado_em TIMESTAMP DEFAULT NOW()
);
"""

    def _postgres_app_name(self, repository_name: str) -> str:
        normalized = re.sub(r"^ms-", "", repository_name, flags=re.IGNORECASE)
        normalized = re.sub(self._TEMPLATE_SUFFIX_PATTERN, "", normalized, flags=re.IGNORECASE)
        normalized = re.sub(r"[^A-Za-z0-9]+", " ", normalized).strip()
        return normalized or "postgres"

    def _generic_gitignore(self) -> str:
        return """# Environment
.env
.env.*

# Build artifacts
dist/
build/
tmp/
temp/

# Editor and OS files
.DS_Store
.idea/
.vscode/
"""

    def _workflow(self, language: str) -> str:
        workflow_path = self._WORKFLOW_DIR / f"{language}.yml"
        if not workflow_path.exists():
            if DEBUG:
                logger.debug(f"[_workflow] language={language} file NOT FOUND, falling back to generic.yml")
            workflow_path = self._WORKFLOW_DIR / "generic.yml"
        else:
            if DEBUG:
                logger.debug(f"[_workflow] language={language} file FOUND at {workflow_path}")
        content = workflow_path.read_text(encoding="utf-8").replace(
            "__GITHUB_ORG_LOGIN__",
            settings.GITHUB_ORG_LOGIN,
        )
        if DEBUG:
            logger.debug(f"[_workflow] language={language} content_len={len(content)} has_disable_autoscan={'Disable Automatic Analysis' in content}")
        return content

    def _org(self):
        try:
            return self._client.get_organization(settings.GITHUB_ORG_LOGIN)
        except GithubException as exc:
            raise GitHubManagerError(self._format_github_error(exc)) from exc

    def _repo(self, repository_name: str):
        try:
            return self._client.get_repo(f"{settings.GITHUB_ORG_LOGIN}/{repository_name}")
        except GithubException as exc:
            raise GitHubManagerError(self._format_github_error(exc)) from exc

    def _is_template_repository(self, repo) -> bool:
        raw_data = getattr(repo, "raw_data", None)
        if isinstance(raw_data, dict) and "is_template" in raw_data:
            return bool(raw_data["is_template"])

        value = getattr(repo, "is_template", None)
        if value is not None:
            return bool(value)

        return False

    def _format_github_error(self, exc: GithubException) -> str:
        data = exc.data if isinstance(exc.data, dict) else {}
        message = data.get("message") if data else None
        return message or str(exc)


github_manager = GitHubRepositoryManager()
