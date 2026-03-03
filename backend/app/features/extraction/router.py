"""
Endpoints API para extraccion ASME, guardado en Glide y gestion de tanques.
- Finalidad: Capa HTTP que recibe requests y delega a service.py y glide/repository.py.
  Endpoints: /extract, /extract-url (con auto_save + id_activo), /batch/extract (masivo),
  /save, /tanques, /tanques/{serie}/check, /batch/process.
  Proteccion "solo campos vacios": tanto /extract-url como /batch/extract verifican
  datos existentes en Glide antes de guardar, solo llenando campos que estan vacios.
  Batch optimizado: UNA sola query a Glide al inicio para cache de todos los tanques.
  Todos protegidos con API key via auth.py.
- Consume: service.py (extract, save, check), schemas.py (request/response),
  validators.py (PDFTypeError), config.py (MAX_PDF_SIZE_MB), auth.py (verify_api_key),
  glide/repository.py (list, batch, get_tanque_by_row_id, get_all_tanques_by_row_id)
- Consumido por: main.py (registro de router)
"""

import json
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


@router.post("/batch/extract")
async def batch_extract(raw_request: Request):
    """Procesa multiples PDFs en una sola peticion.

    Recibe lista de items con pdf_url + id_activo. Descarga, extrae y guarda
    cada PDF directamente en el id_activo indicado.
    Proteccion: solo llena campos vacios (no sobrescribe datos existentes).
    Optimizacion: UNA sola query a Glide al inicio para obtener todos los tanques.

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

    logger.info("POST /batch/extract — %d PDFs a procesar", len(batch_req.items))
    max_size = settings.MAX_PDF_SIZE_MB * 1024 * 1024

    # UNA sola query a Glide: obtener todos los tanques indexados por row_id
    tanques_cache: dict[str, dict] = {}
    try:
        tanques_cache = await get_all_tanques_by_row_id()
        logger.info("POST /batch/extract — cache de %d tanques cargado", len(tanques_cache))
    except Exception as e:
        logger.warning("POST /batch/extract — no se pudo cargar cache de tanques: %s", e)

    results = []
    for i, item in enumerate(batch_req.items):
        item_result = {"pdf_url": item.pdf_url, "id_activo": item.id_activo}
        try:
            # Descargar PDF
            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.get(item.pdf_url)
                response.raise_for_status()

            pdf_bytes = response.content
            if len(pdf_bytes) > max_size:
                item_result["status"] = "error"
                item_result["error"] = f"PDF excede {settings.MAX_PDF_SIZE_MB}MB"
                results.append(item_result)
                continue

            # Derivar filename de la URL
            path = urlparse(item.pdf_url).path
            filename = path.rsplit("/", 1)[-1] if "/" in path else "document.pdf"
            if not filename.lower().endswith(".pdf"):
                filename += ".pdf"

            # Extraer datos
            result = await extract_from_pdf(pdf_bytes=pdf_bytes, filename=filename)
            serie = result.get("extraction", {}).get("serial_number")
            item_result["pdf_type"] = result.get("pdf_type")
            item_result["serie_extraida"] = serie
            item_result["extraction"] = result.get("extraction")

            # Guardar directamente si auto_save e id_activo
            if item.auto_save and item.id_activo:
                ext = result.get("extraction", {})
                save_data = _build_save_data(ext, serie or "", include_serie=False)
                save_data = {k: v for k, v in save_data.items() if v is not None}

                # Proteccion: solo llenar campos vacios
                existing = tanques_cache.get(item.id_activo, {})
                if existing:
                    original_count = len(save_data)
                    save_data = _filter_empty_fields(save_data, existing)
                    skipped = original_count - len(save_data)
                    if skipped:
                        logger.info("  batch[%d] — %d campos omitidos (ya tienen valor)", i, skipped)

                if not save_data:
                    item_result["saved"] = False
                    item_result["status"] = "skipped"
                    item_result["message"] = "Todos los campos ya tienen valor"
                    logger.info("  batch[%d] SKIP — serie=%s, todos los campos llenos", i, serie)
                else:
                    save_result = await save_to_glide(data=save_data, row_id=item.id_activo)
                    item_result["saved"] = True
                    item_result["save_action"] = save_result.get("action")
                    item_result["status"] = "ok"
                    logger.info("  batch[%d] OK — serie=%s, saved %d campos to %s", i, serie, len(save_data), item.id_activo)
            else:
                item_result["saved"] = False
                item_result["status"] = "extracted"
                logger.info("  batch[%d] OK — serie=%s (no auto_save)", i, serie)

        except Exception as e:
            logger.error("  batch[%d] error: %s", i, e)
            item_result["status"] = "error"
            item_result["error"] = str(e)

        results.append(item_result)

    ok_count = sum(1 for r in results if r["status"] == "ok")
    skip_count = sum(1 for r in results if r.get("status") == "skipped")
    err_count = sum(1 for r in results if r["status"] == "error")
    logger.info("POST /batch/extract DONE — %d total, %d ok, %d skipped, %d errors", len(results), ok_count, skip_count, err_count)
    return {"results": results, "total": len(results), "ok": ok_count, "skipped": skip_count, "errors": err_count}
