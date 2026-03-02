"""
Cliente HTTP para Glide API (queryTables + mutateTables).
- Finalidad: Encapsula las llamadas REST a Glide con retry, backoff y column mapping.
  Provee funciones genericas query/mutate que el repository consume.
- Consume: config.py (GLIDE_APP_ID, GLIDE_API_TOKEN)
- Consumido por: glide/repository.py
"""

import logging
from typing import Any

import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

# --- Glide API ---
GLIDE_API_BASE = "https://api.glideapp.io/api/function"
MAX_MUTATIONS_PER_CALL = 500
MAX_RETRIES = 3
RETRY_BACKOFF_BASE = 2  # seconds

# --- Table IDs ---
TABLE_TANQUES = "native-table-dtJX4UJpeQHou0W1uTGP"
TABLE_DOCUMENTOS = "native-table-WCPGts1smiVKLdZGPCxT"

# --- Column mapping: nombre legible → codigo Glide ---
TANQUE_COLUMNS = {
    "serie": "Name",
    "ano_fabricacion": "1xfXM",
    "fabricante": "iP4yR",
    "asme_code_edition": "QXc1G",
    "mawp_psi": "2ZVOU",
    "hydro_test_pressure_psi": "fQhZU",
    "material_cuerpo": "C24xM",
    "espesor_cuerpo_mm": "ufC6j",
    "longitud_cuerpo_m": "WuXF8",
    "material_cabezales": "D2M9P",
    "diametro_interior_m": "m8GnR",
    "espesor_cabezales_mm": "j0BBy",
    "fecha_certificacion": "Kx76y",
}

DOCUMENTO_COLUMNS = {
    "tanque_row_id": "eYLsX",
    "pdf_urls": "jT8nO",
}

# Inverso: codigo Glide → nombre legible
_TANQUE_COLUMNS_INV = {v: k for k, v in TANQUE_COLUMNS.items()}
_DOCUMENTO_COLUMNS_INV = {v: k for k, v in DOCUMENTO_COLUMNS.items()}


def _headers() -> dict[str, str]:
    return {
        "Authorization": f"Bearer {settings.GLIDE_API_TOKEN}",
        "Content-Type": "application/json",
    }


async def _post_with_retry(endpoint: str, payload: dict) -> dict:
    """POST a Glide API con retry y backoff exponencial."""
    import asyncio

    url = f"{GLIDE_API_BASE}/{endpoint}"
    last_error = None

    for attempt in range(MAX_RETRIES):
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                response = await client.post(url, json=payload, headers=_headers())

            if response.status_code == 429:
                wait = RETRY_BACKOFF_BASE ** (attempt + 1)
                logger.warning("Glide rate limit (429), retry in %ds...", wait)
                await asyncio.sleep(wait)
                continue

            response.raise_for_status()
            return response.json()

        except httpx.HTTPStatusError as e:
            last_error = e
            logger.error(
                "Glide API error %d: %s",
                e.response.status_code,
                e.response.text[:300],
            )
            if e.response.status_code >= 500:
                wait = RETRY_BACKOFF_BASE ** (attempt + 1)
                await asyncio.sleep(wait)
                continue
            raise

        except httpx.RequestError as e:
            last_error = e
            logger.error("Glide connection error: %s", str(e))
            if attempt < MAX_RETRIES - 1:
                wait = RETRY_BACKOFF_BASE ** (attempt + 1)
                await asyncio.sleep(wait)
                continue

    raise RuntimeError(f"Glide API failed after {MAX_RETRIES} retries: {last_error}")


async def query_table(
    table_id: str,
    sql: str | None = None,
    params: list | None = None,
    utc: bool = True,
) -> list[dict]:
    """Consulta rows de una tabla en Glide.

    Args:
        table_id: ID de la tabla Glide (ej: native-table-xxx).
        sql: SQL opcional (SELECT * FROM "table" WHERE ...).
        params: Parametros para placeholders $1, $2, etc.
        utc: Si True, fechas en UTC.

    Returns:
        Lista de rows (dicts con column codes como keys).
    """
    if not settings.GLIDE_APP_ID or not settings.GLIDE_API_TOKEN:
        raise RuntimeError("GLIDE_APP_ID y GLIDE_API_TOKEN deben estar configurados")

    effective_sql = sql or f'SELECT * FROM "{table_id}"'
    query: dict[str, Any] = {"tableName": table_id, "sql": effective_sql, "utc": utc}
    if params:
        query["params"] = params

    all_rows: list[dict] = []
    continuation_token = None

    while True:
        if continuation_token:
            query["startAt"] = continuation_token

        payload = {"appID": settings.GLIDE_APP_ID, "queries": [query]}
        result = await _post_with_retry("queryTables", payload)

        rows = result[0].get("rows", []) if isinstance(result, list) else result.get("rows", [])
        all_rows.extend(rows)

        next_token = result[0].get("next") if isinstance(result, list) else result.get("next")
        if next_token:
            continuation_token = next_token
        else:
            break

    logger.info("Glide query on %s returned %d rows", table_id, len(all_rows))
    return all_rows


async def mutate_table(mutations: list[dict]) -> list[dict]:
    """Ejecuta mutaciones (add/set/delete) en Glide.

    Args:
        mutations: Lista de mutation objects con kind, tableName, columnValues, etc.
            Max 500 por llamada.

    Returns:
        Lista de resultados (uno por mutacion).
    """
    if not settings.GLIDE_APP_ID or not settings.GLIDE_API_TOKEN:
        raise RuntimeError("GLIDE_APP_ID y GLIDE_API_TOKEN deben estar configurados")

    if len(mutations) > MAX_MUTATIONS_PER_CALL:
        raise ValueError(f"Max {MAX_MUTATIONS_PER_CALL} mutations per call, got {len(mutations)}")

    payload = {"appID": settings.GLIDE_APP_ID, "mutations": mutations}
    result = await _post_with_retry("mutateTables", payload)
    logger.info("Glide mutate: %d mutations sent", len(mutations))
    return result


def to_glide_columns(data: dict, column_map: dict) -> dict:
    """Convierte dict con nombres legibles a column codes de Glide.

    Ejemplo: {"serie": "M123"} → {"Name": "M123"}
    """
    glide_data = {}
    for key, value in data.items():
        if key in column_map and value is not None:
            glide_data[column_map[key]] = str(value)
    return glide_data


def from_glide_columns(row: dict, column_map_inv: dict) -> dict:
    """Convierte row de Glide (column codes) a nombres legibles.

    Ejemplo: {"Name": "M123", "$rowID": "row-xxx"} → {"serie": "M123", "row_id": "row-xxx"}
    """
    result: dict[str, Any] = {}
    if "$rowID" in row:
        result["row_id"] = row["$rowID"]
    for code, name in column_map_inv.items():
        if code in row:
            result[name] = row[code]
    return result
