import os

from dotenv import load_dotenv


load_dotenv()


class Settings:
    PROJECT_NAME = os.getenv("PROJECT_NAME", "Ouros GitHub Repository Manager")
    DESCRIPTION = os.getenv(
        "PROJECT_DESCRIPTION",
        "API para criar e gerenciar repositorios da organizacao Ouros App no GitHub.",
    )
    VERSION = "0.1.0"
    GITHUB_ORG_LOGIN = os.getenv("GITHUB_ORG_LOGIN", "Ouros-App")
    GH_TOKEN = os.getenv("GH_TOKEN") or os.getenv("GITHUB_TOKEN")
    TEMPLATE_SUFFIX = os.getenv("TEMPLATE_SUFFIX", "-template")
    DEFAULT_BRANCH = os.getenv("DEFAULT_BRANCH", "main")
    GH_TIMEOUT_SECONDS = int(os.getenv("GH_TIMEOUT_SECONDS", "120"))


settings = Settings()
