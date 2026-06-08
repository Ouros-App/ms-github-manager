from fastapi import FastAPI

from app.api.routes import router
from app.core.config import settings

app = FastAPI(
    title=settings.PROJECT_NAME,
    description=settings.DESCRIPTION,
    version=settings.VERSION,
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
    swagger_ui_parameters={
        "defaultModelsExpandDepth": 1,
        "displayRequestDuration": True,
        "docExpansion": "list",
    },
    openapi_tags=[
        {"name": "Health", "description": "Status basico da API."},
        {"name": "Templates", "description": "Consulta de repositorios template da organizacao."},
        {"name": "Repositories", "description": "Criacao e acompanhamento de repositorios GitHub."},
    ],
)

app.include_router(router)
