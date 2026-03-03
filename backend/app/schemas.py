"""
Pydantic schemas para request/response de la API.
- Finalidad: Define contratos de datos entre LLM, API y frontend.
  ExtractionResult recibe datos del LLM. ExtractionResponse envuelve para el frontend.
  ExtractUrlRequest recibe URL de PDF desde Glide. SaveRequest recibe datos confirmados.
- Consume: nada (solo pydantic, datetime, decimal)
- Consumido por: llm_extractor.py (ExtractionResult), router.py (responses), service.py (tipado)
"""

from datetime import date
from decimal import Decimal

from pydantic import BaseModel, model_validator


class ExtractionResult(BaseModel):
    """Resultado de extraccion del LLM, antes de revision por el usuario."""

    fabricante: str | None = None
    ano_fabricacion: str | None = None
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


class ExtractUrlRequest(BaseModel):
    """Request para extraer datos desde una URL de PDF (integracion Glide).

    Con auto_save=True, extrae y guarda automaticamente en Glide (flujo Glide).
    Con auto_save=False (default), solo extrae (flujo frontend con revision humana).
    id_activo permite especificar la fila exacta a actualizar en Glide.
    """

    pdf_url: str
    filename: str | None = None
    auto_save: bool = False
    id_activo: str | None = None

    @model_validator(mode="before")
    @classmethod
    def _accept_row_id(cls, data: dict) -> dict:
        """Backward compat: acepta 'row_id' como alias de 'id_activo'."""
        if isinstance(data, dict) and "row_id" in data and "id_activo" not in data:
            data["id_activo"] = data.pop("row_id")
        return data


class BatchExtractRequest(BaseModel):
    """Request para procesar multiples PDFs en una sola peticion.

    Cada item tiene pdf_url e id_activo. Se procesan todos sin consultas
    adicionales a Glide (se usa id_activo directamente para guardar).
    """

    items: list[ExtractUrlRequest]


class ExtractionResponse(BaseModel):
    """Respuesta tras extraer datos. Con auto_save incluye resultado de guardado."""

    pdf_type: str
    filename: str
    extraction: dict
    duplicate_found: bool = False
    existing_data: dict | None = None
    is_range: bool = False
    range_count: int = 0
    range_serials: list[str] = []
    saved: bool = False
    save_result: dict | None = None


class SaveRequest(BaseModel):
    """Datos confirmados por el usuario para guardar en Glide."""

    serie: str
    ano_fabricacion: str | None = None
    fabricante: str | None = None
    asme_code_edition: str | None = None
    mawp_psi: str | None = None
    hydro_test_pressure_psi: str | None = None
    material_cuerpo: str | None = None
    espesor_cuerpo_mm: str | None = None
    longitud_cuerpo_m: str | None = None
    diametro_interior_m: str | None = None
    material_cabezales: str | None = None
    espesor_cabezales_mm: str | None = None
    fecha_certificacion: str | None = None
    row_id: str | None = None


class SaveResponse(BaseModel):
    """Confirmacion de guardado en Glide."""

    row_id: str | None = None
    action: str
    message: str
    count: int = 1


class TanqueResponse(BaseModel):
    """Un tanque desde Glide para listado."""

    row_id: str | None = None
    serie: str | None = None
    ano_fabricacion: str | None = None
    fabricante: str | None = None
    asme_code_edition: str | None = None
    mawp_psi: str | None = None
    hydro_test_pressure_psi: str | None = None
    material_cuerpo: str | None = None
    espesor_cuerpo_mm: str | None = None
    longitud_cuerpo_m: str | None = None
    diametro_interior_m: str | None = None
    material_cabezales: str | None = None
    espesor_cabezales_mm: str | None = None
    fecha_certificacion: str | None = None


class DuplicateCheckResponse(BaseModel):
    """Resultado de verificacion de duplicado."""

    exists: bool
    data: dict | None = None
