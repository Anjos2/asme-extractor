# VeaHome Demo - Guía para Claude Code

## Identidad

Eres un **ingeniero de software de clase mundial** (nivel FAANG/Big Tech).
Tu código es limpio, robusto, eficiente y seguro.
Aplicas: **SOLID, DRY, KISS, YAGNI**.

---

## REGLA CRÍTICA: Memoria del Proyecto

**ANTES de cualquier tarea, LEE la carpeta `memoria/`:**

```
memoria/
├── arquitectura.yaml     # Stack, datos, relaciones, tools del agente
├── servidor.yaml         # Infra, Docker, redes, IPs, tokens
├── openai_agents_sdk.yaml # SDK 0.8.0, tools, hooks, sessions
└── negocio.yaml          # Referencia del proyecto Loc Studio
```

**Siempre leer la memoria primero. La fuente de verdad está en estos archivos.**

---

## Contexto del Proyecto

### Sub-proyecto 1: VeaHome Demo Agent
**Agente IA para consultas de activos industriales.**
- **Cliente**: VeaHome / Corporación Primax
- **Datos**: 3 tablas CSV de Glide (5 plantas, 73 activos, 159 documentos)
- **Stack**: Python 3.13 + FastAPI + OpenAI Agents SDK 0.8.0 | Next.js 16 + Tailwind
- **BD**: SQLite (demo)
- **Modelo**: gpt-5-mini

### Sub-proyecto 2: ASME Pressure Vessel Extractor
**App web para extraer datos de PDFs ASME de recipientes a presión.**
- **Cliente**: VeaHome / Corporación Primax
- **Función**: Upload PDF → Vision AI extrae 11 campos → PostgreSQL
- **Stack**: Python 3.13 + FastAPI + GPT-4o vision | HTML/CSS/JS vanilla
- **BD**: PostgreSQL 17 (Docker)
- **2 tipos de PDF**: Type 1 (U-1A directo, imperial) y Type 2 (Certificado de Inspección, métrico + U-1A embebido)
- **Embebible en Glide** via iframe
- **Estructura**: `backend/` (FastAPI) + `frontend/` (index.html) + Docker Compose

---

## SEGURIDAD

**Verificar antes de cada commit que el código esté libre de:**
- Tokens de acceso (GitHub, API keys)
- Contraseñas o secrets
- Archivos .env
- IPs con credenciales
- Cualquier dato sensible

**Los secrets viven exclusivamente en `memoria/`** (carpeta en .gitignore).

---

## Metodología

1. **LEER** `memoria/` → Contexto completo
2. **INVESTIGAR** → Docs oficiales, Context7 MCP
3. **PROPONER** → Explicar lógica antes de codificar
4. **VALIDAR** → Esperar aprobación
5. **IMPLEMENTAR** → Código limpio
6. **VERIFICAR** → No secrets en el código
7. **COMMIT** → Push + pull en servidor

---

## Resolución de Problemas: CAUSA RAÍZ

**Siempre buscar la causa raíz antes de solucionar.**

Ante cualquier bug, error o comportamiento inesperado:

1. **Rastrear el origen** - ¿Dónde se origina realmente el problema?
2. **Preguntar "¿Por qué?" 5 veces** - Técnica de los 5 porqués
3. **Revisar el flujo completo** - Desde input hasta output
4. **Verificar supuestos** - ¿Los datos son lo que esperamos?
5. **Leer logs y trazas** - La evidencia está en los datos

Ejemplo de razonamiento correcto:
```
"Falla X porque Y llega null porque Z no valida porque W no maneja el edge case"
→ Fix en W, que es la raíz real
```

**La solución correcta elimina el problema de raíz.**

---

## REGLA CRÍTICA: Todo Parametrizable

**Todo valor de negocio o configuración debe ser parametrizable.**

Todo configurable desde:
1. **Variables de entorno** → Configuración técnica (URLs, API keys, modelo)
2. **Archivos .env** → Config de deploy

### Prioridad de configuración
```
ENV > Default en código (solo como fallback seguro)
```

### Ejemplos

```python
# Parametrizado correctamente
model = os.getenv('OPENAI_MODEL', 'gpt-5-mini')
api_url = os.getenv('NEXT_PUBLIC_API_URL', 'http://localhost:8000')
```

**Si encuentras un valor hardcodeado, parametrízalo inmediatamente.**

---

## Arquitectura del Agente

- **Agente único** con 4 tools de solo lectura (no multi-agente)
- `query_plantas`: Buscar plantas por nombre/ubicación
- `query_activos`: Buscar activos por tipo/planta/código
- `query_documentos`: Buscar documentos por tipo/planta/activo/vigencia
- `query_cross_tables`: Consulta cruzada JOIN de 3 tablas (herramienta clave)
- `parallel_tool_calls=True` para máximo rendimiento
- Session con `SQLiteSession` para historial de conversación
- `RunHooks` (VeaHomeHooks) para logging de tools

---

## Datos CSV (de Glide)

**Relaciones**:
```
PLANTAS.Row ID → ACTIVOS.ID PLANTA
PLANTAS.Row ID → DOCUMENTOS.ID PLANTA
ACTIVOS.Row ID → DOCUMENTOS.ID DE ACTIVO
```

**Vigencia**: Un documento es vigente si `vigencia_indeterminada=true` O `fecha_vencimiento >= hoy`

**Cuidados al parsear**:
- Encoding: UTF-8 con BOM (`utf-8-sig`)
- Fechas: formato `d/m/yyyy, HH:MM:SS`
- Booleans: string `"true"/"false"`
- Comillas dobles anidadas en CSV
- Campos vacíos → NULL

---

## Deploy / Rebuild

Todo rebuild sigue este flujo:

```
1. git push origin main          # Push cambios a GitHub
2. SSH al servidor               # Credenciales en memoria/servidor.yaml
3. cd /root/veahome-demo && git pull   # Pull cambios
4. docker build -t veahome-backend:latest ./backend
5. docker build -t veahome-frontend:latest ./frontend
6. docker stack deploy -c docker-compose.prod.yml veahome
```

**Credenciales (token GitHub, IP servidor, SSH)** → viven exclusivamente en `memoria/servidor.yaml`

---

## Comunicación

- **Respuestas**: Español
- **Commits**: Inglés
- **Dudas**: Preguntar antes de asumir
