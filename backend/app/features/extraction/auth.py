"""
Middleware de autenticacion via API Key para proteger endpoints.
- Finalidad: Valida header X-API-Key en cada request contra ASME_API_KEY.
  Si ASME_API_KEY no esta configurada (dev local), permite todo (bypass).
- Consume: config.py (get_settings → ASME_API_KEY)
- Consumido por: router.py (como Depends() del APIRouter)
"""

import logging

from fastapi import HTTPException, Security
from fastapi.security import APIKeyHeader

from app.config import get_settings

logger = logging.getLogger(__name__)

_api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


async def verify_api_key(api_key: str | None = Security(_api_key_header)) -> None:
    """Valida API key del header X-API-Key.

    - Si ASME_API_KEY no esta configurada (vacio) → bypass (dev local).
    - Si el header falta o no coincide → HTTP 401.
    """
    settings = get_settings()

    if not settings.ASME_API_KEY:
        return

    if not api_key:
        raise HTTPException(status_code=401, detail="API key requerida (header X-API-Key)")

    if api_key != settings.ASME_API_KEY:
        logger.warning("API key invalida recibida")
        raise HTTPException(status_code=401, detail="API key invalida")
