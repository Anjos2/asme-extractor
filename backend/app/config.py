"""
Configuracion centralizada via variables de entorno.
- Finalidad: Centraliza todas las settings de la app (Glide API, OpenAI, PDF, CORS)
  en un unico punto, leyendo de env vars con defaults seguros.
- Consume: nada (solo stdlib os)
- Consumido por: glide/client.py, llm_extractor.py, main.py, router.py
"""

import os
from functools import lru_cache


class Settings:
    # Glide API
    GLIDE_APP_ID: str = os.getenv("GLIDE_APP_ID", "")
    GLIDE_API_TOKEN: str = os.getenv("GLIDE_API_TOKEN", "")

    # OpenAI
    OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")
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
