from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.api.routes import router
from app.core.config import settings

STATIC_DIR = Path(__file__).resolve().parent / "static"

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
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
