from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


RepositoryVisibility = Literal["private", "public", "internal"]
RepositoryLanguage = Literal["generic", "python", "fastapi", "node", "go"]
CreationStatusValue = Literal["queued", "running", "succeeded", "failed"]


class TemplateResponse(BaseModel):
    name: str
    description: str | None = None
    private: bool
    url: str


class BareRepositoryCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=100, pattern=r"^[A-Za-z0-9_.-]+$")
    description: str | None = Field(default=None, max_length=350)
    visibility: RepositoryVisibility = "private"
    language: RepositoryLanguage = "generic"


class TemplateRepositoryCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=100, pattern=r"^[A-Za-z0-9_.-]+$")
    template_name: str = Field(..., min_length=1, max_length=100, pattern=r"^[A-Za-z0-9_.-]+$")
    description: str | None = Field(default=None, max_length=350)
    visibility: RepositoryVisibility = "private"


class RepositoryCreationResponse(BaseModel):
    creation_id: str
    status: CreationStatusValue
    repository: str
    message: str


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
