"""
Orquestacion completa de extraccion: recibe PDF, detecta tipo, extrae imagenes, llama LLM, guarda en DB.
- Finalidad: Coordina todo el pipeline de extraccion de datos ASME
- Consume: validators.py (validate, find_u1a, extract_text), pdf_to_images.py, llm_extractor.py, models.py, schemas.py
- Consumido por: router.py
"""

import logging

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import PressureVesselRecord
from app.schemas import ExtractionResult
from app.features.extraction.llm_extractor import extract_with_llm
from app.features.extraction.pdf_to_images import pdf_pages_to_base64
from app.features.extraction.validators import (
    extract_text_from_page,
    find_u1a_page,
    validate_pdf_type,
)

logger = logging.getLogger(__name__)


def _get_pages_for_type1() -> list[int]:
    """Paginas a convertir para Type 1: pags 1 y 2 (0-indexed: 0, 1)."""
    return [0, 1]


def _get_pages_for_type2(pdf_bytes: bytes) -> list[int]:
    """Paginas a convertir para Type 2: pag 2 (datos) + U-1A embebido."""
    pages = [1]  # Pagina 2 = index 1 (DATOS DEL PRODUCTO)
    u1a_page = find_u1a_page(pdf_bytes)
    if u1a_page is not None:
        pages.append(u1a_page)
        logger.info("U-1A embebido encontrado en pagina %d", u1a_page + 1)
    else:
        logger.warning("No se encontro U-1A embebido en el PDF tipo 2")
    return pages


async def process_pdf(
    pdf_bytes: bytes,
    pdf_type: str,
    filename: str,
    db: AsyncSession,
) -> PressureVesselRecord:
    """Procesa un PDF completo: valida, extrae imagenes, llama LLM, guarda en DB.

    Args:
        pdf_bytes: Contenido del PDF.
        pdf_type: 'TYPE_1' o 'TYPE_2' (segun zona de upload).
        filename: Nombre original del archivo.
        db: Sesion de base de datos.

    Returns:
        PressureVesselRecord guardado en DB.

    Raises:
        PDFTypeError: Si el PDF no coincide con el tipo esperado.
    """
    validate_pdf_type(pdf_bytes, pdf_type)

    if pdf_type == "TYPE_1":
        pages = _get_pages_for_type1()
    else:
        pages = _get_pages_for_type2(pdf_bytes)

    images_b64 = pdf_pages_to_base64(pdf_bytes, pages)
    if not images_b64:
        raise ValueError("No se pudieron extraer imagenes del PDF")

    result: ExtractionResult = await extract_with_llm(images_b64, pdf_type)

    raw_text_p1 = extract_text_from_page(pdf_bytes, 0)
    raw_text_p2 = extract_text_from_page(pdf_bytes, 1)

    record = PressureVesselRecord(
        pdf_type=pdf_type,
        original_filename=filename,
        serial_number=result.serial_number,
        vessel_type=result.vessel_type,
        fabricante=result.fabricante,
        asme_code_edition=result.asme_code_edition,
        mawp_psi=result.mawp_psi,
        hydro_test_pressure_psi=result.hydro_test_pressure_psi,
        material_cuerpo=result.material_cuerpo,
        espesor_cuerpo_mm=result.espesor_cuerpo_mm,
        longitud_cuerpo_m=result.longitud_cuerpo_m,
        diametro_interior_m=result.diametro_interior_m,
        material_cabezales=result.material_cabezales,
        espesor_cabezales_mm=result.espesor_cabezales_mm,
        fecha_certificacion=result.fecha_certificacion,
        raw_mawp=result.raw_mawp,
        raw_hydro_test_pressure=result.raw_hydro_test_pressure,
        raw_espesor_cuerpo=result.raw_espesor_cuerpo,
        raw_longitud_cuerpo=result.raw_longitud_cuerpo,
        raw_diametro_interior=result.raw_diametro_interior,
        raw_espesor_cabezales=result.raw_espesor_cabezales,
        extraction_warnings=result.warnings if result.warnings else None,
        raw_text_page1=raw_text_p1[:5000] if raw_text_p1 else None,
        raw_text_page2=raw_text_p2[:5000] if raw_text_p2 else None,
    )

    db.add(record)
    await db.commit()
    await db.refresh(record)
    logger.info("Record saved: id=%d, filename=%s", record.id, filename)
    return record


async def list_records(
    db: AsyncSession, limit: int = 50, offset: int = 0
) -> tuple[list[PressureVesselRecord], int]:
    """Lista registros paginados, ordenados por fecha de creacion descendente."""
    count_result = await db.execute(
        select(func.count()).select_from(PressureVesselRecord)
    )
    total = count_result.scalar()

    result = await db.execute(
        select(PressureVesselRecord)
        .order_by(PressureVesselRecord.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    records = list(result.scalars().all())
    return records, total


async def get_record(db: AsyncSession, record_id: int) -> PressureVesselRecord | None:
    """Obtiene un registro por ID."""
    result = await db.execute(
        select(PressureVesselRecord).where(PressureVesselRecord.id == record_id)
    )
    return result.scalar_one_or_none()


async def delete_record(db: AsyncSession, record_id: int) -> bool:
    """Elimina un registro por ID. Retorna True si existia."""
    record = await get_record(db, record_id)
    if not record:
        return False
    await db.delete(record)
    await db.commit()
    return True
