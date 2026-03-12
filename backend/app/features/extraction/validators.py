"""
Auto-deteccion de tipo de PDF y utilidades de texto para PDFs ASME.
- Finalidad: Usa pdfplumber para leer texto de paginas, auto-detectar tipo de PDF
  (TYPE_1 U-1A directo o TYPE_2 Certificado de Inspeccion), buscar U-1A embebido
  por texto, y detectar paginas escaneadas (sin texto) como fallback para U-1A.
- Consume: nada interno (solo pdfplumber)
- Consumido por: service.py (auto-detect + busqueda U-1A + scanned pages), router.py (PDFTypeError)
"""

import io
import logging

import pdfplumber

logger = logging.getLogger(__name__)

# POR QUE: Paginas con menos de este umbral de caracteres se consideran
# escaneadas (imagenes sin OCR). 50 chars filtra paginas con solo numeros
# de pagina o headers minimos que pdfplumber a veces extrae de imagenes.
SCANNED_PAGE_TEXT_THRESHOLD = 50


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
    # POR QUE: Texto sin espacios para detectar palabras rotas por OCR
    # (ej: "CE RTIFICADO" -> "CERTIFICADO")
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

    Usa dos estrategias: texto normal y texto compacto (anti-OCR).
    Requiere header del formulario + campos reales para evitar falsos positivos.

    Returns:
        Numero de pagina (0-indexed) o None si no se encuentra.
    """
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        start = min(5, len(pdf.pages))
        for i in range(start, len(pdf.pages)):
            text = (pdf.pages[i].extract_text() or "").upper()
            compact = text.replace(" ", "")

            has_u1a = (
                "FORM U-1A" in text
                or "MANUFACTURER'S DATA REPORT" in text
                or "FORMU-1A" in compact
                or ("MANUFACTURER" in compact and "DATAREPORT" in compact)
            )
            has_fields = (
                "MAWP" in text
                or "SHELL:" in text
                or "HEADS:" in text
                or "MAWP" in compact
            )
            if has_u1a and has_fields:
                logger.info("find_u1a_page: encontrado en pagina %d (texto)", i + 1)
                return i
    return None


def find_scanned_pages(pdf_bytes: bytes) -> list[int]:
    """Detecta paginas escaneadas (imagenes sin texto extraible) en la segunda mitad del PDF.

    Busca paginas con muy poco texto (< SCANNED_PAGE_TEXT_THRESHOLD chars).
    Retorna maximo 4 paginas (2 para U-1A front/back + margen).

    Returns:
        Lista de page indexes (0-indexed), maximo 4 elementos.
    """
    scanned = []
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        total = len(pdf.pages)
        # POR QUE: Buscamos desde la mitad del PDF porque el U-1A embebido
        # siempre esta en la segunda mitad (paginas finales del certificado)
        start = total // 2
        for i in range(start, total):
            text = pdf.pages[i].extract_text() or ""
            if len(text.strip()) < SCANNED_PAGE_TEXT_THRESHOLD:
                scanned.append(i)

    if scanned:
        logger.info(
            "find_scanned_pages: %d paginas escaneadas encontradas: %s",
            len(scanned),
            [p + 1 for p in scanned],
        )

    # POR QUE: Retornamos todas las escaneadas de la 2da mitad sin limite.
    # Los TYPE_2 son minoria (~30% del volumen) y el U-1A puede estar en
    # cualquier posicion entre las escaneadas. Mejor enviar de mas al LLM
    # (que ignora paginas irrelevantes) que cortar y perder el U-1A.
    return scanned
