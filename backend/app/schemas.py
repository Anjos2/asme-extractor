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

    Acepta dos formatos:
    - Simple: {"pdf_urls": ["url1", "url2"], "auto_save": true}
    - Avanzado: {"items": [{"pdf_url": "url1", "id_activo": "row-id"}], "auto_save": true}

    auto_save a nivel de batch se aplica a todos los items (default true).
    Cada item puede tener su propio id_activo opcional.
    """

    items: list[ExtractUrlRequest] = []
    pdf_urls: list[str] = []
    auto_save: bool = True

    @model_validator(mode="before")
    @classmethod
    def _build_items(cls, data: dict) -> dict:
        """Convierte pdf_urls a items y aplica auto_save global."""
        if not isinstance(data, dict):
            return data

        batch_auto_save = data.get("auto_save", True)

        # Si mandan pdf_urls (formato simple), convertir a items
        if "pdf_urls" in data and data["pdf_urls"]:
            urls = data["pdf_urls"]
            if not data.get("items"):
                data["items"] = []
            for url in urls:
                data["items"].append({"pdf_url": url, "auto_save": batch_auto_save})

        # Aplicar auto_save global a items que no lo tengan explícito
        if "items" in data:
            for item in data["items"]:
                if isinstance(item, dict) and "auto_save" not in item:
                    item["auto_save"] = batch_auto_save

        return data


class ExtractionResponse(BaseModel):
    """Respuesta tras extraer datos. Con auto_save incluye resultado de guardado.

    Siempre retorna 200. Si hay error, status='error' y error_message tiene el detalle.
    Glide puede leer error_message para mostrar al usuario.
    """

    status: str = "ok"
    error_message: str | None = None
    pdf_type: str | None = None
    filename: str | None = None
    extraction: dict | None = None
    duplicate_found: bool = False
    existing_data: dict | None = None
    is_range: bool = False
    range_count: int = 0
    range_serials: list[str] = []
    saved: bool = False
    save_result: dict | None = None
    range_saved: bool = False
    range_result: dict | None = None
    u1a_method: str | None = None
    pages_sent: list[int] = []
    fields_extracted: int = 0
    fields_null: list[str] = []
    retry_used: bool = False


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
