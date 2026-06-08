from fastapi import APIRouter, HTTPException, status

from app.schemas.common import HealthResponse, MessageResponse
from app.schemas.github import (
    BareRepositoryCreateRequest,
    RepositoryCreationResponse,
    RepositoryCreationStatusResponse,
    TemplateRepositoryCreateRequest,
    TemplateResponse,
)
from app.services.github_manager import GitHubCliError, github_manager

router = APIRouter()


@router.get(
    "/",
    response_model=MessageResponse,
    tags=["Health"],
    summary="Status da aplicacao",
)
async def read_root() -> MessageResponse:
    return MessageResponse(message="Ouros GitHub Repository Manager is running")


@router.get(
    "/health",
    response_model=HealthResponse,
    tags=["Health"],
    summary="Health check",
)
async def health_check() -> HealthResponse:
    return HealthResponse(status="ok")


@router.get(
    "/templates",
    response_model=list[TemplateResponse],
    tags=["Templates"],
    summary="Listar templates",
)
async def list_templates() -> list[TemplateResponse]:
    try:
        return await github_manager.list_templates()
    except GitHubCliError as exc:
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
