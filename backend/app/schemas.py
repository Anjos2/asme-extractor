"""
Pydantic schemas para request/response de la API.
- Finalidad: Define contratos de datos entre LLM, API y frontend.
  ExtractionResult recibe datos del LLM, RecordResponse serializa para el cliente.
- Consume: nada (solo pydantic, datetime, decimal)
- Consumido por: llm_extractor.py (ExtractionResult), router.py (responses), service.py (tipado)
"""

from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel


class ExtractionResult(BaseModel):
    """Resultado de extraccion del LLM, antes de guardar en DB."""

    fabricante: str | None = None
    asme_code_edition: str | None = None
    mawp_psi: Decimal | None = None
    hydro_test_pressure_psi: Decimal | None = None
    material_cuerpo: str | None = None
    espesor_cuerpo_mm: Decimal | None = None
    longitud_cuerpo_m: Decimal | None = None
    diametro_interior_m: Decimal | None = None
    material_cabezales: str | None = None
    espesor_cabezales_mm: Decimal | None = None
    fecha_certificacion: date | None = None
    serial_number: str | None = None
    vessel_type: str | None = None

    # Raw values from LLM (before conversion)
    raw_mawp: str | None = None
    raw_hydro_test_pressure: str | None = None
    raw_espesor_cuerpo: str | None = None
    raw_longitud_cuerpo: str | None = None
    raw_diametro_interior: str | None = None
    raw_espesor_cabezales: str | None = None

    warnings: list[str] = []


class RecordResponse(BaseModel):
    """Respuesta al cliente con un registro completo."""

    model_config = {"from_attributes": True}

    id: int
    pdf_type: str
    original_filename: str
    serial_number: str | None
    vessel_type: str | None

    fabricante: str | None
    asme_code_edition: str | None
    mawp_psi: Decimal | None
    hydro_test_pressure_psi: Decimal | None
    material_cuerpo: str | None
    espesor_cuerpo_mm: Decimal | None
    longitud_cuerpo_m: Decimal | None
    diametro_interior_m: Decimal | None
    material_cabezales: str | None
    espesor_cabezales_mm: Decimal | None
    fecha_certificacion: date | None

    raw_mawp: str | None
    raw_hydro_test_pressure: str | None
    raw_espesor_cuerpo: str | None
    raw_longitud_cuerpo: str | None
    raw_diametro_interior: str | None
    raw_espesor_cabezales: str | None

    extraction_warnings: list[str] | None
    created_at: datetime


class RecordListResponse(BaseModel):
    """Respuesta paginada de registros."""

    records: list[RecordResponse]
    total: int


class UploadResponse(BaseModel):
    """Respuesta tras subir y procesar un PDF."""

    record: RecordResponse
    message: str
