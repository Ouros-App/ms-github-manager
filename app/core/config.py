import os
from contextvars import ContextVar, Token

from dotenv import load_dotenv


load_dotenv()


class Settings:
    def __init__(self, values: dict[str, object] | None = None) -> None:
        values = values or {}
        self.PROJECT_NAME = str(
            values.get("PROJECT_NAME", os.getenv("PROJECT_NAME", "Ouros GitHub Repository Manager"))
        )
        self.DESCRIPTION = str(
            values.get(
                "PROJECT_DESCRIPTION",
                os.getenv("PROJECT_DESCRIPTION", "API para criar e gerenciar repositorios da organizacao Ouros App no GitHub."),
            )
        )
        self.VERSION = str(values.get("VERSION", os.getenv("VERSION", "0.1.0")))
        self.GITHUB_ORG_LOGIN = str(values.get("GITHUB_ORG_LOGIN", os.getenv("GITHUB_ORG_LOGIN", "Ouros-App")))
        self.GH_TOKEN = values.get("GH_TOKEN") or values.get("GITHUB_TOKEN") or os.getenv("GH_TOKEN") or os.getenv("GITHUB_TOKEN")
        self.SONAR_CLOUD_TOKEN = (
            values.get("SONAR_CLOUD_TOKEN")
            or values.get("sonar_cloud_token")
            or os.getenv("SONAR_CLOUD_TOKEN")
            or os.getenv("sonar_cloud_token")
        )
        self.TEMPLATE_SUFFIX = str(values.get("TEMPLATE_SUFFIX", os.getenv("TEMPLATE_SUFFIX", "-template")))
        self.DEFAULT_BRANCH = str(values.get("DEFAULT_BRANCH", os.getenv("DEFAULT_BRANCH", "main")))
        self.GH_TIMEOUT_SECONDS = int(values.get("GH_TIMEOUT_SECONDS", os.getenv("GH_TIMEOUT_SECONDS", "120")))


_local_settings = Settings()

_request_settings: ContextVar[Settings | None] = ContextVar("request_settings", default=None)


def get_settings() -> Settings:
    return _request_settings.get() or _local_settings


def set_worker_settings(env: object) -> Token[Settings | None]:
    names = (
        "PROJECT_NAME", "PROJECT_DESCRIPTION", "VERSION", "GITHUB_ORG_LOGIN", "GH_TOKEN",
        "GITHUB_TOKEN", "SONAR_CLOUD_TOKEN", "sonar_cloud_token", "TEMPLATE_SUFFIX",
        "DEFAULT_BRANCH", "GH_TIMEOUT_SECONDS",
    )
    values = {}
    for name in names:
        try:
            value = getattr(env, name)
        except AttributeError:
            try:
                value = env[name]
            except (KeyError, TypeError):
                continue
        if value is not None:
            values[name] = value
    return _request_settings.set(Settings(values))


def reset_worker_settings(token: Token[Settings | None]) -> None:
    _request_settings.reset(token)


class SettingsProxy:
    def __getattr__(self, name: str) -> object:
        return getattr(get_settings(), name)


settings = SettingsProxy()
