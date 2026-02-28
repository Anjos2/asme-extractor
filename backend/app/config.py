"""
Configuracion centralizada via variables de entorno.
- Finalidad: Centraliza todas las settings de la app (DB, OpenAI, PDF, CORS)
  en un unico punto, leyendo de env vars con defaults seguros.
- Consume: nada (solo stdlib os)
- Consumido por: database.py, llm_extractor.py, main.py, router.py
"""

import os
from functools import lru_cache


class Settings:
    # Database
    DATABASE_URL: str = os.getenv(
        "DATABASE_URL",
        "postgresql+asyncpg://asme_user:asme_pass@localhost:5432/asme_db",
    )

    # OpenAI
    OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")
    OPENAI_MODEL: str = os.getenv("OPENAI_MODEL", "gpt-5-mini")
    OPENAI_MAX_TOKENS: int = int(os.getenv("OPENAI_MAX_TOKENS", "16000"))

    # PDF processing
    PDF_DPI: int = int(os.getenv("PDF_DPI", "200"))
    MAX_PDF_SIZE_MB: int = int(os.getenv("MAX_PDF_SIZE_MB", "50"))

    # App
    APP_TITLE: str = "ASME Pressure Vessel Extractor"
    APP_VERSION: str = "1.0.0"
    CORS_ORIGINS: list[str] = os.getenv("CORS_ORIGINS", "*").split(",")


@lru_cache
def get_settings() -> Settings:
    return Settings()
