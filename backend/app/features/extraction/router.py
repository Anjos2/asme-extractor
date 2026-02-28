"""
Endpoints API para upload, listado, detalle y eliminacion de registros.
- Finalidad: Capa HTTP que recibe requests y delega a service.py
- Consume: service.py (CRUD), schemas.py (responses), database.py (get_db), validators.py (PDFTypeError), config.py (MAX_PDF_SIZE_MB)
- Consumido por: main.py (registro de router)
"""

from fastapi import APIRouter, Depends, HTTPException, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database import get_db
from app.features.extraction.service import (
    delete_record,
    get_record,
    list_records,
    process_pdf,
)
from app.features.extraction.validators import PDFTypeError
from app.schemas import RecordListResponse, RecordResponse, UploadResponse

settings = get_settings()
router = APIRouter(prefix="/api", tags=["extraction"])

VALID_PDF_TYPES = {"type1": "TYPE_1", "type2": "TYPE_2"}


@router.post("/upload/{pdf_type}", response_model=UploadResponse)
async def upload_pdf(
    pdf_type: str,
    file: UploadFile,
    db: AsyncSession = Depends(get_db),
):
    """Sube un PDF, extrae datos con Vision AI y guarda en DB."""
    if pdf_type not in VALID_PDF_TYPES:
        raise HTTPException(400, f"Tipo invalido. Use: {list(VALID_PDF_TYPES.keys())}")

    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(400, "Solo se aceptan archivos PDF")

    pdf_bytes = await file.read()
    max_size = settings.MAX_PDF_SIZE_MB * 1024 * 1024
    if len(pdf_bytes) > max_size:
        raise HTTPException(400, f"PDF excede {settings.MAX_PDF_SIZE_MB}MB")

    try:
        record = await process_pdf(
            pdf_bytes=pdf_bytes,
            pdf_type=VALID_PDF_TYPES[pdf_type],
            filename=file.filename,
            db=db,
        )
    except PDFTypeError as e:
        raise HTTPException(422, str(e))
    except RuntimeError as e:
        raise HTTPException(500, str(e))

    return UploadResponse(
        record=RecordResponse.model_validate(record),
        message="PDF procesado exitosamente",
    )


@router.get("/records", response_model=RecordListResponse)
async def list_all_records(
    limit: int = 50,
    offset: int = 0,
    db: AsyncSession = Depends(get_db),
):
    """Lista registros paginados."""
    limit = max(1, min(limit, 100))
    offset = max(0, offset)
    records, total = await list_records(db, limit=limit, offset=offset)
    return RecordListResponse(
        records=[RecordResponse.model_validate(r) for r in records],
        total=total,
    )


@router.get("/records/{record_id}", response_model=RecordResponse)
async def get_single_record(
    record_id: int,
    db: AsyncSession = Depends(get_db),
):
    """Obtiene detalle de un registro."""
    record = await get_record(db, record_id)
    if not record:
        raise HTTPException(404, "Registro no encontrado")
    return RecordResponse.model_validate(record)


@router.delete("/records/{record_id}")
async def delete_single_record(
    record_id: int,
    db: AsyncSession = Depends(get_db),
):
    """Elimina un registro."""
    deleted = await delete_record(db, record_id)
    if not deleted:
        raise HTTPException(404, "Registro no encontrado")
    return {"message": "Registro eliminado", "id": record_id}
