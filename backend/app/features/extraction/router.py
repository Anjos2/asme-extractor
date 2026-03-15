"""
Endpoints API para extraccion ASME, guardado en Glide, gestion de tanques y backlog.
- Finalidad: Capa HTTP que recibe requests y delega a service.py, glide/repository.py y backlog.py.
  Endpoints: /extract, /extract-url (con auto_save + id_activo), /batch/extract (masivo async),
  /batch/status/{job_id}, /save, /tanques, /tanques/{serie}/check, /batch/process,
  /backlog, /backlog/summary.
  Proteccion "solo campos vacios": tanto /extract-url como /batch/extract verifican
  datos existentes en Glide antes de guardar, solo llenando campos que estan vacios.
  Batch async: respuesta inmediata con job_id, procesamiento paralelo en background,
  early skip para tanques ya procesados, status endpoint para monitorear progreso.
  Todos protegidos con API key via auth.py.
- Consume: service.py (extract, save, check, expand_serial_range), schemas.py (request/response),
  validators.py (PDFTypeError), config.py (settings), auth.py (verify_api_key),
  glide/repository.py (list, batch, get_tanque_by_row_id, get_all_tanques_by_row_id),
  backlog.py (read_backlog, get_backlog_summary)
  extract-url expande rangos automaticamente: actualiza id_activo + crea/actualiza resto por serie.
- Consumido por: main.py (registro de router)
"""

import asyncio
import json
import logging
import math
import time
from urllib.parse import urlparse
from uuid import uuid4

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile

from app.config import get_settings
from app.features.extraction.auth import verify_api_key
from app.features.extraction.backlog import get_backlog_summary, read_backlog
from app.features.extraction.service import (
    check_duplicate,
    expand_serial_range,
    extract_from_pdf,
    save_to_glide,
)
from app.features.extraction.validators import PDFTypeError
from app.features.glide.repository import (
    get_all_tanques_by_row_id,
    get_documentos_by_tanque,
    get_tanque_by_row_id,
    get_tanques_sin_libro_digital,
    list_tanques,
)
from app.schemas import (
    BatchExtractRequest,
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


def _filter_empty_fields(save_data: dict, existing: dict) -> dict:
    """Filtra save_data para solo incluir campos vacios en Glide.

    Si el campo ya tiene valor en Glide, no se sobrescribe.
    Esto protege datos ingresados manualmente por el usuario.
    """
    filtered = {}
    for campo, valor in save_data.items():
        existing_val = existing.get(campo)
        if existing_val:
            continue  # campo ya tiene valor → no sobrescribir
        filtered[campo] = valor
    return filtered


def _build_save_data(ext: dict, serie: str, include_serie: bool = True) -> dict:
    """Construye dict de datos a guardar en Glide desde la extraccion del LLM."""
    save_data = {
        "fabricante": ext.get("fabricante"),
        "ano_fabricacion": ext.get("ano_fabricacion"),
        "asme_code_edition": ext.get("asme_code_edition"),
        "mawp_psi": str(ext["mawp_psi"]) if ext.get("mawp_psi") is not None else None,
        "hydro_test_pressure_psi": str(ext["hydro_test_pressure_psi"]) if ext.get("hydro_test_pressure_psi") is not None else None,
        "material_cuerpo": ext.get("material_cuerpo"),
        "espesor_cuerpo_mm": str(ext["espesor_cuerpo_mm"]) if ext.get("espesor_cuerpo_mm") is not None else None,
        "longitud_cuerpo_m": str(ext["longitud_cuerpo_m"]) if ext.get("longitud_cuerpo_m") is not None else None,
        "diametro_interior_m": str(ext["diametro_interior_m"]) if ext.get("diametro_interior_m") is not None else None,
        "material_cabezales": ext.get("material_cabezales"),
        "espesor_cabezales_mm": str(ext["espesor_cabezales_mm"]) if ext.get("espesor_cabezales_mm") is not None else None,
        "fecha_certificacion": str(ext["fecha_certificacion"]) if ext.get("fecha_certificacion") is not None else None,
    }
    if include_serie:
        save_data["serie"] = serie
    return save_data


# POR QUÉ: Los 12 campos que el LLM extrae y se guardan en Glide.
# Si TODOS tienen valor, no hay necesidad de descargar/extraer el PDF de nuevo.
_EXTRACTION_FIELDS = [
    "fabricante", "ano_fabricacion", "asme_code_edition", "mawp_psi",
    "hydro_test_pressure_psi", "material_cuerpo", "espesor_cuerpo_mm",
    "longitud_cuerpo_m", "diametro_interior_m", "material_cabezales",
    "espesor_cabezales_mm", "fecha_certificacion",
]


def _all_fields_filled(existing: dict) -> bool:
    """Verifica si un tanque ya tiene TODOS los campos de extraccion llenos."""
    return all(existing.get(field) for field in _EXTRACTION_FIELDS)


# POR QUÉ: Dict en memoria para rastrear el progreso de batch jobs.
# Cada job tiene status, progreso y resultados parciales. Se limpia automaticamente
# despues de 1 hora para no acumular memoria indefinidamente.
_batch_jobs: dict[str, dict] = {}
_BATCH_JOB_TTL_SECONDS = 3600


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
async def extract_pdf_from_url(raw_request: Request):
    """Descarga un PDF desde una URL, auto-detecta tipo y extrae datos. NO guarda.

    Pensado para integracion con Glide: el usuario sube PDF en Glide,
    Glide envia la URL a esta API, la API descarga y procesa.
    Acepta body JSON con cualquier Content-Type (Glide envia text/plain).
    """
    content_type = raw_request.headers.get("content-type", "")
    body_bytes = await raw_request.body()

    try:
        data = json.loads(body_bytes)
    except (json.JSONDecodeError, ValueError) as e:
        logger.error("POST /extract-url JSON parse error: %s — body=%s", e, body_bytes[:300])
        raise HTTPException(400, f"Body debe ser JSON valido: {e}")

    request = ExtractUrlRequest(**data)
    logger.info(
        "POST /extract-url — pdf_url=%s, filename=%s, id_activo=%s, auto_save=%s, content_type=%s",
        request.pdf_url, request.filename, request.id_activo, request.auto_save, content_type,
    )
    max_size = settings.MAX_PDF_SIZE_MB * 1024 * 1024

    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.get(request.pdf_url)
            response.raise_for_status()
    except httpx.TimeoutException:
        logger.error("POST /extract-url timeout descargando %s", request.pdf_url)
        return ExtractionResponse(status="error", error_message="No se pudo descargar el PDF: tiempo de espera agotado (60s)")
    except httpx.HTTPStatusError as e:
        logger.error("POST /extract-url HTTP error %d descargando %s", e.response.status_code, request.pdf_url)
        return ExtractionResponse(status="error", error_message=f"No se pudo descargar el PDF: error HTTP {e.response.status_code}")
    except httpx.RequestError as e:
        logger.error("POST /extract-url conexion error: %s", e)
        return ExtractionResponse(status="error", error_message="No se pudo descargar el PDF: error de conexion")

    pdf_bytes = response.content
    logger.info("POST /extract-url — PDF descargado: %d bytes", len(pdf_bytes))

    if len(pdf_bytes) > max_size:
        logger.warning("POST /extract-url rechazado: PDF excede limite (%d > %d)", len(pdf_bytes), max_size)
        return ExtractionResponse(status="error", error_message=f"El PDF excede el limite de {settings.MAX_PDF_SIZE_MB}MB")

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
        return ExtractionResponse(
            status="error", filename=filename,
            error_message="El documento no es un formulario ASME U-1A ni un Certificado de Inspeccion reconocido. Verifique que el PDF sea correcto.",
        )
    except ValueError as e:
        logger.error("POST /extract-url ValueError: %s", e)
        return ExtractionResponse(
            status="error", filename=filename,
            error_message=f"No se pudieron extraer datos del PDF: {e}",
        )
    except RuntimeError as e:
        logger.error("POST /extract-url RuntimeError: %s", e)
        return ExtractionResponse(
            status="error", filename=filename,
            error_message=f"Error procesando el PDF: {e}",
        )

    serie = result.get("extraction", {}).get("serial_number")
    logger.info(
        "POST /extract-url OK — type=%s, serie=%s, filename=%s",
        result.get("pdf_type"), serie, filename,
    )

    if request.auto_save and serie:
        logger.info("POST /extract-url auto_save=True, guardando serie=%s", serie)
        ext = result.get("extraction", {})
        save_data = _build_save_data(ext, serie, include_serie=not request.id_activo)
        save_data = {k: v for k, v in save_data.items() if v is not None}

        # Prioridad: id_activo del request > row_id del duplicado > crear nuevo
        row_id = request.id_activo
        if not row_id and result.get("duplicate_found"):
            row_id = result.get("existing_data", {}).get("row_id")
        logger.info("POST /extract-url auto_save — row_id=%s (source=%s)",
                     row_id, "request" if request.id_activo else ("duplicate" if row_id else "new"))

        # Proteccion: solo llenar campos vacios (no sobrescribir datos existentes)
        if row_id:
            try:
                existing = await get_tanque_by_row_id(row_id)
                if existing:
                    original_count = len(save_data)
                    save_data = _filter_empty_fields(save_data, existing)
                    skipped = original_count - len(save_data)
                    if skipped:
                        logger.info("POST /extract-url — %d campos omitidos (ya tienen valor)", skipped)
            except Exception as e:
                logger.warning("POST /extract-url — no se pudo verificar campos existentes: %s", e)

        if not save_data:
            logger.info("POST /extract-url — todos los campos ya tienen valor, nada que guardar")
            result["saved"] = False
            result["save_result"] = {"message": "Todos los campos ya tienen valor en Glide"}
        else:
            try:
                save_result = await save_to_glide(data=save_data, row_id=row_id)
                result["saved"] = True
                result["save_result"] = save_result
                logger.info("POST /extract-url auto_save OK — action=%s, row_id=%s", save_result.get("action"), save_result.get("row_id"))
            except Exception as e:
                logger.error("POST /extract-url auto_save error: %s", e)
                result["saved"] = False
                result["save_result"] = {"error": str(e)}

        # POR QUE: Cuando el PDF tiene un rango de seriales (ej: M1744629-M1744662),
        # el bloque anterior solo actualiza el id_activo (1 fila). Este bloque
        # crea/actualiza las filas restantes del rango buscando por serial en Glide.
        if result.get("is_range") and serie:
            serials = expand_serial_range(serie)
            if len(serials) > 1:
                logger.info("POST /extract-url — rango detectado: %d seriales, expandiendo", len(serials))
                range_save_data = _build_save_data(ext, serie, include_serie=True)
                range_save_data = {k: v for k, v in range_save_data.items() if v is not None}
                try:
                    range_result = await save_to_glide(data=range_save_data)
                    result["range_saved"] = True
                    result["range_result"] = range_result
                    logger.info(
                        "POST /extract-url rango OK — %d creados, %d actualizados",
                        range_result.get("created", 0), range_result.get("updated", 0),
                    )
                except Exception as e:
                    logger.error("POST /extract-url rango error: %s", e)
                    result["range_saved"] = False
                    result["range_result"] = {"error": str(e)}

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
            logger.info("  batch/process tanque %s: %d PDFs encontrados", row_id, len(pdf_urls))
        except Exception as e:
            logger.error("  batch/process tanque %s error: %s", row_id, e)
            results.append({
                "tanque_row_id": row_id,
                "pdf_urls": [],
                "doc_count": 0,
                "error": str(e),
            })

    total = sum(r["doc_count"] for r in results)
    err_count = sum(1 for r in results if "error" in r)
    logger.info(
        "POST /batch/process DONE — %d tanques, %d PDFs total, %d errores",
        len(results), total, err_count,
    )
    return {"tanques": results, "total_pdfs": total, "errors": err_count}


@router.post("/batch/extract")
async def batch_extract(raw_request: Request):
    """Procesa multiples PDFs de forma asincrona y en paralelo.

    Responde INMEDIATAMENTE con un job_id. El procesamiento ocurre en background.
    Cada PDF se procesa en paralelo (hasta MAX_CONCURRENT_EXTRACTIONS simultaneos).
    Early skip: si un tanque ya tiene todos los campos llenos, no descarga ni extrae.
    Los resultados se guardan en Glide via auto_save conforme cada PDF termina.
    Consultar progreso con GET /batch/status/{job_id}.

    Body JSON:
        {"items": [{"pdf_url": "...", "id_activo": "...", "auto_save": true}, ...]}
    """
    body_bytes = await raw_request.body()
    try:
        data = json.loads(body_bytes)
    except (json.JSONDecodeError, ValueError) as e:
        logger.error("POST /batch/extract JSON parse error: %s", e)
        raise HTTPException(400, f"Body debe ser JSON valido: {e}")

    try:
        batch_req = BatchExtractRequest(**data)
    except Exception as e:
        logger.error("POST /batch/extract validation error: %s", e)
        raise HTTPException(400, f"Formato invalido: {e}")

    if not batch_req.items:
        raise HTTPException(400, "items no puede estar vacio")

    total = len(batch_req.items)
    max_concurrent = settings.MAX_CONCURRENT_EXTRACTIONS
    avg_time = settings.AVG_EXTRACTION_TIME_SECONDS
    estimated_seconds = math.ceil(total / max_concurrent) * avg_time

    job_id = str(uuid4())
    job = {
        "job_id": job_id,
        "status": "processing",
        "total": total,
        "completed": 0,
        "ok": 0,
        "skipped": 0,
        "errors": 0,
        "results": [],
        "started_at": time.time(),
        "estimated_seconds": estimated_seconds,
    }
    _batch_jobs[job_id] = job

    logger.info(
        "POST /batch/extract — job=%s, %d PDFs, estimated=%ds, max_concurrent=%d",
        job_id, total, estimated_seconds, max_concurrent,
    )

    # POR QUÉ: asyncio.create_task lanza el procesamiento en background.
    # El endpoint responde inmediatamente al cliente (<1s), evitando timeout de Cloudflare.
    asyncio.create_task(_run_batch(job_id, batch_req.items))

    return {
        "job_id": job_id,
        "status": "processing",
        "total": total,
        "estimated_seconds": estimated_seconds,
        "estimated_minutes": round(estimated_seconds / 60, 1),
        "message": f"Procesando {total} PDFs. Tiempo estimado: ~{math.ceil(estimated_seconds / 60)} minutos",
    }


async def _run_batch(job_id: str, items: list) -> None:
    """Orquesta el procesamiento paralelo de un batch con semaforo de concurrencia."""
    job = _batch_jobs[job_id]

    # UNA sola query a Glide: obtener todos los tanques indexados por row_id
    tanques_cache: dict[str, dict] = {}
    try:
        tanques_cache = await get_all_tanques_by_row_id()
        logger.info("batch[%s] cache de %d tanques cargado", job_id[:8], len(tanques_cache))
    except Exception as e:
        logger.warning("batch[%s] no se pudo cargar cache: %s", job_id[:8], e)

    semaphore = asyncio.Semaphore(settings.MAX_CONCURRENT_EXTRACTIONS)

    async def _process_with_semaphore(index: int, item) -> None:
        async with semaphore:
            await _process_batch_item(job_id, index, item, tanques_cache)

    tasks = [_process_with_semaphore(i, item) for i, item in enumerate(items)]
    await asyncio.gather(*tasks)

    job["status"] = "completed"
    elapsed = round(time.time() - job["started_at"], 1)
    logger.info(
        "batch[%s] DONE — %d total, %d ok, %d skipped, %d errors, %.1fs elapsed",
        job_id[:8], job["total"], job["ok"], job["skipped"], job["errors"], elapsed,
    )

    # POR QUÉ: Solo limpiar jobs COMPLETADOS con >1 hora de antiguedad.
    # Si un job largo (500 PDFs, ~67 min) sigue en "processing", NO se borra
    # para que Javier pueda seguir consultando el progreso.
    now = time.time()
    expired = [
        jid for jid, j in _batch_jobs.items()
        if j["status"] == "completed" and now - j["started_at"] > _BATCH_JOB_TTL_SECONDS
    ]
    for jid in expired:
        del _batch_jobs[jid]


async def _process_batch_item(
    job_id: str, index: int, item, tanques_cache: dict[str, dict],
) -> None:
    """Procesa un solo PDF del batch: early skip → descarga → extraccion → guardado."""
    job = _batch_jobs[job_id]
    item_result = {"pdf_url": item.pdf_url, "id_activo": item.id_activo}
    max_size = settings.MAX_PDF_SIZE_MB * 1024 * 1024

    try:
        # EARLY SKIP: verificar si el tanque ya tiene todos los campos llenos
        # ANTES de descargar o llamar al LLM (ahorra tokens y tiempo)
        if item.auto_save and item.id_activo:
            existing = tanques_cache.get(item.id_activo, {})
            if existing and _all_fields_filled(existing):
                item_result["status"] = "skipped"
                item_result["saved"] = False
                item_result["message"] = "Todos los campos ya tienen valor"
                logger.info("  batch[%d] EARLY_SKIP — id_activo=%s, todos los campos ya llenos (sin descarga ni extraccion)", index, item.id_activo)
                job["results"].append(item_result)
                job["completed"] += 1
                job["skipped"] += 1
                return

        # Descargar PDF
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.get(item.pdf_url)
            response.raise_for_status()

        pdf_bytes = response.content
        if len(pdf_bytes) > max_size:
            item_result["status"] = "error"
            item_result["error"] = f"PDF excede {settings.MAX_PDF_SIZE_MB}MB"
            job["results"].append(item_result)
            job["completed"] += 1
            job["errors"] += 1
            return

        # Derivar filename de la URL
        path = urlparse(item.pdf_url).path
        filename = path.rsplit("/", 1)[-1] if "/" in path else "document.pdf"
        if not filename.lower().endswith(".pdf"):
            filename += ".pdf"

        # Extraer datos con LLM
        result = await extract_from_pdf(pdf_bytes=pdf_bytes, filename=filename)
        serie = result.get("extraction", {}).get("serial_number")
        item_result["pdf_type"] = result.get("pdf_type")
        item_result["serie_extraida"] = serie
        item_result["extraction"] = result.get("extraction")

        # Guardar en Glide si auto_save
        if item.auto_save and serie:
            ext = result.get("extraction", {})

            if item.id_activo:
                # CON id_activo: guardar en la fila especifica + expandir rango
                save_data = _build_save_data(ext, serie or "", include_serie=False)
                save_data = {k: v for k, v in save_data.items() if v is not None}

                # Proteccion: solo llenar campos vacios
                existing = tanques_cache.get(item.id_activo, {})
                if existing:
                    original_count = len(save_data)
                    save_data = _filter_empty_fields(save_data, existing)
                    skipped_fields = original_count - len(save_data)
                    if skipped_fields:
                        logger.info("  batch[%d] — %d campos omitidos (ya tienen valor)", index, skipped_fields)

                if not save_data:
                    item_result["saved"] = False
                    item_result["status"] = "skipped"
                    item_result["message"] = "Todos los campos ya tienen valor"
                    logger.info("  batch[%d] SKIP — serie=%s, todos los campos llenos (post-extraccion)", index, serie)
                    job["skipped"] += 1
                else:
                    save_result = await save_to_glide(data=save_data, row_id=item.id_activo)
                    item_result["saved"] = True
                    item_result["save_action"] = save_result.get("action")
                    item_result["status"] = "ok"
                    logger.info("  batch[%d] OK — serie=%s, saved %d campos to %s", index, serie, len(save_data), item.id_activo)
                    job["ok"] += 1
            else:
                # POR QUÉ: Sin id_activo, Javier solo manda el pdf_url.
                # El script busca el tanque por serie en Glide. Si existe lo actualiza,
                # si no existe lo crea. Si es un rango, save_to_glide expande automaticamente.
                save_data = _build_save_data(ext, serie, include_serie=True)
                save_data = {k: v for k, v in save_data.items() if v is not None}

                try:
                    save_result = await save_to_glide(data=save_data)
                    item_result["saved"] = True
                    item_result["save_action"] = save_result.get("action")
                    item_result["status"] = "ok"
                    count = save_result.get("count", 1)
                    logger.info("  batch[%d] OK — serie=%s, saved by serie (%d tanques)", index, serie, count)
                    job["ok"] += 1
                    if save_result.get("action") == "range":
                        item_result["range_saved"] = True
                        item_result["range_result"] = save_result
                except Exception as e:
                    logger.error("  batch[%d] save error: %s", index, e)
                    item_result["saved"] = False
                    item_result["status"] = "error"
                    item_result["error"] = str(e)
                    job["errors"] += 1

            # Expandir rango si tiene id_activo y el PDF cubre multiples seriales
            # POR QUÉ: Con id_activo, el bloque anterior solo actualiza 1 fila.
            # Este bloque crea/actualiza las filas restantes del rango buscando por serie.
            # Sin id_activo, save_to_glide ya maneja el rango completo internamente.
            if item.id_activo and result.get("is_range") and serie:
                serials = expand_serial_range(serie)
                if len(serials) > 1:
                    logger.info("  batch[%d] — rango detectado: %d seriales, expandiendo", index, len(serials))
                    range_save_data = _build_save_data(ext, serie, include_serie=True)
                    range_save_data = {k: v for k, v in range_save_data.items() if v is not None}
                    try:
                        range_result = await save_to_glide(data=range_save_data)
                        item_result["range_saved"] = True
                        item_result["range_result"] = range_result
                        logger.info(
                            "  batch[%d] rango OK — %d creados, %d actualizados",
                            index, range_result.get("created", 0), range_result.get("updated", 0),
                        )
                    except Exception as e:
                        logger.error("  batch[%d] rango error: %s", index, e)
                        item_result["range_saved"] = False
                        item_result["range_result"] = {"error": str(e)}
        elif not item.auto_save:
            item_result["saved"] = False
            item_result["status"] = "extracted"
            logger.info("  batch[%d] OK — serie=%s (no auto_save)", index, serie)
            job["ok"] += 1
        else:
            item_result["saved"] = False
            item_result["status"] = "error"
            item_result["error"] = "No se pudo extraer numero de serie del PDF"
            logger.error("  batch[%d] error: no se extrajo serie", index)
            job["errors"] += 1

    except Exception as e:
        logger.error("  batch[%d] error: %s", index, e)
        item_result["status"] = "error"
        item_result["error"] = str(e)
        job["errors"] += 1

    job["results"].append(item_result)
    job["completed"] += 1


@router.get("/batch/status/{job_id}")
async def batch_status(job_id: str):
    """Consulta el progreso de un batch en procesamiento.

    Retorna status (processing/completed), progreso, tiempo transcurrido,
    estimado restante, y resultados parciales.
    """
    job = _batch_jobs.get(job_id)
    if not job:
        raise HTTPException(404, f"Job {job_id} no encontrado. Los jobs expiran despues de 1 hora.")

    elapsed = round(time.time() - job["started_at"], 1)
    remaining = max(0, job["estimated_seconds"] - elapsed) if job["status"] == "processing" else 0

    return {
        "job_id": job_id,
        "status": job["status"],
        "total": job["total"],
        "completed": job["completed"],
        "ok": job["ok"],
        "skipped": job["skipped"],
        "errors": job["errors"],
        "elapsed_seconds": elapsed,
        "estimated_remaining_seconds": round(remaining, 1),
        "results": job["results"],
    }


@router.get("/backlog")
async def get_backlog(limit: int = 50, category: str | None = None):
    """Ultimas N entradas del backlog de extracciones.

    Query params:
        limit: Cantidad de entradas (default 50, max 500).
        category: Filtro opcional — "ok", "incomplete" o "failed".
    """
    limit = min(limit, 500)
    logger.info("GET /backlog — limit=%d, category=%s", limit, category)
    entries = read_backlog(limit=limit, category=category)
    logger.info("GET /backlog OK — %d entradas", len(entries))
    return {"entries": entries, "count": len(entries)}


@router.get("/backlog/summary")
async def get_backlog_stats():
    """Estadisticas del backlog: totales, por categoria, campos mas fallidos, metodos U-1A."""
    logger.info("GET /backlog/summary")
    summary = get_backlog_summary()
    logger.info("GET /backlog/summary OK — %d entradas totales", summary["total"])
    return summary
