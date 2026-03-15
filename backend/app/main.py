"""
Punto de entrada de la aplicacion FastAPI (API-only, sin frontend).
- Finalidad: Configura app, registra routers, maneja lifecycle.
  GET / redirige a /docs. GET /health (sin prefijo, sin auth) para monitoreo externo.
- Consume: config.py (settings), features/extraction/router.py (endpoints API)
- Consumido por: Dockerfile (uvicorn app.main:app), docker-compose
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse
from starlette.middleware.base import BaseHTTPMiddleware

from app.config import get_settings
from app.features.extraction.router import router as extraction_router

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)
settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("ASME Extractor v%s starting...", settings.APP_VERSION)
    yield
    logger.info("Shutting down")


app = FastAPI(
    title=settings.APP_TITLE,
    version=settings.APP_VERSION,
    lifespan=lifespan,
)


class RequestLogMiddleware(BaseHTTPMiddleware):
    """Loguea cada request entrante con metodo, path y status de respuesta."""

    async def dispatch(self, request: Request, call_next):
        logger.info(
            ">> %s %s [client=%s, content-type=%s]",
            request.method,
            request.url.path,
            request.client.host if request.client else "unknown",
            request.headers.get("content-type", "none"),
        )
        response = await call_next(request)
        logger.info(
            "<< %s %s → %d",
            request.method,
            request.url.path,
            response.status_code,
        )
        return response


app.add_middleware(RequestLogMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(RequestValidationError)
async def validation_error_handler(request: Request, exc: RequestValidationError):
    """Loguea errores 422 con el body recibido para diagnostico."""
    body = None
    try:
        body = await request.body()
        body = body.decode("utf-8")[:500]
    except Exception:
        body = "<no se pudo leer>"

    errors = []
    for err in exc.errors():
        clean = {k: v for k, v in err.items() if k != "input"}
        clean["input"] = str(err.get("input", ""))[:200]
        errors.append(clean)

    logger.error(
        "422 Validation Error en %s %s — body=%s — errors=%s",
        request.method,
        request.url.path,
        body,
        errors,
    )
    return JSONResponse(
        status_code=422,
        content={"detail": errors},
    )


app.include_router(extraction_router)


@app.get("/health")
async def health_check():
    """Health check publico, sin auth. Para Traefik, Cloudflare, load balancers, monitors."""
    return {"status": "ok", "version": settings.APP_VERSION}


@app.get("/")
async def root_redirect():
    """Redirige a la documentacion Swagger de la API."""
    return RedirectResponse(url="/docs")
