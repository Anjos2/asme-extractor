"""
Envio de imagenes de PDF al LLM vision y parseo de respuesta JSON.
- Finalidad: Orquesta la llamada a OpenAI vision API (gpt-5-mini por default)
  con imagenes base64, parsea el JSON resultante y genera warnings por campos faltantes.
- Consume: prompts.py (textos de prompt), config.py (API key, modelo), schemas.py (ExtractionResult)
- Consumido por: service.py (orquestacion de extraccion)
"""

import json
import logging

from openai import AsyncOpenAI

from app.config import get_settings
from app.features.extraction.prompts import SYSTEM_PROMPT, TYPE_1_PROMPT, TYPE_2_PROMPT
from app.schemas import ExtractionResult

logger = logging.getLogger(__name__)
settings = get_settings()


def _build_messages(images_b64: list[str], pdf_type: str) -> list[dict]:
    """Construye mensajes para la API de OpenAI con imagenes."""
    prompt = TYPE_1_PROMPT if pdf_type == "TYPE_1" else TYPE_2_PROMPT

    content: list[dict] = [{"type": "text", "text": prompt}]
    for img_b64 in images_b64:
        content.append(
            {
                "type": "image_url",
                "image_url": {
                    "url": f"data:image/png;base64,{img_b64}",
                    "detail": "high",
                },
            }
        )

    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": content},
    ]


def _clean_json_response(text: str) -> str:
    """Limpia la respuesta del LLM para obtener JSON puro."""
    text = text.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        lines = lines[1:]  # Remove ```json
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines)
    return text.strip()


async def extract_with_llm(
    images_b64: list[str], pdf_type: str
) -> ExtractionResult:
    """Envia imagenes a GPT-4o y retorna datos estructurados.

    Args:
        images_b64: Lista de imagenes en base64.
        pdf_type: 'TYPE_1' o 'TYPE_2'.

    Returns:
        ExtractionResult con los campos extraidos.
    """
    if not settings.OPENAI_API_KEY:
        raise RuntimeError("OPENAI_API_KEY no configurada")

    client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
    messages = _build_messages(images_b64, pdf_type)

    response = await client.chat.completions.create(
        model=settings.OPENAI_MODEL,
        messages=messages,
        max_tokens=2000,
        temperature=0,
    )

    raw_content = response.choices[0].message.content
    logger.info("LLM raw response length: %d chars", len(raw_content))

    clean_json = _clean_json_response(raw_content)

    try:
        data = json.loads(clean_json)
    except json.JSONDecodeError as e:
        logger.error("Failed to parse LLM JSON: %s\nRaw: %s", e, raw_content[:500])
        return ExtractionResult(
            warnings=[f"Error parseando respuesta del LLM: {str(e)}"]
        )

    warnings = []
    expected_fields = [
        "fabricante", "asme_code_edition", "mawp_psi",
        "hydro_test_pressure_psi", "material_cuerpo", "espesor_cuerpo_mm",
        "longitud_cuerpo_m", "diametro_interior_m", "material_cabezales",
        "espesor_cabezales_mm", "fecha_certificacion",
    ]
    for field in expected_fields:
        if data.get(field) is None:
            warnings.append(f"Campo '{field}' no encontrado en el PDF")

    data["warnings"] = warnings
    return ExtractionResult(**data)
