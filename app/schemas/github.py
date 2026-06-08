from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


RepositoryVisibility = Literal["private", "public", "internal"]
RepositoryLanguage = Literal["frontend", "springboot", "fastapi"]
CreationStatusValue = Literal["queued", "running", "succeeded", "failed"]


class TemplateResponse(BaseModel):
    name: str
    description: str | None = None
    private: bool
    url: str

    model_config = {
        "json_schema_extra": {
            "example": {
                "name": "fastapi-template",
                "description": "Template para APIs FastAPI",
                "private": True,
                "url": "https://github.com/Ouros-App/fastapi-template",
            }
        }
    }


class BareRepositoryCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=100, pattern=r"^[A-Za-z0-9_.-]+$")
    description: str | None = Field(default=None, max_length=350)
    visibility: RepositoryVisibility = "private"
    language: RepositoryLanguage = "fastapi"

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "name": "web-admin",
                    "description": "Frontend administrativo",
                    "visibility": "private",
                    "language": "frontend",
                },
                {
                    "name": "orders-api",
                    "description": "API de pedidos",
                    "visibility": "private",
                    "language": "springboot",
                },
                {
                    "name": "billing-api",
                    "description": "API de faturamento",
                    "visibility": "private",
                    "language": "fastapi",
                },
            ]
        }
    }


class TemplateRepositoryCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=100, pattern=r"^[A-Za-z0-9_.-]+$")
    template_name: str = Field(..., min_length=1, max_length=100, pattern=r"^[A-Za-z0-9_.-]+$")
    description: str | None = Field(default=None, max_length=350)
    visibility: RepositoryVisibility = "private"

    model_config = {
        "json_schema_extra": {
            "example": {
                "name": "billing-api",
                "template_name": "fastapi-template",
                "description": "API de faturamento",
                "visibility": "private",
            }
        }
    }


class RepositoryCreationResponse(BaseModel):
    creation_id: str
    status: CreationStatusValue
    repository: str
    message: str

    model_config = {
        "json_schema_extra": {
            "example": {
                "creation_id": "8ff5a88d-d2c4-4c27-9c2d-13e0a19599e1",
                "status": "queued",
                "repository": "Ouros-App/billing-api",
                "message": "Criacao de repositorio cru iniciada.",
            }
        }
    }


class RepositoryCreationStatusResponse(BaseModel):
    creation_id: str
    status: CreationStatusValue
    repository: str
    mode: Literal["bare", "template"]
    started_at: datetime
    finished_at: datetime | None = None
    steps: list[str] = Field(default_factory=list)
    error: str | None = None
    url: str | None = None

    model_config = {
        "json_schema_extra": {
            "example": {
                "creation_id": "8ff5a88d-d2c4-4c27-9c2d-13e0a19599e1",
                "status": "running",
                "repository": "Ouros-App/billing-api",
                "mode": "bare",
                "started_at": "2026-06-08T10:00:00Z",
                "finished_at": None,
                "steps": ["Criando repositorio cru", "Aplicando CI/CD"],
                "error": None,
                "url": None,
            }
        }
    }
