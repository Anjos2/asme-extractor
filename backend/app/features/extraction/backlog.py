"""
Logging estructurado de extracciones para analisis y auto-mejora.
- Finalidad: Registra cada extraccion en un archivo JSONL con metadata del proceso
  (tipo PDF, metodo U-1A, paginas enviadas, campos extraidos/null, retry, tiempo).
  Permite analizar patrones de fallo y mejorar el pipeline iterativamente.
- Consume: config.py (BACKLOG_PATH, BACKLOG_MAX_ENTRIES)
- Consumido por: service.py (log_extraction al final de extract_from_pdf),
  router.py (get_backlog, get_backlog_summary)
"""

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from app.config import get_settings

logger = logging.getLogger(__name__)

_settings = get_settings()
BACKLOG_PATH = Path(_settings.BACKLOG_PATH)
BACKLOG_MAX_ENTRIES = _settings.BACKLOG_MAX_ENTRIES


def log_extraction(data: dict) -> None:
    """Escribe una entrada de extraccion al backlog JSONL.

    Si no puede escribir (permisos, disco lleno), solo loguea warning
    sin interrumpir el flujo de extraccion.
    """
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        **data,
    }

    try:
        BACKLOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(BACKLOG_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False, default=str) + "\n")
        _rotate_if_needed()
    except Exception as e:
        logger.warning("No se pudo escribir al backlog: %s", e)


def _rotate_if_needed() -> None:
    """Mantiene el backlog en <= BACKLOG_MAX_ENTRIES lineas.

    Lee todas las lineas, conserva las ultimas N, y reescribe el archivo.
    Solo ejecuta la rotacion cuando el archivo supera el limite.
    """
    try:
        lines = BACKLOG_PATH.read_text(encoding="utf-8").splitlines()
        if len(lines) <= BACKLOG_MAX_ENTRIES:
            return
        trimmed = lines[-BACKLOG_MAX_ENTRIES:]
        BACKLOG_PATH.write_text("\n".join(trimmed) + "\n", encoding="utf-8")
        logger.info("Backlog rotado: %d → %d entradas", len(lines), len(trimmed))
    except Exception as e:
        logger.warning("No se pudo rotar el backlog: %s", e)


def read_backlog(limit: int = 50, category: str | None = None) -> list[dict]:
    """Lee las ultimas N entradas del backlog, opcionalmente filtradas por categoria."""
    if not BACKLOG_PATH.exists():
        return []

    try:
        lines = BACKLOG_PATH.read_text(encoding="utf-8").splitlines()
    except Exception as e:
        logger.warning("No se pudo leer el backlog: %s", e)
        return []

    entries = []
    for line in reversed(lines):
        if not line.strip():
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        if category and entry.get("category") != category:
            continue
        entries.append(entry)
        if len(entries) >= limit:
            break

    return entries


def get_backlog_summary() -> dict:
    """Genera estadisticas del backlog: totales, por categoria, campos mas fallidos."""
    if not BACKLOG_PATH.exists():
        return {"total": 0, "by_category": {}, "top_null_fields": [], "by_method": {}}

    try:
        lines = BACKLOG_PATH.read_text(encoding="utf-8").splitlines()
    except Exception as e:
        logger.warning("No se pudo leer el backlog: %s", e)
        return {"total": 0, "by_category": {}, "top_null_fields": [], "by_method": {}}

    total = 0
    by_category: dict[str, int] = {}
    by_method: dict[str, int] = {}
    null_field_counts: dict[str, int] = {}

    for line in lines:
        if not line.strip():
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue

        total += 1
        cat = entry.get("category", "unknown")
        by_category[cat] = by_category.get(cat, 0) + 1

        method = entry.get("u1a_method", "unknown")
        by_method[method] = by_method.get(method, 0) + 1

        for field in entry.get("fields_null", []):
            null_field_counts[field] = null_field_counts.get(field, 0) + 1

    top_null = sorted(null_field_counts.items(), key=lambda x: x[1], reverse=True)[:10]

    return {
        "total": total,
        "by_category": by_category,
        "top_null_fields": [{"field": f, "count": c} for f, c in top_null],
        "by_method": by_method,
    }
