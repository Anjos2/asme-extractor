"""
Endpoints API para extraccion ASME, guardado en Glide y gestion de tanques.
- Finalidad: Capa HTTP que recibe requests y delega a service.py y glide/repository.py.
  Endpoints: /extract (auto-detect + LLM), /save (Glide), /tanques, /tanques/{serie}/check, /batch/process.
- Consume: service.py (extract, save, check), schemas.py (request/response),
  validators.py (PDFTypeError), config.py (MAX_PDF_SIZE_MB), glide/repository.py (list, batch)
- Consumido por: main.py (registro de router)
"""

import logging

from fastapi import APIRouter, HTTPException, UploadFile

from app.config import get_settings
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
    ExtractionResponse,
    SaveRequest,
    SaveResponse,
    TanqueResponse,
)

logger = logging.getLogger(__name__)
settings = get_settings()
router = APIRouter(prefix="/api", tags=["extraction"])


@router.post("/extract", response_model=ExtractionResponse)
async def extract_pdf(file: UploadFile):
    """Sube un PDF, auto-detecta tipo y extrae datos con Vision AI. NO guarda."""
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(400, "Solo se aceptan archivos PDF")

    pdf_bytes = await file.read()
    max_size = settings.MAX_PDF_SIZE_MB * 1024 * 1024
    if len(pdf_bytes) > max_size:
        raise HTTPException(400, f"PDF excede {settings.MAX_PDF_SIZE_MB}MB")

    try:
        result = await extract_from_pdf(pdf_bytes=pdf_bytes, filename=file.filename)
    except PDFTypeError as e:
        raise HTTPException(422, str(e))
    except ValueError as e:
        raise HTTPException(422, str(e))
    except RuntimeError as e:
        raise HTTPException(500, str(e))

    return ExtractionResponse(**result)


@router.post("/save", response_model=SaveResponse)
async def save_data(request: SaveRequest):
    """Guarda datos confirmados por el usuario en Glide."""
    data = request.model_dump(exclude={"row_id"}, exclude_none=True)

    try:
        result = await save_to_glide(data=data, row_id=request.row_id)
    except RuntimeError as e:
        raise HTTPException(500, f"Error guardando en Glide: {str(e)}")
    except ValueError as e:
        raise HTTPException(400, str(e))

    action_msg = "actualizado" if result["action"] == "updated" else "creado"
    return SaveResponse(
        row_id=result["row_id"],
        action=result["action"],
        message=f"Tanque {request.serie} {action_msg} exitosamente en Glide",
    )


@router.get("/tanques", response_model=list[TanqueResponse])
async def list_all_tanques():
    """Lista todos los tanques desde Glide."""
    try:
        tanques = await list_tanques()
    except RuntimeError as e:
        raise HTTPException(500, f"Error consultando Glide: {str(e)}")
    return [TanqueResponse(**t) for t in tanques]


@router.get("/tanques/pendientes", response_model=list[TanqueResponse])
async def list_tanques_pendientes():
    """Lista tanques con serie pero sin datos LIBRO DIGITAL (para batch)."""
    try:
        tanques = await get_tanques_sin_libro_digital()
    except RuntimeError as e:
        raise HTTPException(500, f"Error consultando Glide: {str(e)}")
    return [TanqueResponse(**t) for t in tanques]


@router.get("/tanques/{serie}/check", response_model=DuplicateCheckResponse)
async def check_tanque_duplicate(serie: str):
    """Verifica si un tanque con esa serie ya existe en Glide."""
    try:
        result = await check_duplicate(serie)
    except RuntimeError as e:
        raise HTTPException(500, f"Error consultando Glide: {str(e)}")
    return DuplicateCheckResponse(**result)


@router.post("/batch/process")
async def batch_process(tanque_row_ids: list[str]):
    """Obtiene PDFs de Glide para los tanques seleccionados.

    Retorna lista de tanques con sus URLs de documentos para que el frontend
    los procese uno a uno via /extract (descargando cada PDF).
    """
    if not tanque_row_ids:
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
        except RuntimeError as e:
            results.append({
                "tanque_row_id": row_id,
                "pdf_urls": [],
                "doc_count": 0,
                "error": str(e),
            })

    return {"tanques": results, "total_pdfs": sum(r["doc_count"] for r in results)}
