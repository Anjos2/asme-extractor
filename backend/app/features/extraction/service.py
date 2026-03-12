"""
Orquestacion del pipeline de extraccion ASME y persistencia en Glide.
- Finalidad: Coordina auto-deteccion de tipo, conversion PDF→imagenes, llamada LLM,
  verificacion de duplicados en Glide, y guardado de datos confirmados.
  Pipeline TYPE_2 de 3 niveles (texto → escaneado → brute force) con retry automatico.
- Consume: validators.py (detect_pdf_type, find_u1a_page, find_scanned_pages),
  pdf_to_images.py (pdf_pages_to_base64, get_page_count),
  llm_extractor.py, schemas.py, backlog.py (log_extraction),
  glide/repository.py (create, update, get_tanque_by_serie, get_all_tanques_by_serie)
- Consumido por: router.py
"""

import logging
import re
import time

from app.features.extraction.backlog import log_extraction
from app.schemas import ExtractionResult
from app.features.extraction.llm_extractor import detect_type_with_vision, extract_with_llm
from app.features.extraction.pdf_to_images import get_page_count, pdf_pages_to_base64
from app.features.extraction.validators import (
    PDFTypeError,
    detect_pdf_type,
    find_scanned_pages,
    find_u1a_page,
)
from app.features.glide.repository import (
    create_tanque,
    get_all_tanques_by_serie,
    get_tanque_by_serie,
    update_tanque,
)

logger = logging.getLogger(__name__)

# POR QUE: 14 campos que el LLM debe extraer. Si muchos son null, la extraccion
# se considera incompleta y se reintenta con mas paginas (solo TYPE_2).
EXPECTED_FIELDS = [
    "fabricante", "ano_fabricacion", "asme_code_edition",
    "mawp_psi", "hydro_test_pressure_psi", "material_cuerpo",
    "espesor_cuerpo_mm", "longitud_cuerpo_m", "diametro_interior_m",
    "material_cabezales", "espesor_cabezales_mm", "fecha_certificacion",
    "serial_number", "vessel_type",
]

# POR QUE: Umbral de 4 campos null para considerar extraccion incompleta.
# Con 10+/14 campos, la extraccion es aceptable. Con 5+ nulls probablemente
# faltan las paginas del U-1A.
MAX_NULL_FIELDS_THRESHOLD = 4

# POR QUE: 10 paginas finales como red de seguridad en brute force.
# U-1A tiene 2 paginas (front+back). El margen amplio de 8 paginas extra
# cubre PDFs con anexos/fotos intercalados. Precision > costo de tokens.
BRUTE_FORCE_LAST_PAGES = 10


def _validate_extraction(result: ExtractionResult) -> tuple[int, list[str]]:
    """Cuenta campos extraidos vs null.

    Returns:
        Tupla (campos_extraidos, lista_de_campos_null).
    """
    null_fields = [f for f in EXPECTED_FIELDS if getattr(result, f, None) is None]
    return len(EXPECTED_FIELDS) - len(null_fields), null_fields


def _get_pages_for_type1() -> list[int]:
    """Paginas a convertir para Type 1: pags 1 y 2 (0-indexed: 0, 1)."""
    return [0, 1]


def _get_pages_for_type2(pdf_bytes: bytes) -> tuple[list[int], str]:
    """Paginas para Type 2 con pipeline de 3 niveles: texto → escaneado → brute force.

    Returns:
        Tupla (lista_paginas, metodo_usado). Metodo: "text", "scanned" o "brute_force".
    """
    pages = [1, 7]  # Pagina 2 = index 1 (DATOS DEL PRODUCTO), Pagina 8 = index 7 (FECHA INSPECCION)

    # Nivel 1: Buscar U-1A por texto extraible (mas preciso)
    u1a_page = find_u1a_page(pdf_bytes)
    if u1a_page is not None:
        pages.extend([u1a_page, u1a_page + 1])
        logger.info(
            "U-1A encontrado por texto en paginas %d-%d",
            u1a_page + 1, u1a_page + 2,
        )
        return pages, "text"

    # Nivel 2: Buscar paginas escaneadas en la 2da mitad (fallback para U-1A sin texto)
    scanned = find_scanned_pages(pdf_bytes)
    if scanned:
        pages.extend(scanned)
        logger.info(
            "U-1A no encontrado por texto, usando %d paginas escaneadas: %s",
            len(scanned), [p + 1 for p in scanned],
        )
        return pages, "scanned"

    # Nivel 3: Brute force — ultimas N paginas como red de seguridad
    total = get_page_count(pdf_bytes)
    brute_pages = list(range(max(total - BRUTE_FORCE_LAST_PAGES, 0), total))
    for p in brute_pages:
        if p not in pages:
            pages.append(p)
    logger.warning(
        "U-1A no encontrado, brute force: ultimas %d paginas del PDF (%d total)",
        BRUTE_FORCE_LAST_PAGES, total,
    )
    return pages, "brute_force"


async def extract_from_pdf(
    pdf_bytes: bytes,
    filename: str,
) -> dict:
    """Extrae datos de un PDF ASME sin guardar. Auto-detecta tipo.

    Returns:
        Dict con: pdf_type, filename, extraction (datos extraidos),
        duplicate_found, existing_data (si el serial ya existe en Glide).
    """
    start_time = time.monotonic()

    try:
        pdf_type = detect_pdf_type(pdf_bytes)
        logger.info("Auto-detected PDF type: %s for %s (text)", pdf_type, filename)
    except PDFTypeError:
        logger.warning("Text detection failed for %s, falling back to vision AI", filename)
        page1_images = pdf_pages_to_base64(pdf_bytes, [0])
        if not page1_images:
            raise ValueError("No se pudo convertir la pagina 1 a imagen")
        pdf_type = await detect_type_with_vision(page1_images[0])
        logger.info("Auto-detected PDF type: %s for %s (vision)", pdf_type, filename)

    if pdf_type == "TYPE_1":
        pages = _get_pages_for_type1()
        u1a_method = "direct"
    else:
        pages, u1a_method = _get_pages_for_type2(pdf_bytes)

    images_b64 = pdf_pages_to_base64(pdf_bytes, pages)
    if not images_b64:
        raise ValueError("No se pudieron extraer imagenes del PDF")

    result: ExtractionResult = await extract_with_llm(images_b64, pdf_type)
    extracted_count, null_fields = _validate_extraction(result)

    # POR QUE: Retry solo para TYPE_2 cuando la extraccion es incompleta y aun
    # no se uso brute force. Agrega paginas finales del PDF para cubrir
    # casos donde el nivel 1 o 2 selecciono paginas incorrectas.
    retry_used = False
    if (
        len(null_fields) > MAX_NULL_FIELDS_THRESHOLD
        and u1a_method not in ("brute_force", "direct")
        and pdf_type == "TYPE_2"
    ):
        logger.warning(
            "Extraccion incompleta (%d/%d campos null: %s), reintentando con brute force",
            len(null_fields), len(EXPECTED_FIELDS), null_fields,
        )
        total = get_page_count(pdf_bytes)
        brute_pages = list(range(max(total - BRUTE_FORCE_LAST_PAGES, 0), total))
        retry_pages = sorted(set(pages + brute_pages))
        retry_images = pdf_pages_to_base64(pdf_bytes, retry_pages)
        if retry_images:
            retry_result: ExtractionResult = await extract_with_llm(retry_images, pdf_type)
            retry_count, retry_nulls = _validate_extraction(retry_result)
            retry_used = True
            if retry_count > extracted_count:
                result = retry_result
                extracted_count = retry_count
                null_fields = retry_nulls
                pages = retry_pages
                u1a_method = "retry_brute_force"
                logger.info(
                    "Retry mejoro extraccion: %d/%d campos",
                    retry_count, len(EXPECTED_FIELDS),
                )
            else:
                logger.info(
                    "Retry no mejoro (%d vs %d), manteniendo resultado original",
                    retry_count, extracted_count,
                )

    if null_fields:
        logger.info(
            "Extraccion final: %d/%d campos, nulls: %s",
            extracted_count, len(EXPECTED_FIELDS), null_fields,
        )

    response = {
        "pdf_type": pdf_type,
        "filename": filename,
        "extraction": result.model_dump(),
        "duplicate_found": False,
        "existing_data": None,
        "u1a_method": u1a_method,
        "pages_sent": [p + 1 for p in pages],
        "fields_extracted": extracted_count,
        "fields_null": null_fields,
        "retry_used": retry_used,
    }

    if result.serial_number:
        serials = expand_serial_range(result.serial_number)
        if len(serials) > 1:
            response["is_range"] = True
            response["range_count"] = len(serials)
            response["range_serials"] = serials
            logger.info("Rango detectado: %s → %d tanques", result.serial_number, len(serials))
        else:
            existing = await get_tanque_by_serie(result.serial_number)
            if existing:
                response["duplicate_found"] = True
                response["existing_data"] = existing
                logger.info(
                    "Duplicado encontrado: serie=%s, rowID=%s",
                    result.serial_number,
                    existing.get("row_id"),
                )

    # POR QUE: Registrar cada extraccion en el backlog para analisis posterior.
    # Categorias: ok (10+ campos), incomplete (5-9), failed (<5).
    elapsed = round(time.monotonic() - start_time, 2)
    if extracted_count >= 10:
        category = "ok"
    elif extracted_count >= 5:
        category = "incomplete"
    else:
        category = "failed"

    log_extraction({
        "filename": filename,
        "pdf_type": pdf_type,
        "total_pages": get_page_count(pdf_bytes),
        "u1a_method": u1a_method,
        "pages_sent": [p + 1 for p in pages],
        "fields_extracted": extracted_count,
        "fields_null": null_fields,
        "retry_used": retry_used,
        "category": category,
        "extraction_time_seconds": elapsed,
        "serial_number": result.serial_number,
    })

    return response


def expand_serial_range(serial: str) -> list[str]:
    """Expande un rango de seriales como 'M1744629-M1744662' en una lista.

    Soporta formatos: 'PREFIX{start}-PREFIX{end}', 'PREFIX{start} to PREFIX{end}',
    'PREFIX{start} thru PREFIX{end}'.
    Si no es un rango, retorna [serial].
    """
    serial = serial.strip()

    # Patron: PREFIJO+NUMEROS separador PREFIJO+NUMEROS
    match = re.match(
        r"^([A-Za-z]*)(\d+)\s*[-–—]\s*([A-Za-z]*)(\d+)$",
        serial,
    )
    if not match:
        # POR QUE: "to" y "thru" son formatos comunes en formularios ASME U-1A
        # para indicar rangos de seriales (ej: "M1744629 thru M1744662")
        match = re.match(
            r"^([A-Za-z]*)(\d+)\s+(?:to|thru)\s+([A-Za-z]*)(\d+)$",
            serial,
            re.IGNORECASE,
        )

    if not match:
        return [serial]

    prefix1, start_str, prefix2, end_str = match.groups()
    prefix = prefix1 or prefix2
    start_num = int(start_str)
    end_num = int(end_str)

    if end_num < start_num or (end_num - start_num) > 500:
        logger.warning("Rango sospechoso: %s (start=%d, end=%d)", serial, start_num, end_num)
        return [serial]

    width = len(start_str)
    return [f"{prefix}{str(n).zfill(width)}" for n in range(start_num, end_num + 1)]


async def save_to_glide(data: dict, row_id: str | None = None) -> dict:
    """Guarda o actualiza datos confirmados en Glide.

    Si serial_number es un rango (ej: M1744629-M1744662), crea/actualiza
    un registro por cada serial en el rango con los mismos datos.

    Args:
        data: Dict con nombres legibles (serie, fabricante, mawp_psi, etc.)
        row_id: Si se provee, actualiza el tanque existente. Si None, crea nuevo.

    Returns:
        Dict con row_id, action, y count (numero de tanques afectados).
    """
    serial = data.get("serie", "")
    serials = expand_serial_range(serial)

    if len(serials) == 1:
        # Caso simple: un solo tanque
        if row_id:
            await update_tanque(row_id, data)
            logger.info("Tanque actualizado en Glide: rowID=%s", row_id)
            return {"row_id": row_id, "action": "updated", "count": 1}
        else:
            new_row_id = await create_tanque(data)
            logger.info("Tanque creado en Glide: rowID=%s", new_row_id)
            return {"row_id": new_row_id, "action": "created", "count": 1}

    # Caso rango: crear/actualizar multiples tanques con los mismos datos
    logger.info("Rango detectado: %s → %d tanques", serial, len(serials))

    # POR QUE: Cargamos TODOS los tanques de Glide en 1 sola llamada HTTP.
    # Sin cache, un rango de 34 seriales haria 34 queries (cada una trae la tabla
    # entera). Con cache: 1 query + dict lookup instantaneo por serie.
    tanques_cache: dict[str, dict] = {}
    try:
        tanques_cache = await get_all_tanques_by_serie()
        logger.info("  Rango: cache de %d tanques cargado", len(tanques_cache))
    except Exception as e:
        logger.warning("  Rango: no se pudo cargar cache, consultando uno a uno: %s", e)

    created = 0
    updated = 0
    errors = 0

    for s in serials:
        tanque_data = {**data, "serie": s}
        try:
            existing = tanques_cache.get(s) if tanques_cache else await get_tanque_by_serie(s)
            if existing:
                await update_tanque(existing["row_id"], tanque_data)
                logger.info("  Rango: actualizado %s (rowID=%s)", s, existing["row_id"])
                updated += 1
            else:
                await create_tanque(tanque_data)
                logger.info("  Rango: creado %s", s)
                created += 1
        except Exception as e:
            logger.error("  Rango: error en %s: %s", s, e)
            errors += 1

    logger.info(
        "Rango %s completado: %d creados, %d actualizados, %d errores",
        serial, created, updated, errors,
    )
    return {
        "row_id": None,
        "action": "range",
        "count": created + updated,
        "created": created,
        "updated": updated,
        "errors": errors,
        "serial_range": serial,
    }


async def check_duplicate(serial_number: str) -> dict:
    """Verifica si un serial number ya existe en Glide.

    Returns:
        Dict con exists (bool) y data (dict con datos existentes o None).
    """
    existing = await get_tanque_by_serie(serial_number)
    return {
        "exists": existing is not None,
        "data": existing,
    }
