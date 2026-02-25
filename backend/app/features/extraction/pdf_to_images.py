"""
Convierte paginas de PDF a imagenes PNG usando pypdfium2.
- Finalidad: Toma bytes de un PDF y convierte paginas especificas a imagenes
  base64 PNG para enviar a GPT-4o vision.
- Consume: config.py (PDF_DPI)
- Consumido por: service.py (pipeline de extraccion)
"""

import base64
import io

import pypdfium2 as pdfium

from app.config import get_settings

settings = get_settings()


def pdf_pages_to_base64(pdf_bytes: bytes, page_numbers: list[int]) -> list[str]:
    """Convierte paginas especificas de un PDF a imagenes base64.

    Args:
        pdf_bytes: Contenido del PDF en bytes.
        page_numbers: Lista de numeros de pagina (0-indexed).

    Returns:
        Lista de strings base64 de las imagenes PNG.
    """
    pdf = pdfium.PdfDocument(pdf_bytes)
    try:
        images_b64 = []
        for page_num in page_numbers:
            if page_num >= len(pdf):
                continue
            page = pdf[page_num]
            bitmap = page.render(scale=settings.PDF_DPI / 72)
            pil_image = bitmap.to_pil()

            buffer = io.BytesIO()
            pil_image.save(buffer, format="PNG")
            buffer.seek(0)
            images_b64.append(base64.b64encode(buffer.read()).decode("utf-8"))
        return images_b64
    finally:
        pdf.close()


def get_page_count(pdf_bytes: bytes) -> int:
    """Retorna el numero total de paginas del PDF."""
    pdf = pdfium.PdfDocument(pdf_bytes)
    try:
        return len(pdf)
    finally:
        pdf.close()
