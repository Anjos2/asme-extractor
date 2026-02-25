"""
ORM model para registros de recipientes a presion ASME.
- Finalidad: Define la tabla pressure_vessel_records con 11 campos de negocio,
  6 raw_* de auditoria, warnings, texto debug y timestamps.
- Consume: database.py (Base)
- Consumido por: service.py (CRUD), schemas.py (referencia de campos)
"""

from datetime import date, datetime

from sqlalchemy import ARRAY, DECIMAL, Date, DateTime, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class PressureVesselRecord(Base):
    __tablename__ = "pressure_vessel_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    pdf_type: Mapped[str] = mapped_column(String(10))  # TYPE_1 or TYPE_2
    original_filename: Mapped[str] = mapped_column(String(255))
    serial_number: Mapped[str | None] = mapped_column(String(255), nullable=True)
    vessel_type: Mapped[str | None] = mapped_column(String(50), nullable=True)

    # 11 business fields
    fabricante: Mapped[str | None] = mapped_column(Text, nullable=True)
    asme_code_edition: Mapped[str | None] = mapped_column(String(50), nullable=True)
    mawp_psi: Mapped[float | None] = mapped_column(DECIMAL(10, 2), nullable=True)
    hydro_test_pressure_psi: Mapped[float | None] = mapped_column(
        DECIMAL(10, 2), nullable=True
    )
    material_cuerpo: Mapped[str | None] = mapped_column(String(255), nullable=True)
    espesor_cuerpo_mm: Mapped[float | None] = mapped_column(
        DECIMAL(10, 3), nullable=True
    )
    longitud_cuerpo_m: Mapped[float | None] = mapped_column(
        DECIMAL(10, 4), nullable=True
    )
    diametro_interior_m: Mapped[float | None] = mapped_column(
        DECIMAL(10, 4), nullable=True
    )
    material_cabezales: Mapped[str | None] = mapped_column(String(255), nullable=True)
    espesor_cabezales_mm: Mapped[float | None] = mapped_column(
        DECIMAL(10, 3), nullable=True
    )
    fecha_certificacion: Mapped[date | None] = mapped_column(Date, nullable=True)

    # Raw values for audit
    raw_mawp: Mapped[str | None] = mapped_column(String(100), nullable=True)
    raw_hydro_test_pressure: Mapped[str | None] = mapped_column(
        String(100), nullable=True
    )
    raw_espesor_cuerpo: Mapped[str | None] = mapped_column(String(100), nullable=True)
    raw_longitud_cuerpo: Mapped[str | None] = mapped_column(String(100), nullable=True)
    raw_diametro_interior: Mapped[str | None] = mapped_column(
        String(100), nullable=True
    )
    raw_espesor_cabezales: Mapped[str | None] = mapped_column(
        String(100), nullable=True
    )

    # Extraction metadata
    extraction_warnings: Mapped[list[str] | None] = mapped_column(
        ARRAY(Text), nullable=True
    )
    raw_text_page1: Mapped[str | None] = mapped_column(Text, nullable=True)
    raw_text_page2: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
