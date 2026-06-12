import asyncio
import re
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from github import Auth, Github
from github.GithubException import GithubException, UnknownObjectException

from app.core.config import settings
from app.schemas.github import (
    BareRepositoryCreateRequest,
    CreationStatusValue,
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
            await self._step(creation_id, "Configurando SonarCloud")
            await asyncio.to_thread(self._put_sonar_secret_sync, repo.name)

            if payload.language == "springboot":
                await self._step(creation_id, "Aplicando estrutura Spring REST")
                await asyncio.to_thread(self._put_springboot_scaffold_sync, repo.name)

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
            await asyncio.to_thread(self._protect_main_branch_sync, repo.name)
            await self._mark_succeeded(creation_id, repo.html_url)
        except Exception as exc:
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
            await self._step(creation_id, "Configurando SonarCloud")
            await asyncio.to_thread(self._put_sonar_secret_sync, repo.name)

            if self._template_language(payload.template_name) == "springboot":
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

            await self._step(creation_id, "Aplicando CI/CD")
            await asyncio.to_thread(
                self._put_workflow_sync,
                repo.name,
                self._template_language(payload.template_name),
            )

            await self._step(creation_id, "Aplicando protecao da branch main")
            await asyncio.to_thread(self._protect_main_branch_sync, repo.name)
            await self._mark_succeeded(creation_id, repo.html_url)
        except Exception as exc:
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
            "description": payload.description or "",
            "private": payload.visibility == "private",
            "auto_init": True,
            "license_template": "mit",
        }
        if payload.visibility != "private":
            kwargs["visibility"] = payload.visibility
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
                    "description": payload.description or "",
                    "private": payload.visibility == "private",
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
        self._put_file_sync(
            repository_name,
            ".github/workflows/ci-cd.yml",
            self._workflow(language),
            "Configure CI/CD",
        )

    def _put_springboot_scaffold_sync(self, repository_name: str) -> None:
        application_name = self._springboot_application_name(repository_name)
        package_name = self._springboot_package_name(repository_name)
        package_path = package_name.replace(".", "/")
        application_class_name = self._springboot_application_class_name(repository_name)
        files = {
            "README.md": (
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
            "src/main/resources/application-local.properties": self._springboot_application_local_properties(
                application_name
            ),
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

    def _springboot_application_local_properties(self, application_name: str) -> str:
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
        normalized = re.sub(r"[-_.]?template$", "", normalized)
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

    def _put_sonar_secret_sync(self, repository_name: str) -> None:
        if not settings.SONAR_CLOUD_TOKEN:
            return
        repo = self._repo(repository_name)
        try:
            repo.create_secret("SONAR_TOKEN", settings.SONAR_CLOUD_TOKEN)
        except GithubException as exc:
            raise GitHubManagerError(self._format_github_error(exc)) from exc

    def _put_file_sync(
        self,
        repository_name: str,
        path: str,
        content: str,
        message: str,
    ) -> None:
        repo = self._repo(repository_name)
        try:
            existing = repo.get_contents(path, ref=settings.DEFAULT_BRANCH)
            repo.update_file(
                path=path,
                message=message,
                content=content,
                sha=existing.sha,
                branch=settings.DEFAULT_BRANCH,
            )
        except UnknownObjectException:
            try:
                repo.create_file(
                    path=path,
                    message=message,
                    content=content,
                    branch=settings.DEFAULT_BRANCH,
                )
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

    def _protect_main_branch_sync(self, repository_name: str) -> None:
        repo = self._repo(repository_name)
        try:
            branch = repo.get_branch(settings.DEFAULT_BRANCH)
            branch.edit_protection(
                strict=True,
                contexts=["ci", "conventional-commits", "sonarcloud", "codeql"],
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
        }
        return templates.get(language)

    def _template_language(self, template_name: str) -> str:
        normalized_name = template_name.lower()
        if (
            "frontend" in normalized_name
            or "react" in normalized_name
            or "vite" in normalized_name
            or "typescript" in normalized_name
        ):
            return "frontend"
        if "spring" in normalized_name or "java" in normalized_name:
            return "springboot"
        if "fastapi" in normalized_name:
            return "fastapi"
        return "generic"

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
            workflow_path = self._WORKFLOW_DIR / "generic.yml"
        return workflow_path.read_text(encoding="utf-8").replace(
            "__GITHUB_ORG_LOGIN__",
            settings.GITHUB_ORG_LOGIN,
        )

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
