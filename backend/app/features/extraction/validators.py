"""
Auto-deteccion de tipo de PDF y utilidades de texto para PDFs ASME.
- Finalidad: Usa pdfplumber para leer texto de pag 1, auto-detectar tipo de PDF
  (TYPE_1 U-1A directo o TYPE_2 Certificado de Inspeccion), y buscar U-1A embebido.
- Consume: nada interno (solo pdfplumber)
- Consumido por: service.py (auto-detect + busqueda U-1A), router.py (PDFTypeError)
"""

import io

import pdfplumber


class PDFTypeError(Exception):
    """Error cuando el PDF no es un tipo ASME reconocido."""

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
    # Texto sin espacios para detectar palabras rotas por OCR
    # (ej: "CE RTIFICADO" → "CERTIFICADO")
    text_compact = text_upper.replace(" ", "")

    is_type1 = "FORMU-1A" in text_compact or (
        "MANUFACTURER" in text_compact and "DATAREPORT" in text_compact
    )
    is_type2 = "CERTIFICADO" in text_compact and "INSPECCI" in text_compact

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


def find_u1a_page(pdf_bytes: bytes) -> int | None:
    """Busca la pagina que contiene el FORM U-1A embebido en PDFs tipo 2.

    Busca desde la pagina 5 en adelante. Requiere que la pagina contenga
    campos reales del formulario (MAWP, SHELL, HEADS) para evitar falsos
    positivos con paginas que solo mencionan "Form U-1A" como referencia textual.

    Returns:
        Numero de pagina (0-indexed) o None si no se encuentra.
    """
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        for i in range(min(5, len(pdf.pages)), len(pdf.pages)):
            text = (pdf.pages[i].extract_text() or "").upper()
            has_u1a_header = "FORM U-1A" in text or "MANUFACTURER'S DATA REPORT" in text
            has_form_fields = "MAWP" in text or "SHELL:" in text or "HEADS:" in text
            if has_u1a_header and has_form_fields:
                return i
    return None
