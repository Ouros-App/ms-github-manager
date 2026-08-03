from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from app.api.routes import router
from app.core.auth import is_authenticated
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
app.state.settings = settings


@app.middleware("http")
async def require_session(request: Request, call_next):
    public = request.url.path in {"/health", "/ui", "/auth/login", "/auth/logout"} or request.url.path.startswith("/static/")
    if not public and not is_authenticated(request):
        return JSONResponse(status_code=401, content={"detail": "Autenticacao necessaria."})
    return await call_next(request)


@app.exception_handler(RequestValidationError)
async def request_validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
    errors = [{key: value for key, value in error.items() if key != "input"} for error in exc.errors()]
    return JSONResponse(status_code=422, content=jsonable_encoder({"detail": errors}))

app.include_router(router)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
