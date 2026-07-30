import pytest
from pydantic import ValidationError

from app.schemas.github import (
    BareRepositoryCreateRequest,
    TemplateRepositoryCreateRequest,
)


def test_postgres_repository_requires_database_suffix():
    with pytest.raises(ValidationError, match="terminar com '-database'"):
        BareRepositoryCreateRequest(name="orders", language="postgres")


def test_postgres_repository_accepts_database_suffix():
    request = BareRepositoryCreateRequest(name="orders-database", language="postgres")
    assert request.name == "orders-database"


def test_postgres_template_requires_database_suffix():
    with pytest.raises(ValidationError, match="terminar com '-database'"):
        TemplateRepositoryCreateRequest(name="orders", template_name="ms-postgres-template")


def test_non_postgres_template_allows_regular_name():
    request = TemplateRepositoryCreateRequest(name="orders", template_name="ms-fastapi-template")
    assert request.name == "orders"
