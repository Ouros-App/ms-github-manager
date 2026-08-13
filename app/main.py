import time
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from app.api.routes import router
from app.core.auth import is_authenticated
from app.core.config import settings
from app.core.metrics import REQUEST_COUNT, REQUEST_DURATION

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
    started = time.perf_counter()
    response = None
    try:
        public = request.url.path in {"/health", "/ui", "/auth/login", "/auth/logout", "/auth/session"} or request.url.path.startswith("/static/")
        if request.url.path == "/metrics":
            token = settings.METRICS_TOKEN
            if not token or request.headers.get("Authorization") != f"Bearer {token}":
                response = JSONResponse(status_code=401, content={"detail": "Metricas nao autorizadas."})
                return response
            return await call_next(request)
        if not public and not is_authenticated(request):
            response = JSONResponse(status_code=401, content={"detail": "Autenticacao necessaria."})
            return response
        response = await call_next(request)
        return response
    finally:
        route = getattr(request.scope.get("route"), "path", "unmatched")
        status_code = str(response.status_code if response else 500)
        REQUEST_COUNT.labels(request.method, route, status_code).inc()
        REQUEST_DURATION.labels(request.method, route).observe(time.perf_counter() - started)


@app.exception_handler(RequestValidationError)
async def request_validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
    errors = [{key: value for key, value in error.items() if key != "input"} for error in exc.errors()]
    return JSONResponse(status_code=422, content=jsonable_encoder({"detail": errors}))

app.include_router(router)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
