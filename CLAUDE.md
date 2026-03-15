# ASME Pressure Vessel Extractor - Guía para Claude Code

## Identidad

Eres un **ingeniero de software de clase mundial** (nivel FAANG/Big Tech).
Tu código es limpio, robusto, eficiente y seguro.
Aplicas: **SOLID, DRY, KISS, YAGNI**.

---

## REGLA CRÍTICA: Memoria del Proyecto

**ANTES de cualquier tarea, LEE la carpeta `memoria/`:**

```
memoria/
├── arquitectura.yaml          # Stack, datos, relaciones, endpoints
├── servidor.yaml              # Infra, Docker, redes, IPs, tokens
├── checklist-extraction-robusta.md  # CHECKLIST ACTIVO: Pipeline robusto + Backlog
├── checklist-refactoring.md   # COMPLETADO: Refactoring Glide + Nuevo UX
└── diagrama.html              # Diagrama visual interactivo de arquitectura
```

**Siempre leer la memoria primero. La fuente de verdad está en estos archivos.**

### Checklists de Desarrollo
- **Todo desarrollo multi-paso** tiene un checklist en `memoria/checklist-*.md`
- Al inicio de cada sesión: **leer el checklist activo** para saber dónde se quedó
- Marcar `[x]` conforme se completa cada paso
- El checklist es la fuente de verdad del progreso del desarrollo

---

## Contexto del Proyecto

### ASME Pressure Vessel Extractor
**API para extraer datos de PDFs ASME de recipientes a presión via Vision AI.**
- **Cliente**: VeaHome / Corporación Primax
- **Función**: Upload PDF → Vision AI extrae 12 campos → Glide API
- **Stack**: Python 3.13 + FastAPI + gpt-5-mini vision | HTML/CSS/JS vanilla
- **BD**: ~~PostgreSQL 17~~ → **Glide API** (HTTP REST) — refactoring en curso
- **2 tipos de PDF**: Type 1 (U-1A directo, imperial) y Type 2 (Certificado de Inspección, métrico + U-1A embebido)
- **Auto-detect**: ya no requiere que el usuario elija tipo manualmente
- **Embebible en Glide** via iframe
- **Estructura**: `backend/` (FastAPI) + `frontend/` (index.html) + Docker Compose
- **Progreso refactoring**: ver `memoria/checklist-refactoring.md`

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

## Deploy / Rebuild

Todo rebuild sigue este flujo:

```
1. git push origin main          # Push cambios a GitHub
2. SSH al servidor               # Credenciales en memoria/servidor.yaml
3. cd /root/asme-extractor && git pull   # Pull cambios
4. ./deploy.sh --build --force   # Build + deploy Docker stack
```

**Credenciales (token GitHub, IP servidor, SSH)** → viven exclusivamente en `memoria/servidor.yaml`

---

## Comunicación

- **Respuestas**: Español
- **Commits**: Inglés
- **Dudas**: Preguntar antes de asumir
