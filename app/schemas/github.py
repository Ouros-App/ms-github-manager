from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, model_validator

RepositoryVisibility = Literal["private", "public", "internal"]
RepositoryLanguage = Literal["generic", "frontend", "springboot", "fastapi", "android", "postgres"]
CreationStatusValue = Literal["queued", "running", "done", "failed"]


def _is_postgres_template(template_name: str) -> bool:
    normalized = template_name.lower()
    return "postgres" in normalized or "postgresql" in normalized


def _is_mongodb_template(template_name: str) -> bool:
    normalized = template_name.lower()
    return "mongodb" in normalized or "mongo" in normalized


def _validate_database_suffix(name: str) -> str:
    if not name.lower().endswith("-database"):
        raise ValueError("Repositorios PostgreSQL devem terminar com '-database'.")
    return name


class TemplateResponse(BaseModel):
    name: str
    description: str | None = None
    private: bool
    url: str

    model_config = {
        "json_schema_extra": {
            "example": {
                "name": "ms-fastapi-template",
                "description": "Template para APIs FastAPI",
                "private": True,
                "url": "https://github.com/Ouros-App/ms-fastapi-template",
            }
        }
    }


class BareRepositoryCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=100, pattern=r"^[A-Za-z0-9_.-]+$")
    description: str | None = Field(default=None, max_length=350)
    visibility: RepositoryVisibility = "private"
    language: RepositoryLanguage = "generic"

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "name": "shared-lib",
                    "description": "Repositorio cru com workflow generico",
                    "visibility": "private",
                    "language": "generic",
                },
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
                {
                    "name": "mobile-app",
                    "description": "Aplicativo Android",
                    "visibility": "private",
                    "language": "android",
                },
                {
                    "name": "db-migrations",
                    "description": "Repositorio de migracoes PostgreSQL",
                    "visibility": "private",
                    "language": "postgres",
                },
            ]
        }
    }

    @model_validator(mode="after")
    def validate_postgres_name(self) -> "BareRepositoryCreateRequest":
        if self.language == "postgres":
            _validate_database_suffix(self.name)
        return self


class PostgresConnection(BaseModel):
    host: str = Field(..., min_length=1, max_length=253)
    port: int = Field(default=5432, ge=1, le=65535)
    database: str = Field(..., min_length=1, max_length=63, pattern=r"^[A-Za-z0-9_]+$")
    user: str = Field(..., min_length=1, max_length=63, pattern=r"^[A-Za-z0-9_]+$")
    password: str = Field(..., min_length=1, max_length=256)
    root_database: str = Field(default="postgres", min_length=1, max_length=63, pattern=r"^[A-Za-z0-9_]+$")
    root_user: str = Field(..., min_length=1, max_length=63, pattern=r"^[A-Za-z0-9_]+$")
    root_password: str = Field(..., min_length=1, max_length=256)


class MongoConnection(BaseModel):
    host: str = Field(..., min_length=1, max_length=253)
    port: int = Field(default=27017, ge=1, le=65535)
    database: str = Field(..., min_length=1, max_length=63)
    user: str = Field(..., min_length=1, max_length=128)
    password: str = Field(..., min_length=1, max_length=256)
    auth_database: str = Field(default="admin", min_length=1, max_length=63)


class TemplateRepositoryCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=100, pattern=r"^[A-Za-z0-9_.-]+$")
    template_name: str = Field(..., min_length=1, max_length=100, pattern=r"^[A-Za-z0-9_.-]+$")
    description: str | None = Field(default=None, max_length=350)
    visibility: RepositoryVisibility = "private"
    postgres: PostgresConnection | None = None
    mongodb: MongoConnection | None = None

    model_config = {
        "json_schema_extra": {
            "example": {
                "name": "billing-api",
                "template_name": "ms-fastapi-template",
                "description": "API de faturamento",
                "visibility": "private",
            }
        }
    }

    @model_validator(mode="after")
    def validate_postgres_template_name(self) -> "TemplateRepositoryCreateRequest":
        if _is_postgres_template(self.template_name):
            _validate_database_suffix(self.name)
            if self.postgres is None:
                raise ValueError("Informe a conexao PostgreSQL para o template de banco.")
        if _is_mongodb_template(self.template_name):
            _validate_database_suffix(self.name)
            if self.mongodb is None:
                raise ValueError("Informe a conexao MongoDB para o template de banco.")
        return self


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
    current_step: str | None = None
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
                "current_step": "Aplicando CI/CD",
                "steps": ["Criando repositorio cru", "Aplicando CI/CD"],
                "error": None,
                "url": None,
            }
        }
    }
