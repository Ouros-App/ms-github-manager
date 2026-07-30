import os
from contextvars import ContextVar

from dotenv import load_dotenv


load_dotenv()


class Settings:
    PROJECT_NAME = os.getenv("PROJECT_NAME", "Ouros GitHub Repository Manager")
    DESCRIPTION = os.getenv(
        "PROJECT_DESCRIPTION",
        "API para criar e gerenciar repositorios da organizacao Ouros App no GitHub.",
    )
    VERSION = os.getenv("VERSION", "0.1.0")
    GITHUB_ORG_LOGIN = os.getenv("GITHUB_ORG_LOGIN", "Ouros-App")
    GH_TOKEN = os.getenv("GH_TOKEN") or os.getenv("GITHUB_TOKEN")
    SONAR_CLOUD_TOKEN = os.getenv("SONAR_CLOUD_TOKEN") or os.getenv("sonar_cloud_token")
    TEMPLATE_SUFFIX = os.getenv("TEMPLATE_SUFFIX", "-template")
    DEFAULT_BRANCH = os.getenv("DEFAULT_BRANCH", "main")
    GH_TIMEOUT_SECONDS = int(os.getenv("GH_TIMEOUT_SECONDS", "120"))


settings = Settings()

_request_settings: ContextVar[Settings | None] = ContextVar("request_settings", default=None)


def get_settings() -> Settings:
    return _request_settings.get() or settings


def set_worker_settings(env) -> None:
    values = {name: getattr(env, name) for name in dir(env) if name.isupper() and hasattr(env, name)}
    current = Settings()
    for name, value in values.items():
        if hasattr(current, name) and value is not None:
            setattr(current, name, value)
    _request_settings.set(current)
