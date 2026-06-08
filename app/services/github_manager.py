import asyncio
import base64
import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal

from app.core.config import settings
from app.schemas.github import (
    BareRepositoryCreateRequest,
    CreationStatusValue,
    RepositoryCreationStatusResponse,
    TemplateRepositoryCreateRequest,
    TemplateResponse,
)


class GitHubCliError(RuntimeError):
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
    def __init__(self) -> None:
        self._creations: dict[str, CreationState] = {}
        self._lock = asyncio.Lock()

    async def list_templates(self) -> list[TemplateResponse]:
        repos = await self._run_gh_json(
            "repo",
            "list",
            settings.GITHUB_ORG_LOGIN,
            "--limit",
            "200",
            "--json",
            "name,description,isPrivate,url",
        )

        return [
            TemplateResponse(
                name=repo["name"],
                description=repo.get("description"),
                private=repo["isPrivate"],
                url=repo["url"],
            )
            for repo in repos
            if repo["name"].endswith(settings.TEMPLATE_SUFFIX)
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
            repo = f"{settings.GITHUB_ORG_LOGIN}/{payload.name}"

            args = [
                "repo",
                "create",
                repo,
                self._visibility_flag(payload.visibility),
                "--add-readme",
                "--license",
                "mit",
            ]
            gitignore_template = self._gitignore_template(payload.language)
            if gitignore_template is not None:
                args.extend(["--gitignore", gitignore_template])
            if payload.description:
                args.extend(["--description", payload.description])

            await self._step(creation_id, "Criando repositorio cru")
            await self._run_gh(*args)

            if gitignore_template is None:
                await self._step(creation_id, "Criando .gitignore generico")
                await self._put_file(
                    payload.name,
                    ".gitignore",
                    self._generic_gitignore(),
                    "Add generic gitignore",
                )

            if payload.language == "fastapi":
                await self._step(creation_id, "Aplicando CI/CD FastAPI")
                await self._put_fastapi_workflow(payload.name)

            await self._step(creation_id, "Aplicando protecao da branch main")
            await self._protect_main_branch(payload.name)
            await self._mark_succeeded(creation_id, f"https://github.com/{repo}")
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

            repo = f"{settings.GITHUB_ORG_LOGIN}/{payload.name}"
            template = f"{settings.GITHUB_ORG_LOGIN}/{payload.template_name}"
            args = [
                "repo",
                "create",
                repo,
                self._visibility_flag(payload.visibility),
                "--template",
                template,
            ]
            if payload.description:
                args.extend(["--description", payload.description])

            await self._step(creation_id, "Criando repositorio a partir do template")
            await self._run_gh(*args)

            if self._is_fastapi_template(payload.template_name):
                await self._step(creation_id, "Aplicando CI/CD FastAPI")
                await self._put_fastapi_workflow(payload.name)

            await self._step(creation_id, "Aplicando protecao da branch main")
            await self._protect_main_branch(payload.name)
            await self._mark_succeeded(creation_id, f"https://github.com/{repo}")
        except Exception as exc:
            await self._mark_failed(creation_id, str(exc))

    async def _assert_template_exists(self, template_name: str) -> None:
        templates = await self.list_templates()
        if template_name not in {template.name for template in templates}:
            raise ValueError(
                f"Template '{template_name}' nao encontrado em {settings.GITHUB_ORG_LOGIN} "
                f"com sufixo '{settings.TEMPLATE_SUFFIX}'."
            )

    async def _put_fastapi_workflow(self, repository_name: str) -> None:
        await self._put_file(
            repository_name,
            ".github/workflows/ci-cd.yml",
            self._fastapi_workflow(),
            "Configure FastAPI CI/CD",
        )

    async def _put_file(
        self,
        repository_name: str,
        path: str,
        content: str,
        message: str,
    ) -> None:
        existing = await self._get_file_metadata(repository_name, path)
        payload = {
            "message": message,
            "content": base64.b64encode(content.encode("utf-8")).decode("ascii"),
            "branch": settings.DEFAULT_BRANCH,
        }
        if existing is not None and existing.get("sha"):
            payload["sha"] = existing["sha"]

        await self._run_gh(
            "api",
            "--method",
            "PUT",
            f"repos/{settings.GITHUB_ORG_LOGIN}/{repository_name}/contents/{path}",
            "--input",
            "-",
            input_data=json.dumps(payload),
        )

    async def _get_file_metadata(self, repository_name: str, path: str) -> dict[str, Any] | None:
        try:
            return await self._run_gh_json(
                "api",
                "--method",
                "GET",
                f"repos/{settings.GITHUB_ORG_LOGIN}/{repository_name}/contents/{path}",
                "-f",
                f"ref={settings.DEFAULT_BRANCH}",
            )
        except GitHubCliError:
            return None

    async def _protect_main_branch(self, repository_name: str) -> None:
        protection_payload = {
            "required_status_checks": {
                "strict": True,
                "contexts": ["ci"],
            },
            "enforce_admins": True,
            "required_pull_request_reviews": {
                "required_approving_review_count": 1,
                "dismiss_stale_reviews": True,
                "require_code_owner_reviews": False,
            },
            "restrictions": None,
            "required_linear_history": True,
            "allow_force_pushes": False,
            "allow_deletions": False,
        }
        await self._run_gh(
            "api",
            "--method",
            "PUT",
            f"repos/{settings.GITHUB_ORG_LOGIN}/{repository_name}/branches/{settings.DEFAULT_BRANCH}/protection",
            "--input",
            "-",
            input_data=json.dumps(protection_payload),
        )

    async def _run_gh_json(self, *args: str, input_data: str | None = None) -> Any:
        output = await self._run_gh(*args, input_data=input_data)
        return json.loads(output)

    async def _run_gh(self, *args: str, input_data: str | None = None) -> str:
        process = await asyncio.create_subprocess_exec(
            "gh",
            *args,
            stdin=asyncio.subprocess.PIPE if input_data is not None else None,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        try:
            stdout, stderr = await asyncio.wait_for(
                process.communicate(input_data.encode("utf-8") if input_data is not None else None),
                timeout=settings.GH_TIMEOUT_SECONDS,
            )
        except asyncio.TimeoutError as exc:
            process.kill()
            await process.wait()
            raise GitHubCliError(f"gh {' '.join(args)} excedeu o timeout") from exc

        if process.returncode != 0:
            error = stderr.decode("utf-8").strip() or stdout.decode("utf-8").strip()
            raise GitHubCliError(f"gh {' '.join(args)} falhou: {error}")

        return stdout.decode("utf-8")

    async def _mark_running(self, creation_id: str) -> None:
        async with self._lock:
            self._creations[creation_id].status = "running"

    async def _mark_succeeded(self, creation_id: str, url: str) -> None:
        async with self._lock:
            state = self._creations[creation_id]
            state.status = "succeeded"
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
            steps=state.steps,
            error=state.error,
            url=state.url,
        )

    def _visibility_flag(self, visibility: str) -> str:
        return f"--{visibility}"

    def _gitignore_template(self, language: str) -> str | None:
        templates = {
            "python": "Python",
            "fastapi": "Python",
            "node": "Node",
            "go": "Go",
        }
        return templates.get(language)

    def _is_fastapi_template(self, template_name: str) -> bool:
        return "fastapi" in template_name.lower()

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

    def _fastapi_workflow(self) -> str:
        return """name: CI/CD

on:
  pull_request:
    branches:
      - main
  push:
    branches:
      - main

jobs:
  ci:
    name: ci
    runs-on: ubuntu-latest

    steps:
      - name: Checkout
        uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.12"

      - name: Install dependencies
        run: |
          python -m pip install --upgrade pip
          if [ -f requirements.txt ]; then pip install -r requirements.txt; fi
          pip install ruff pytest

      - name: Lint
        run: ruff check .

      - name: Test
        run: pytest

  deploy:
    name: deploy
    runs-on: ubuntu-latest
    needs: ci
    if: github.ref == 'refs/heads/main' && github.event_name == 'push'
    steps:
      - name: Checkout
        uses: actions/checkout@v4

      - name: Deploy
        run: echo "Configure o deploy deste repositorio."
"""


github_manager = GitHubRepositoryManager()
