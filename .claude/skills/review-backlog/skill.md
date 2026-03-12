---
name: review-backlog
description: Analiza el backlog de extracciones ASME para detectar patrones de fallo y sugerir mejoras al pipeline (prompts, validators, service). Consulta GET /api/backlog y /api/backlog/summary en el servidor de produccion.
allowed-tools: Read, Edit, Glob, Grep, Bash, WebFetch, Agent
---

# Skill: Review Backlog (Analisis de Extracciones ASME)

## Cuando Usar

- Cuando el usuario diga: "review backlog", "revisar backlog", "mejorar extraccion", "como van las extracciones"
- Periodicamente despues de un batch de PDFs procesados
- Cuando se detecten fallos recurrentes en produccion

## Prerequisitos

Leer las credenciales del servidor desde `memoria/servidor.yaml`:
- **URL base**: valor de `hostinger.asme_extractor.url` (ej: `https://visionaiveahome.itelcore.org`)
- **API key**: valor de `credenciales.asme_api_key`

## Flujo (4 pasos)

### Paso 1: Obtener Datos del Backlog

Hacer 2 requests al servidor de produccion:

```bash
# Summary (estadisticas agregadas)
curl -s -H "X-API-Key: {API_KEY}" "{URL_BASE}/api/backlog/summary"

# Ultimas 100 entradas (para analisis detallado)
curl -s -H "X-API-Key: {API_KEY}" "{URL_BASE}/api/backlog?limit=100"
```

Si el servidor no responde o el backlog esta vacio, informar al usuario y sugerir procesar PDFs primero.

### Paso 2: Analizar Patrones

Con los datos obtenidos, analizar:

**2a. Tasa de exito:**
- % de extracciones "ok" vs "incomplete" vs "failed"
- Si la tasa de "ok" es < 80%, hay un problema sistematico

**2b. Campos problematicos (`top_null_fields`):**
- Identificar los 5 campos que mas fallan
- Para cada campo, buscar en `backend/app/features/extraction/prompts.py` como se le pide al LLM que lo extraiga
- Evaluar si el prompt es suficientemente claro/especifico

**2c. Metodos U-1A (`by_method`):**
- % text vs scanned vs brute_force vs direct
- Si brute_force > 30%, hay muchos PDFs donde el U-1A no se detecta → revisar `validators.py`
- Si scanned > 40%, los PDFs de este cliente tienden a ser escaneados

**2d. Tiempos de extraccion:**
- Promedio de `extraction_time_seconds`
- Outliers (>60s) → probablemente retries o PDFs muy grandes

**2e. Patrones por filename:**
- Agrupar errores por prefijo de filename para detectar lotes problematicos
- PDFs del mismo lote tienden a tener el mismo formato

### Paso 3: Generar Recomendaciones

Basado en el analisis, generar recomendaciones concretas:

**Para campos con alta tasa de null:**
- Proponer mejoras especificas al prompt (que keyword buscar, que formato esperar)
- Revisar si el campo existe en todos los tipos de PDF o solo en algunos

**Para alta tasa de brute_force:**
- Revisar si `find_u1a_page()` tiene keywords suficientes
- Proponer agregar nuevos keywords basados en los PDFs que fallan
- Considerar si `find_scanned_pages()` necesita ajustar su umbral de texto

**Para extracciones lentas:**
- Verificar si el retry esta activandose demasiado (bajar umbral?)
- Considerar si se estan enviando demasiadas paginas al LLM

**Formato de recomendacion:**
```
## Hallazgo: [descripcion del patron]
- **Evidencia**: X de Y extracciones (Z%) muestran este patron
- **Causa probable**: [hipotesis]
- **Archivo afectado**: `backend/app/features/extraction/{archivo}.py`
- **Fix sugerido**: [cambio concreto con codigo]
- **Impacto esperado**: [que mejoraria]
```

### Paso 4: Preguntar Antes de Implementar

Presentar todas las recomendaciones al usuario y preguntar:
1. Cuales quiere implementar
2. Si quiere ver mas detalle de alguna
3. Si quiere que se implementen automaticamente (con `/file-audit` por archivo)

**NO implementar cambios sin aprobacion explicita.**

## Notas

- El backlog solo registra extracciones exitosas (no errores HTTP). Los errores HTTP se ven en los logs del servidor, no en el backlog.
- Las categorias son: ok (10+ campos de 14), incomplete (5-9), failed (<5)
- El campo `u1a_method` indica como se encontro el U-1A: "direct" (TYPE_1), "text" (encontrado por texto), "scanned" (paginas sin texto), "brute_force" (ultimas N paginas), "retry_brute_force" (retry mejoro resultado)
