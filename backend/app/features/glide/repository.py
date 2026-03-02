"""
Repositorio CRUD para tanques y documentos en Glide.
- Finalidad: Operaciones de negocio sobre Glide (buscar por serie, crear, actualizar,
  listar tanques sin datos LIBRO DIGITAL, obtener documentos por tanque).
- Consume: glide/client.py (query_table, mutate_table, column mapping, table IDs)
- Consumido por: extraction/service.py, extraction/router.py
"""

import logging

from app.features.glide.client import (
    DOCUMENTO_COLUMNS,
    TABLE_DOCUMENTOS,
    TABLE_TANQUES,
    TANQUE_COLUMNS,
    _DOCUMENTO_COLUMNS_INV,
    _TANQUE_COLUMNS_INV,
    from_glide_columns,
    mutate_table,
    query_table,
    to_glide_columns,
)

logger = logging.getLogger(__name__)


async def get_tanque_by_serie(serie: str) -> dict | None:
    """Busca un tanque por numero de serie (campo Name).

    Returns:
        Dict con nombres legibles + row_id, o None si no existe.
    """
    sql = f'SELECT * FROM "{TABLE_TANQUES}" WHERE "Name" = $1 LIMIT 1'
    rows = await query_table(TABLE_TANQUES, sql=sql, params=[serie])
    if not rows:
        return None
    return from_glide_columns(rows[0], _TANQUE_COLUMNS_INV)


async def create_tanque(data: dict) -> str:
    """Crea un tanque nuevo en Glide.

    Args:
        data: Dict con nombres legibles (serie, fabricante, mawp_psi, etc.)

    Returns:
        rowID del tanque creado.
    """
    glide_data = to_glide_columns(data, TANQUE_COLUMNS)
    if not glide_data:
        raise ValueError("No hay datos validos para crear el tanque")

    mutation = {
        "kind": "add-row-to-table",
        "tableName": TABLE_TANQUES,
        "columnValues": glide_data,
    }
    result = await mutate_table([mutation])

    row_id = result[0] if result and isinstance(result[0], str) else None
    if not row_id:
        raise RuntimeError(f"Glide no retorno rowID al crear tanque: {result}")

    logger.info("Tanque creado en Glide: serie=%s, rowID=%s", data.get("serie"), row_id)
    return row_id


async def update_tanque(row_id: str, data: dict) -> bool:
    """Actualiza campos de un tanque existente en Glide.

    Args:
        row_id: $rowID del tanque en Glide.
        data: Dict con nombres legibles (solo campos a actualizar).

    Returns:
        True si la mutacion se envio correctamente.
    """
    glide_data = to_glide_columns(data, TANQUE_COLUMNS)
    if not glide_data:
        logger.warning("update_tanque: no hay datos validos para actualizar")
        return False

    mutation = {
        "kind": "set-columns-in-row",
        "tableName": TABLE_TANQUES,
        "rowID": row_id,
        "columnValues": glide_data,
    }
    await mutate_table([mutation])
    logger.info("Tanque actualizado en Glide: rowID=%s, campos=%s", row_id, list(glide_data.keys()))
    return True


async def list_tanques() -> list[dict]:
    """Lista todos los tanques desde Glide.

    Returns:
        Lista de dicts con nombres legibles + row_id.
    """
    rows = await query_table(TABLE_TANQUES)
    return [from_glide_columns(row, _TANQUE_COLUMNS_INV) for row in rows]


async def get_tanques_sin_libro_digital() -> list[dict]:
    """Lista tanques que tienen serie pero campos LIBRO DIGITAL vacios.

    Un tanque sin libro digital es aquel donde el campo fabricante (iP4yR)
    no tiene valor. Glide no retorna campos vacios, asi que filtramos en Python.

    Returns:
        Lista de dicts con nombres legibles + row_id.
    """
    all_tanques = await list_tanques()
    return [t for t in all_tanques if t.get("serie") and not t.get("fabricante")]


async def get_documentos_by_tanque(tanque_row_id: str) -> list[dict]:
    """Obtiene documentos vinculados a un tanque.

    Args:
        tanque_row_id: $rowID del tanque en Glide.

    Returns:
        Lista de dicts con pdf_urls y row_id.
    """
    col_fk = DOCUMENTO_COLUMNS["tanque_row_id"]
    sql = f'SELECT * FROM "{TABLE_DOCUMENTOS}" WHERE "{col_fk}" = $1'
    rows = await query_table(TABLE_DOCUMENTOS, sql=sql, params=[tanque_row_id])
    return [from_glide_columns(row, _DOCUMENTO_COLUMNS_INV) for row in rows]


async def get_all_documentos() -> list[dict]:
    """Lista todos los documentos desde Glide.

    Returns:
        Lista de dicts con tanque_row_id, pdf_urls, row_id.
    """
    rows = await query_table(TABLE_DOCUMENTOS)
    return [from_glide_columns(row, _DOCUMENTO_COLUMNS_INV) for row in rows]
