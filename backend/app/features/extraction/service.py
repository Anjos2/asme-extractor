"""
Orquestacion del pipeline de extraccion ASME y persistencia en Glide.
- Finalidad: Coordina auto-deteccion de tipo, conversion PDF→imagenes, llamada LLM,
  verificacion de duplicados en Glide, y guardado de datos confirmados.
- Consume: validators.py (detect_pdf_type, find_u1a_page), pdf_to_images.py,
  llm_extractor.py, schemas.py, glide/repository.py
- Consumido por: router.py
"""

import logging

from app.schemas import ExtractionResult
from app.features.extraction.llm_extractor import extract_with_llm
from app.features.extraction.pdf_to_images import pdf_pages_to_base64
from app.features.extraction.validators import (
    detect_pdf_type,
    find_u1a_page,
)
from app.features.glide.repository import (
    create_tanque,
    get_tanque_by_serie,
    update_tanque,
)

logger = logging.getLogger(__name__)


def _get_pages_for_type1() -> list[int]:
    """Paginas a convertir para Type 1: pags 1 y 2 (0-indexed: 0, 1)."""
    return [0, 1]


def _get_pages_for_type2(pdf_bytes: bytes) -> list[int]:
    """Paginas a convertir para Type 2: pag 2 (datos) + pag 8 (fecha inspeccion) + U-1A front + U-1A back."""
    pages = [1, 7]  # Pagina 2 = index 1 (DATOS DEL PRODUCTO), Pagina 8 = index 7 (FECHA INSPECCION)
    u1a_page = find_u1a_page(pdf_bytes)
    if u1a_page is not None:
        pages.append(u1a_page)
        pages.append(u1a_page + 1)
        logger.info(
            "U-1A embebido encontrado en paginas %d-%d",
            u1a_page + 1, u1a_page + 2,
        )
    else:
        logger.warning("No se encontro U-1A embebido en el PDF tipo 2")
    return pages


async def extract_from_pdf(
    pdf_bytes: bytes,
    filename: str,
) -> dict:
    """Extrae datos de un PDF ASME sin guardar. Auto-detecta tipo.

    Returns:
        Dict con: pdf_type, filename, extraction (datos extraidos),
        duplicate_found, existing_data (si el serial ya existe en Glide).
    """
    pdf_type = detect_pdf_type(pdf_bytes)
    logger.info("Auto-detected PDF type: %s for %s", pdf_type, filename)

    if pdf_type == "TYPE_1":
        pages = _get_pages_for_type1()
    else:
        pages = _get_pages_for_type2(pdf_bytes)

    images_b64 = pdf_pages_to_base64(pdf_bytes, pages)
    if not images_b64:
        raise ValueError("No se pudieron extraer imagenes del PDF")

    result: ExtractionResult = await extract_with_llm(images_b64, pdf_type)

    response = {
        "pdf_type": pdf_type,
        "filename": filename,
        "extraction": result.model_dump(),
        "duplicate_found": False,
        "existing_data": None,
    }

    if result.serial_number:
        existing = await get_tanque_by_serie(result.serial_number)
        if existing:
            response["duplicate_found"] = True
            response["existing_data"] = existing
            logger.info(
                "Duplicado encontrado: serie=%s, rowID=%s",
                result.serial_number,
                existing.get("row_id"),
            )

    return response


async def save_to_glide(data: dict, row_id: str | None = None) -> dict:
    """Guarda o actualiza datos confirmados en Glide.

    Args:
        data: Dict con nombres legibles (serie, fabricante, mawp_psi, etc.)
        row_id: Si se provee, actualiza el tanque existente. Si None, crea nuevo.

    Returns:
        Dict con row_id y action (created/updated).
    """
    if row_id:
        await update_tanque(row_id, data)
        logger.info("Tanque actualizado en Glide: rowID=%s", row_id)
        return {"row_id": row_id, "action": "updated"}
    else:
        new_row_id = await create_tanque(data)
        logger.info("Tanque creado en Glide: rowID=%s", new_row_id)
        return {"row_id": new_row_id, "action": "created"}


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
