"""
Endpoints API para extraccion ASME, guardado en Glide y gestion de tanques.
- Finalidad: Capa HTTP que recibe requests y delega a service.py y glide/repository.py.
  Endpoints: /extract, /extract-url, /save, /tanques, /tanques/{serie}/check, /batch/process.
  Todos protegidos con API key via auth.py.
- Consume: service.py (extract, save, check), schemas.py (request/response),
  validators.py (PDFTypeError), config.py (MAX_PDF_SIZE_MB), auth.py (verify_api_key),
  glide/repository.py (list, batch)
- Consumido por: main.py (registro de router)
"""

import logging
from urllib.parse import urlparse

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile

from app.config import get_settings
from app.features.extraction.auth import verify_api_key
from app.features.extraction.service import (
    check_duplicate,
    extract_from_pdf,
    save_to_glide,
)
from app.features.extraction.validators import PDFTypeError
from app.features.glide.repository import (
    get_documentos_by_tanque,
    get_tanques_sin_libro_digital,
    list_tanques,
)
from app.schemas import (
    DuplicateCheckResponse,
    ExtractUrlRequest,
    ExtractionResponse,
    SaveRequest,
    SaveResponse,
    TanqueResponse,
)

logger = logging.getLogger(__name__)
settings = get_settings()
router = APIRouter(
    prefix="/api",
    tags=["extraction"],
    dependencies=[Depends(verify_api_key)],
)


@router.post("/extract", response_model=ExtractionResponse)
async def extract_pdf(file: UploadFile):
    """Sube un PDF, auto-detecta tipo y extrae datos con Vision AI. NO guarda."""
    logger.info("POST /extract — filename=%s, content_type=%s", file.filename, file.content_type)

    if not file.filename or not file.filename.lower().endswith(".pdf"):
        logger.warning("POST /extract rechazado: archivo no es PDF (%s)", file.filename)
        raise HTTPException(400, "Solo se aceptan archivos PDF")

    pdf_bytes = await file.read()
    max_size = settings.MAX_PDF_SIZE_MB * 1024 * 1024
    logger.info("POST /extract — PDF size=%d bytes (max=%d)", len(pdf_bytes), max_size)

    if len(pdf_bytes) > max_size:
        logger.warning("POST /extract rechazado: PDF excede limite (%d > %d)", len(pdf_bytes), max_size)
        raise HTTPException(400, f"PDF excede {settings.MAX_PDF_SIZE_MB}MB")

    try:
        result = await extract_from_pdf(pdf_bytes=pdf_bytes, filename=file.filename)
    except PDFTypeError as e:
        logger.error("POST /extract PDFTypeError: %s", e)
        raise HTTPException(422, str(e))
    except ValueError as e:
        logger.error("POST /extract ValueError: %s", e)
        raise HTTPException(422, str(e))
    except RuntimeError as e:
        logger.error("POST /extract RuntimeError: %s", e)
        raise HTTPException(500, str(e))

    logger.info("POST /extract OK — type=%s, serie=%s", result.get("pdf_type"), result.get("extraction", {}).get("serial_number"))
    return ExtractionResponse(**result)


@router.post("/extract-url", response_model=ExtractionResponse)
async def extract_pdf_from_url(request: ExtractUrlRequest, raw_request: Request):
    """Descarga un PDF desde una URL, auto-detecta tipo y extrae datos. NO guarda.

    Pensado para integracion con Glide: el usuario sube PDF en Glide,
    Glide envia la URL a esta API, la API descarga y procesa.
    """
    logger.info(
        "POST /extract-url — pdf_url=%s, filename=%s, content_type=%s",
        request.pdf_url, request.filename, raw_request.headers.get("content-type"),
    )
    max_size = settings.MAX_PDF_SIZE_MB * 1024 * 1024

    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.get(request.pdf_url)
            response.raise_for_status()
    except httpx.TimeoutException:
        logger.error("POST /extract-url timeout descargando %s", request.pdf_url)
        raise HTTPException(504, "Timeout descargando PDF (60s)")
    except httpx.HTTPStatusError as e:
        logger.error("POST /extract-url HTTP error %d descargando %s", e.response.status_code, request.pdf_url)
        raise HTTPException(502, f"Error descargando PDF: HTTP {e.response.status_code}")
    except httpx.RequestError as e:
        logger.error("POST /extract-url conexion error: %s", e)
        raise HTTPException(502, f"Error de conexion descargando PDF: {e}")

    pdf_bytes = response.content
    logger.info("POST /extract-url — PDF descargado: %d bytes", len(pdf_bytes))

    if len(pdf_bytes) > max_size:
        logger.warning("POST /extract-url rechazado: PDF excede limite (%d > %d)", len(pdf_bytes), max_size)
        raise HTTPException(400, f"PDF excede {settings.MAX_PDF_SIZE_MB}MB")

    filename = request.filename
    if not filename:
        path = urlparse(request.pdf_url).path
        filename = path.rsplit("/", 1)[-1] if "/" in path else "document.pdf"
        if not filename.lower().endswith(".pdf"):
            filename += ".pdf"

    try:
        result = await extract_from_pdf(pdf_bytes=pdf_bytes, filename=filename)
    except PDFTypeError as e:
        logger.error("POST /extract-url PDFTypeError: %s", e)
        raise HTTPException(422, str(e))
    except ValueError as e:
        logger.error("POST /extract-url ValueError: %s", e)
        raise HTTPException(422, str(e))
    except RuntimeError as e:
        logger.error("POST /extract-url RuntimeError: %s", e)
        raise HTTPException(500, str(e))

    logger.info(
        "POST /extract-url OK — type=%s, serie=%s, filename=%s",
        result.get("pdf_type"), result.get("extraction", {}).get("serial_number"), filename,
    )
    return ExtractionResponse(**result)


@router.post("/save", response_model=SaveResponse)
async def save_data(request: SaveRequest):
    """Guarda datos confirmados por el usuario en Glide."""
    logger.info("POST /save — serie=%s, row_id=%s", request.serie, request.row_id)
    data = request.model_dump(exclude={"row_id"}, exclude_none=True)
    logger.info("POST /save — campos a guardar: %s", list(data.keys()))

    try:
        result = await save_to_glide(data=data, row_id=request.row_id)
    except RuntimeError as e:
        logger.error("POST /save RuntimeError: %s", e)
        raise HTTPException(500, f"Error guardando en Glide: {str(e)}")
    except ValueError as e:
        logger.error("POST /save ValueError: %s", e)
        raise HTTPException(400, str(e))

    if result["action"] == "range":
        count = result["count"]
        logger.info("POST /save OK — rango %s: %d tanques", result["serial_range"], count)
        return SaveResponse(
            row_id=None,
            action="range",
            message=f"Rango {result['serial_range']}: {count} tanques procesados ({result['created']} creados, {result['updated']} actualizados)",
            count=count,
        )

    action_msg = "actualizado" if result["action"] == "updated" else "creado"
    logger.info("POST /save OK — serie=%s, action=%s, row_id=%s", request.serie, result["action"], result.get("row_id"))
    return SaveResponse(
        row_id=result["row_id"],
        action=result["action"],
        message=f"Tanque {request.serie} {action_msg} exitosamente en Glide",
    )


@router.get("/tanques", response_model=list[TanqueResponse])
async def list_all_tanques():
    """Lista todos los tanques desde Glide."""
    logger.info("GET /tanques")
    try:
        tanques = await list_tanques()
    except RuntimeError as e:
        logger.error("GET /tanques error: %s", e)
        raise HTTPException(500, f"Error consultando Glide: {str(e)}")
    logger.info("GET /tanques OK — %d tanques", len(tanques))
    return [TanqueResponse(**t) for t in tanques]


@router.get("/tanques/pendientes", response_model=list[TanqueResponse])
async def list_tanques_pendientes():
    """Lista tanques con serie pero sin datos LIBRO DIGITAL (para batch)."""
    logger.info("GET /tanques/pendientes")
    try:
        tanques = await get_tanques_sin_libro_digital()
    except RuntimeError as e:
        logger.error("GET /tanques/pendientes error: %s", e)
        raise HTTPException(500, f"Error consultando Glide: {str(e)}")
    logger.info("GET /tanques/pendientes OK — %d pendientes", len(tanques))
    return [TanqueResponse(**t) for t in tanques]


@router.get("/tanques/{serie}/check", response_model=DuplicateCheckResponse)
async def check_tanque_duplicate(serie: str):
    """Verifica si un tanque con esa serie ya existe en Glide."""
    logger.info("GET /tanques/%s/check", serie)
    try:
        result = await check_duplicate(serie)
    except RuntimeError as e:
        logger.error("GET /tanques/%s/check error: %s", serie, e)
        raise HTTPException(500, f"Error consultando Glide: {str(e)}")
    logger.info("GET /tanques/%s/check — exists=%s", serie, result.get("exists"))
    return DuplicateCheckResponse(**result)


@router.post("/batch/process")
async def batch_process(tanque_row_ids: list[str]):
    """Obtiene PDFs de Glide para los tanques seleccionados.

    Retorna lista de tanques con sus URLs de documentos para que el frontend
    los procese uno a uno via /extract (descargando cada PDF).
    """
    logger.info("POST /batch/process — %d tanques solicitados", len(tanque_row_ids))
    if not tanque_row_ids:
        logger.warning("POST /batch/process rechazado: lista vacia")
        raise HTTPException(400, "Debe seleccionar al menos un tanque")

    results = []
    for row_id in tanque_row_ids:
        try:
            docs = await get_documentos_by_tanque(row_id)
            pdf_urls = []
            for doc in docs:
                urls = doc.get("pdf_urls", [])
                if isinstance(urls, list):
                    pdf_urls.extend(urls)
                elif urls:
                    pdf_urls.append(urls)
            results.append({
                "tanque_row_id": row_id,
                "pdf_urls": pdf_urls,
                "doc_count": len(pdf_urls),
            })
            logger.info("  batch tanque %s: %d PDFs encontrados", row_id, len(pdf_urls))
        except RuntimeError as e:
            logger.error("  batch tanque %s error: %s", row_id, e)
            results.append({
                "tanque_row_id": row_id,
                "pdf_urls": [],
                "doc_count": 0,
                "error": str(e),
            })

    total = sum(r["doc_count"] for r in results)
    logger.info("POST /batch/process OK — %d tanques, %d PDFs total", len(results), total)
    return {"tanques": results, "total_pdfs": total}
