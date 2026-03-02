"""
Configuracion centralizada via variables de entorno y Docker secrets.
- Finalidad: Centraliza todas las settings de la app (Glide API, OpenAI, PDF, CORS)
  en un unico punto. Prioridad: env var > Docker secret (/run/secrets/) > default.
- Consume: nada (solo stdlib os, pathlib)
- Consumido por: glide/client.py, llm_extractor.py, main.py, router.py
"""

import os
from functools import lru_cache
from pathlib import Path

SECRETS_DIR = Path("/run/secrets")


def _get_secret(env_name: str, secret_name: str, default: str = "") -> str:
    """Lee config con prioridad: env var > Docker secret > default."""
    value = os.getenv(env_name, "")
    if value:
        return value
    secret_path = SECRETS_DIR / secret_name
    if secret_path.is_file():
        return secret_path.read_text().strip()
    return default


class Settings:
    # Glide API
    GLIDE_APP_ID: str = _get_secret("GLIDE_APP_ID", "glide_app_id")
    GLIDE_API_TOKEN: str = _get_secret("GLIDE_API_TOKEN", "glide_api_token")

    # OpenAI
    OPENAI_API_KEY: str = _get_secret("OPENAI_API_KEY", "openai_api_key")
    OPENAI_MODEL: str = os.getenv("OPENAI_MODEL", "gpt-5-mini")
    OPENAI_MAX_TOKENS: int = int(os.getenv("OPENAI_MAX_TOKENS", "16000"))

    # PDF processing
    PDF_DPI: int = int(os.getenv("PDF_DPI", "200"))
    MAX_PDF_SIZE_MB: int = int(os.getenv("MAX_PDF_SIZE_MB", "50"))

    # App
    APP_TITLE: str = "ASME Pressure Vessel Extractor"
    APP_VERSION: str = "2.0.0"
    CORS_ORIGINS: list[str] = os.getenv("CORS_ORIGINS", "*").split(",")


@lru_cache
def get_settings() -> Settings:
    return Settings()
