"""
Deteccion y validacion de tipo de PDF (Type 1 vs Type 2) via texto.
- Finalidad: Usa pdfplumber para leer texto de pag 1, detectar tipo de PDF,
  validar que coincida con la zona de upload, y buscar U-1A embebido en Type 2.
- Consume: nada interno (solo pdfplumber)
- Consumido por: service.py (validacion + busqueda U-1A), router.py (PDFTypeError)
"""

import io

import pdfplumber


class PDFTypeError(Exception):
    """Error cuando el PDF no coincide con el tipo esperado."""

    pass


def extract_text_from_page(pdf_bytes: bytes, page_number: int) -> str:
    """Extrae texto de una pagina especifica del PDF."""
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        if page_number >= len(pdf.pages):
            return ""
        page = pdf.pages[page_number]
        return page.extract_text() or ""


def detect_pdf_type(pdf_bytes: bytes) -> str:
    """Detecta si es TYPE_1 (U-1A directo) o TYPE_2 (Certificado de Inspeccion).

    Returns:
        'TYPE_1' o 'TYPE_2'

    Raises:
        PDFTypeError si no se puede determinar el tipo.
    """
    text_page1 = extract_text_from_page(pdf_bytes, 0)
    text_upper = text_page1.upper()

    is_type1 = "FORM U-1A" in text_upper or (
        "MANUFACTURER" in text_upper and "DATA REPORT" in text_upper
    )
    is_type2 = "CERTIFICADO" in text_upper and "INSPECCI" in text_upper

    if is_type1 and not is_type2:
        return "TYPE_1"
    if is_type2 and not is_type1:
        return "TYPE_2"
    if is_type1 and is_type2:
        return "TYPE_1"

    raise PDFTypeError(
        "No se pudo determinar el tipo de PDF. "
        "Asegurese de subir un formulario ASME U-1A o un Certificado de Inspeccion."
    )


def validate_pdf_type(pdf_bytes: bytes, expected_type: str) -> None:
    """Valida que el PDF corresponda al tipo esperado.

    Raises:
        PDFTypeError si no coincide.
    """
    detected = detect_pdf_type(pdf_bytes)
    if detected != expected_type:
        type_names = {
            "TYPE_1": "FORM U-1A (< 10 anos)",
            "TYPE_2": "Certificado de Inspeccion (> 10 anos)",
        }
        raise PDFTypeError(
            f"El PDF parece ser {type_names.get(detected, detected)}, "
            f"pero se subio en la zona de {type_names.get(expected_type, expected_type)}. "
            f"Por favor use la zona correcta."
        )


def find_u1a_page(pdf_bytes: bytes) -> int | None:
    """Busca la pagina que contiene el FORM U-1A embebido en PDFs tipo 2.

    Busca desde la pagina 5 en adelante para evitar falsos positivos.

    Returns:
        Numero de pagina (0-indexed) o None si no se encuentra.
    """
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        for i in range(min(5, len(pdf.pages)), len(pdf.pages)):
            text = (pdf.pages[i].extract_text() or "").upper()
            if "FORM U-1A" in text or "MANUFACTURER'S DATA REPORT" in text:
                return i
    return None
