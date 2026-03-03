#!/usr/bin/env python3
"""
Migracion one-time: Azure SQL -> Glide.
- Finalidad: Migrar 37 tanques y ~523 certificados de Azure SQL a Glide.
- Consume: Azure SQL (prd-srvdb-veahome) via pymssql, Glide API (mutateTables) via httpx.
- Uso:
    # Dry run con 3 tanques (sin escribir a Glide):
    python migrate_azure_to_glide.py --dry-run --limit 3

    # Migracion real de todos:
    python migrate_azure_to_glide.py

    # Solo tanques, sin documentos:
    python migrate_azure_to_glide.py --tanques-only
"""

import argparse
import asyncio
import logging
import os
import sys
import time
from urllib.parse import unquote

try:
    import pymssql
except ImportError:
    print("ERROR: pymssql no instalado. Ejecutar: pip install pymssql")
    sys.exit(1)

try:
    import httpx
except ImportError:
    print("ERROR: httpx no instalado. Ejecutar: pip install httpx")
    sys.exit(1)


# ─── Configuration (env vars with sensible defaults) ───────────────────────

AZURE_SERVER = os.getenv("AZURE_SQL_SERVER", "prd-srvdb-veahome.database.windows.net")
AZURE_DB = os.getenv("AZURE_SQL_DB", "prd-srvdb-veahome")
AZURE_USER = os.getenv("AZURE_SQL_USER", "dba-veahome-prd")
AZURE_PASS = os.getenv("AZURE_SQL_PASS", "")

GLIDE_APP_ID = os.getenv("GLIDE_APP_ID", "HUzZNoLSSNKs7DC6hXs9")
GLIDE_API_TOKEN = os.getenv("GLIDE_API_TOKEN", "")
GLIDE_API_BASE = "https://api.glideapp.io/api/function"

# ─── Glide Table IDs (same as backend/app/features/glide/client.py) ────────

TABLE_TANQUES = "native-table-dtJX4UJpeQHou0W1uTGP"
TABLE_DOCUMENTOS = "native-table-WCPGts1smiVKLdZGPCxT"

# ─── Column mapping: Azure -> Glide ───────────────────────────────────────
# Solo serie y ano_fabricacion vienen de Azure.
# Los campos tecnicos ASME (MAWP, materiales, espesores) los llena el extractor.

TANQUE_GLIDE_MAP = {
    "serie": "Name",
    "ano_fabricacion": "1xfXM",
}

DOCUMENTO_GLIDE_MAP = {
    "tanque_row_id": "eYLsX",
    "pdf_urls": "jT8nO",
}

# ─── Logging ───────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("migrate")


# ═══════════════════════════════════════════════════════════════════════════
# Azure SQL
# ═══════════════════════════════════════════════════════════════════════════


def connect_azure() -> pymssql.Connection:
    """Conectar a Azure SQL Server."""
    if not AZURE_PASS:
        raise RuntimeError(
            "AZURE_SQL_PASS no configurado. "
            "Usar: export AZURE_SQL_PASS='<password>'"
        )
    log.info("Conectando a Azure SQL: %s/%s ...", AZURE_SERVER, AZURE_DB)
    conn = pymssql.connect(
        server=AZURE_SERVER,
        database=AZURE_DB,
        user=AZURE_USER,
        password=AZURE_PASS,
        login_timeout=30,
    )
    log.info("Conexion OK")
    return conn


def query_tanques(conn: pymssql.Connection) -> list[dict]:
    """Obtener tanques de Azure SQL.

    JOIN components + component_attributes WHERE type='TANQUE'.
    Retorna: component_id, serie, capacidad, ano_fabricacion, location_id.
    """
    sql = """
    SELECT ca.component_id,
           ca.column_name_1 AS serie,
           ca.column_name_2 AS capacidad,
           ca.column_name_3 AS ano_fabricacion,
           ca.column_name_4 AS fecha_venc_insp,
           ca.column_name_5 AS fecha_venc_ext,
           c.location_id
    FROM components c
    INNER JOIN component_attributes ca ON ca.component_id = c.Id
    WHERE c.type = 'TANQUE'
    ORDER BY ca.column_name_1
    """
    cursor = conn.cursor(as_dict=True)
    cursor.execute(sql)
    rows = cursor.fetchall()
    log.info("Azure: %d tanques encontrados", len(rows))
    return rows


def query_documentos(conn: pymssql.Connection) -> list[dict]:
    """Obtener certificados del tanque de Azure SQL.

    Retorna: id, location_id, name, storage_url.
    """
    sql = """
    SELECT id, location_id, name, storage_url
    FROM documents
    WHERE group_name = 'CERTIFICADOS DEL TANQUE'
    ORDER BY name
    """
    cursor = conn.cursor(as_dict=True)
    cursor.execute(sql)
    rows = cursor.fetchall()
    log.info("Azure: %d certificados encontrados", len(rows))
    return rows


# ═══════════════════════════════════════════════════════════════════════════
# Glide API (self-contained, no backend imports)
# ═══════════════════════════════════════════════════════════════════════════


async def glide_post(endpoint: str, payload: dict) -> dict:
    """POST a Glide API con retry y backoff."""
    url = f"{GLIDE_API_BASE}/{endpoint}"
    headers = {
        "Authorization": f"Bearer {GLIDE_API_TOKEN}",
        "Content-Type": "application/json",
    }

    for attempt in range(3):
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(url, json=payload, headers=headers)

        if resp.status_code == 429 or resp.status_code >= 500:
            wait = 2 ** (attempt + 1)
            log.warning("Glide API %d, reintentando en %ds...", resp.status_code, wait)
            await asyncio.sleep(wait)
            continue

        if resp.status_code >= 400:
            log.error("Glide API %d: %s", resp.status_code, resp.text[:300])

        resp.raise_for_status()
        return resp.json()

    raise RuntimeError("Glide API fallo despues de 3 reintentos")


async def glide_query_all(table_id: str) -> list[dict]:
    """Obtener todas las rows de una tabla Glide (con paginacion)."""
    all_rows: list[dict] = []
    continuation = None

    while True:
        query: dict = {"tableName": table_id, "utc": True}
        if continuation:
            query["startAt"] = continuation

        payload = {"appID": GLIDE_APP_ID, "queries": [query]}
        result = await glide_post("queryTables", payload)

        rows = result[0].get("rows", []) if isinstance(result, list) else result.get("rows", [])
        all_rows.extend(rows)

        next_token = result[0].get("next") if isinstance(result, list) else result.get("next")
        if next_token:
            continuation = next_token
        else:
            break

    return all_rows


async def glide_add_row(table_id: str, column_values: dict) -> str | None:
    """Agregar una row a tabla Glide. Retorna rowID."""
    mutation = {
        "kind": "add-row-to-table",
        "tableName": table_id,
        "columnValues": column_values,
    }
    payload = {"appID": GLIDE_APP_ID, "mutations": [mutation]}
    result = await glide_post("mutateTables", payload)

    if result and isinstance(result, list) and result[0]:
        return result[0]
    return None


async def glide_update_row(table_id: str, row_id: str, column_values: dict) -> bool:
    """Actualizar columnas de una row existente en Glide."""
    mutation = {
        "kind": "set-columns-in-row",
        "tableName": table_id,
        "rowID": row_id,
        "columnValues": column_values,
    }
    payload = {"appID": GLIDE_APP_ID, "mutations": [mutation]}
    await glide_post("mutateTables", payload)
    return True


# ═══════════════════════════════════════════════════════════════════════════
# Document matching (deduplicacion por serie en URL)
# ═══════════════════════════════════════════════════════════════════════════


def extract_serie_from_url(url: str) -> str | None:
    """Extraer serie del tanque del path de la URL de Azure Blob.

    Pattern: .../CERTIFICADOS%20DEL%20TANQUE/{serie}/{year}/{filename}
    Ejemplo: .../CERTIFICADOS%20DEL%20TANQUE/M1209340/2022/M1209340.pdf
    """
    decoded = unquote(url)
    marker = "CERTIFICADOS DEL TANQUE/"
    idx = decoded.find(marker)
    if idx < 0:
        return None
    after = decoded[idx + len(marker):]
    parts = after.split("/")
    return parts[0] if parts and parts[0] else None


def match_docs_to_tanques(
    tanques: list[dict], docs: list[dict]
) -> dict[str, list[dict]]:
    """Matchear documentos a tanques extrayendo serie del URL path.

    Deduplica correctamente (vs JOIN por location_id que produce duplicados).
    Retorna: {serie: [doc1, doc2, ...]}
    """
    serie_set = {t["serie"] for t in tanques if t.get("serie")}
    result: dict[str, list[dict]] = {serie: [] for serie in serie_set}
    seen_doc_ids: set = set()
    unmatched = 0

    for doc in docs:
        doc_id = doc.get("id")
        if doc_id in seen_doc_ids:
            continue
        seen_doc_ids.add(doc_id)

        url = doc.get("storage_url", "")
        serie = extract_serie_from_url(url)

        if serie and serie in result:
            result[serie].append(doc)
        else:
            unmatched += 1
            log.debug("Doc sin match: serie_url=%s, name=%s", serie, doc.get("name"))

    matched_total = sum(len(v) for v in result.values())
    log.info(
        "Matching: %d docs unicos -> %d matched a tanques, %d sin match",
        len(seen_doc_ids), matched_total, unmatched,
    )

    return result


# ═══════════════════════════════════════════════════════════════════════════
# Migration logic
# ═══════════════════════════════════════════════════════════════════════════


async def migrate(args: argparse.Namespace) -> None:
    """Ejecutar la migracion Azure SQL -> Glide."""
    if not GLIDE_API_TOKEN:
        raise RuntimeError(
            "GLIDE_API_TOKEN no configurado. "
            "Usar: export GLIDE_API_TOKEN='<token>'"
        )

    t_start = time.time()

    # ── 1. Conectar a Azure SQL y extraer datos ──
    conn = connect_azure()
    try:
        azure_tanques = query_tanques(conn)
        azure_docs = query_documentos(conn) if not args.tanques_only else []
    finally:
        conn.close()
        log.info("Conexion Azure cerrada")

    # ── 2. Aplicar limite si especificado ──
    if args.limit:
        azure_tanques = azure_tanques[: args.limit]
        log.info("Limitado a %d tanques (--limit %d)", len(azure_tanques), args.limit)

    # ── 3. Matchear documentos a tanques por serie en URL ──
    if not args.tanques_only:
        docs_by_serie = match_docs_to_tanques(azure_tanques, azure_docs)
    else:
        docs_by_serie = {}

    # ── 4. Obtener tanques existentes en Glide ──
    log.info("Consultando tanques existentes en Glide...")
    existing_rows = await glide_query_all(TABLE_TANQUES)
    existing_series: dict[str, dict] = {
        row.get("Name"): row
        for row in existing_rows
        if row.get("Name")
    }
    log.info("Glide tiene %d tanques existentes", len(existing_series))

    # ── 5. Obtener documentos existentes en Glide (para evitar duplicados) ──
    existing_doc_urls: set[str] = set()
    if not args.tanques_only:
        log.info("Consultando documentos existentes en Glide...")
        existing_doc_rows = await glide_query_all(TABLE_DOCUMENTOS)
        for row in existing_doc_rows:
            url = row.get(DOCUMENTO_GLIDE_MAP["pdf_urls"], "")
            if isinstance(url, list):
                existing_doc_urls.update(url)
            elif url:
                existing_doc_urls.add(url)
        log.info("Glide tiene %d documentos existentes", len(existing_doc_urls))

    # ── 6. Migrar ──
    stats = {
        "tanques_created": 0,
        "tanques_updated": 0,
        "tanques_skipped": 0,
        "docs_created": 0,
        "docs_skipped": 0,
        "errors": 0,
    }

    for i, tanque in enumerate(azure_tanques, 1):
        serie = (tanque.get("serie") or "").strip()

        if not serie:
            log.warning(
                "Tanque sin serie (component_id=%s), saltando",
                tanque.get("component_id"),
            )
            stats["errors"] += 1
            continue

        log.info("── [%d/%d] Tanque: %s ──", i, len(azure_tanques), serie)

        # ── 6a. Crear, actualizar o saltar tanque ──
        if serie in existing_series:
            glide_row = existing_series[serie]
            tanque_row_id = glide_row.get("$rowID")

            # Buscar columnas vacías en Glide que Azure sí tiene
            updates: dict[str, str] = {}
            if tanque.get("ano_fabricacion") and not glide_row.get(TANQUE_GLIDE_MAP["ano_fabricacion"]):
                updates[TANQUE_GLIDE_MAP["ano_fabricacion"]] = str(tanque["ano_fabricacion"])

            if updates:
                if args.dry_run:
                    log.info("  DRY-RUN: actualizaria %s (rowID=%s) -> %s", serie, tanque_row_id, updates)
                else:
                    try:
                        await glide_update_row(TABLE_TANQUES, tanque_row_id, updates)
                        log.info("  UPDATED: %s (rowID=%s) -> %s", serie, tanque_row_id, updates)
                        await asyncio.sleep(0.5)
                    except Exception as e:
                        log.error("  ERROR actualizando tanque %s: %s", serie, e)
                        stats["errors"] += 1
                        continue
                stats["tanques_updated"] += 1
            else:
                log.info("  SKIP: %s ya completo en Glide (rowID=%s)", serie, tanque_row_id)
                stats["tanques_skipped"] += 1
        else:
            glide_data: dict[str, str] = {}
            glide_data[TANQUE_GLIDE_MAP["serie"]] = serie
            if tanque.get("ano_fabricacion"):
                glide_data[TANQUE_GLIDE_MAP["ano_fabricacion"]] = str(
                    tanque["ano_fabricacion"]
                )

            if args.dry_run:
                log.info("  DRY-RUN: crearia tanque %s -> %s", serie, glide_data)
                tanque_row_id = f"dry-run-{serie}"
            else:
                try:
                    tanque_row_id = await glide_add_row(TABLE_TANQUES, glide_data)
                    log.info("  CREATED: %s -> rowID=%s", serie, tanque_row_id)
                    existing_series[serie] = {"$rowID": tanque_row_id}
                    await asyncio.sleep(0.5)
                except Exception as e:
                    log.error("  ERROR creando tanque %s: %s", serie, e)
                    stats["errors"] += 1
                    continue

            stats["tanques_created"] += 1

        # ── 6b. Migrar documentos de este tanque ──
        if args.tanques_only:
            continue

        tanque_docs = docs_by_serie.get(serie, [])
        if not tanque_docs:
            log.info("  Sin certificados para este tanque")
            continue

        log.info("  %d certificados a migrar", len(tanque_docs))

        for doc in tanque_docs:
            url = doc.get("storage_url", "")
            name = doc.get("name", "?")

            if url in existing_doc_urls:
                log.info("    SKIP doc: %s (ya existe)", name)
                stats["docs_skipped"] += 1
                continue

            doc_data = {
                DOCUMENTO_GLIDE_MAP["tanque_row_id"]: tanque_row_id,
                DOCUMENTO_GLIDE_MAP["pdf_urls"]: url,
            }

            if args.dry_run:
                log.info("    DRY-RUN: crearia doc %s", name)
            else:
                try:
                    doc_row_id = await glide_add_row(TABLE_DOCUMENTOS, doc_data)
                    log.info("    DOC: %s -> rowID=%s", name, doc_row_id)
                    existing_doc_urls.add(url)
                    await asyncio.sleep(0.3)
                except Exception as e:
                    log.error("    ERROR creando doc %s: %s", name, e)
                    stats["errors"] += 1
                    continue

            stats["docs_created"] += 1

    # ── 7. Resumen ──
    elapsed = time.time() - t_start
    log.info("=" * 60)
    log.info("MIGRACION COMPLETADA%s", " (DRY RUN)" if args.dry_run else "")
    log.info("Tanques: %d creados, %d actualizados, %d sin cambios (skip)", stats["tanques_created"], stats["tanques_updated"], stats["tanques_skipped"])
    log.info("Documentos: %d creados, %d existentes (skip)", stats["docs_created"], stats["docs_skipped"])
    log.info("Errores: %d", stats["errors"])
    log.info("Tiempo: %.1f segundos", elapsed)
    log.info("=" * 60)


# ═══════════════════════════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════════════════════════


def main():
    parser = argparse.ArgumentParser(
        description="Migrar tanques y certificados de Azure SQL a Glide",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Ejemplos:
  # Ver que se haria sin escribir nada (3 tanques):
  python migrate_azure_to_glide.py --dry-run --limit 3

  # Migrar solo tanques (sin documentos):
  python migrate_azure_to_glide.py --tanques-only

  # Migracion completa:
  python migrate_azure_to_glide.py

Variables de entorno requeridas:
  AZURE_SQL_PASS     Password de Azure SQL
  GLIDE_API_TOKEN    Token de la API de Glide
        """,
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Mostrar que se haria sin escribir a Glide",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Limitar a N tanques (0 = todos). Para testing: --limit 3",
    )
    parser.add_argument(
        "--tanques-only",
        action="store_true",
        help="Solo migrar tanques, sin documentos",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Logging verbose (DEBUG)",
    )
    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    asyncio.run(migrate(args))


if __name__ == "__main__":
    main()
