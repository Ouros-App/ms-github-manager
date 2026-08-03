from pathlib import Path

from fastapi import APIRouter, HTTPException, Request, Response, status
from fastapi.responses import FileResponse, RedirectResponse

from app.core.auth import create_session, is_authenticated, login_allowed
from app.core.config import settings
from app.schemas.common import HealthResponse, LoginRequest, MessageResponse
from app.schemas.github import (
    BareRepositoryCreateRequest,
    RepositoryCreationResponse,
    RepositoryCreationStatusResponse,
    TemplateRepositoryCreateRequest,
    TemplateResponse,
)
from app.services.github_manager import GitHubManagerError, github_manager

router = APIRouter()
STATIC_DIR = Path(__file__).resolve().parents[1] / "static"


@router.post("/auth/login", response_model=MessageResponse, tags=["Auth"])
async def login(payload: LoginRequest, request: Request, response: Response) -> MessageResponse:
    settings = request.app.state.settings
    if not login_allowed(request.client.host if request.client else "unknown"):
        raise HTTPException(status_code=429, detail="Muitas tentativas. Tente novamente em um minuto.")
    if not settings.AUTH_PASSWORD or not settings.SESSION_SECRET or payload.username != settings.AUTH_USERNAME or payload.password != settings.AUTH_PASSWORD:
        raise HTTPException(status_code=401, detail="Credenciais invalidas.")
    response.set_cookie("session", create_session(settings.SESSION_SECRET, settings.SESSION_TTL_SECONDS), httponly=True, secure=settings.AUTH_COOKIE_SECURE, samesite="lax", max_age=settings.SESSION_TTL_SECONDS)
    return MessageResponse(message="Login realizado.")


@router.get("/auth/session", response_model=MessageResponse, tags=["Auth"])
async def session_status(request: Request) -> MessageResponse:
    if not is_authenticated(request):
        raise HTTPException(status_code=401, detail="Sessao invalida.")
    return MessageResponse(message="Sessao valida.")


@router.post("/auth/logout", response_model=MessageResponse, tags=["Auth"])
async def logout(response: Response) -> MessageResponse:
    response.delete_cookie("session")
    return MessageResponse(message="Logout realizado.")


@router.get(
    "/",
    response_model=MessageResponse,
    tags=["Health"],
    summary="Status da aplicacao",
)
async def read_root() -> MessageResponse:
    return MessageResponse(message="Ouros GitHub Repository Manager is running")


@router.get(
    "/ui",
    include_in_schema=False,
)
async def read_ui() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@router.get(
    "/app",
    include_in_schema=False,
)
async def read_app() -> RedirectResponse:
    return RedirectResponse(url="/ui", status_code=status.HTTP_307_TEMPORARY_REDIRECT)


@router.get(
    "/health",
    response_model=HealthResponse,
    tags=["Health"],
    summary="Health check",
)
async def health_check() -> HealthResponse:
    return HealthResponse(
        status="ok",
        service=settings.PROJECT_NAME,
        version=settings.VERSION,
        organization=settings.GITHUB_ORG_LOGIN,
        default_branch=settings.DEFAULT_BRANCH,
    )


@router.get(
    "/templates",
    response_model=list[TemplateResponse],
    tags=["Templates"],
    summary="Listar templates",
)
async def list_templates() -> list[TemplateResponse]:
    try:
        return await github_manager.list_templates()
    except GitHubManagerError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(exc),
        ) from exc


@router.post(
    "/repositories/bare",
    response_model=RepositoryCreationResponse,
    status_code=status.HTTP_202_ACCEPTED,
    tags=["Repositories"],
    summary="Criar repositorio cru",
)
async def create_bare_repository(
    payload: BareRepositoryCreateRequest,
) -> RepositoryCreationResponse:
    state = await github_manager.start_bare_creation(payload)
    return RepositoryCreationResponse(
        creation_id=state.creation_id,
        status=state.status,
        repository=state.repository,
        message="Criacao de repositorio cru iniciada.",
    )


@router.post(
    "/repositories/from-template",
    response_model=RepositoryCreationResponse,
    status_code=status.HTTP_202_ACCEPTED,
    tags=["Repositories"],
    summary="Criar repositorio a partir de template",
)
async def create_repository_from_template(
    payload: TemplateRepositoryCreateRequest,
) -> RepositoryCreationResponse:
    state = await github_manager.start_template_creation(payload)
    return RepositoryCreationResponse(
        creation_id=state.creation_id,
        status=state.status,
        repository=state.repository,
        message="Criacao de repositorio a partir de template iniciada.",
    )


@router.get(
    "/repositories/creations/{creation_id}",
    response_model=RepositoryCreationStatusResponse,
    tags=["Repositories"],
    summary="Consultar status de criacao",
)
async def get_repository_creation_status(
    creation_id: str,
) -> RepositoryCreationStatusResponse:
    creation = await github_manager.get_creation_status(creation_id)
    if creation is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Criacao nao encontrada.",
        )
    return creation
