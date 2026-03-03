"""
Prompts para el LLM vision segun tipo de PDF (Type 1 U-1A / Type 2 Certificado).
- Finalidad: Define SYSTEM_PROMPT (rol experto ASME) y prompts especificos
  por tipo de PDF con campos, conversiones de unidades y reglas de extraccion.
- Consume: nada (solo constantes string)
- Consumido por: llm_extractor.py (selecciona prompt segun pdf_type)
"""

SYSTEM_PROMPT = (
    "Eres un experto en certificados ASME de recipientes a presion. "
    "Extraes datos estructurados de imagenes de formularios ASME U-1A "
    "y certificados de inspeccion. Siempre respondes SOLO con JSON valido."
)

TYPE_1_PROMPT = """Analiza estas imagenes de un formulario ASME U-1A (MANUFACTURER'S DATA REPORT FOR PRESSURE VESSELS).

Extrae los siguientes campos y devuelve SOLO un JSON valido (sin markdown, sin ```).

CAMPOS A EXTRAER:
- fabricante: Nombre del fabricante (manufacturer name)
- ano_fabricacion: Ano de fabricacion del recipiente. Extraer del campo "DATE" del formulario U-1A (solo el ano, ej: "2017"). Si no hay fecha explicita, usar el ano de fecha_certificacion
- asme_code_edition: Ano/edicion del codigo ASME usado (ej: "2019", "2021 Edition")
- mawp_psi: Maximum Allowable Working Pressure en PSI (numero decimal)
- hydro_test_pressure_psi: Presion de prueba hidrostatica en PSI (numero decimal)
- material_cuerpo: Material del cuerpo/shell (ej: "SA-516 GR.70")
- espesor_cuerpo_mm: Espesor del cuerpo/shell. Si esta en pulgadas, convertir a mm (1 in = 25.4 mm)
- longitud_cuerpo_m: Longitud del cuerpo/shell. Si esta en pies/pulgadas, convertir a metros (1 ft = 0.3048 m)
- diametro_interior_m: Diametro INTERIOR del recipiente. Si esta en pulgadas, convertir a metros (1 in = 0.0254 m)
- material_cabezales: Material de los cabezales/heads (ej: "SA-516 GR.70")
- espesor_cabezales_mm: Espesor de los cabezales/heads. Si esta en pulgadas, convertir a mm
- fecha_certificacion: Fecha de certificacion del FABRICANTE (Date en CERTIFICATE OF COMPLIANCE, NO la fecha del inspector) en formato YYYY-MM-DD
- serial_number: Numero(s) de serie del fabricante
- vessel_type: "Horizontal" o "Vertical"

VALORES RAW (antes de conversion):
- raw_mawp: Valor original tal como aparece (ej: "250 psi")
- raw_hydro_test_pressure: Valor original tal como aparece
- raw_espesor_cuerpo: Valor original tal como aparece (ej: "0.375 in")
- raw_longitud_cuerpo: Valor original tal como aparece (ej: "10 ft 6 in")
- raw_diametro_interior: Valor original tal como aparece (ej: "48 in")
- raw_espesor_cabezales: Valor original tal como aparece

REGLAS:
- Si un campo no se encuentra, pon null
- Todos los espesores finales en mm, longitudes/diametros en metros, presiones en PSI
- Para raw_*, copia el texto exacto como aparece en el documento
- No inventes datos. Si no es legible, pon null
- Responde SOLO con el JSON, sin texto adicional"""

TYPE_2_PROMPT = """Analiza estas imagenes de un Certificado de Inspeccion de recipiente a presion.

Las imagenes son (en orden):
1. Pagina de "DATOS DEL PRODUCTO" (puede estar en espanol con unidades metricas)
2. Pagina de "FECHA DE INSPECCION" (contiene la fecha de certificacion correcta)
3. Formulario ASME U-1A embebido (si existe) — front
4. Formulario ASME U-1A embebido (si existe) — back

Extrae los siguientes campos combinando informacion de TODAS las imagenes y devuelve SOLO un JSON valido (sin markdown, sin ```).

CAMPOS A EXTRAER:
- fabricante: Nombre del fabricante
- ano_fabricacion: Ano de fabricacion del recipiente. Buscar en "DATOS DEL PRODUCTO" o en CERTIFICATE OF COMPLIANCE. Extraer solo el ano (ej: "2015"). Si no hay fecha explicita, usar el ano de fecha_certificacion
- asme_code_edition: Ano/edicion del codigo ASME
- mawp_psi: Presion maxima de trabajo. Si esta en kg/cm2, convertir a PSI (1 kg/cm2 = 14.2233 PSI). Si esta en bar, convertir (1 bar = 14.5038 PSI)
- hydro_test_pressure_psi: Presion de prueba hidrostatica en PSI (buscar en el U-1A embebido si no esta en la pag de datos). Mismas conversiones
- material_cuerpo: Material del cuerpo/shell (ej: "SA-516 GR.70")
- espesor_cuerpo_mm: Espesor del cuerpo/shell en mm. Si ya esta en mm, dejarlo. Si esta en pulgadas, convertir (1 in = 25.4 mm)
- longitud_cuerpo_m: Longitud del cuerpo en metros. Si ya esta en metros, dejarlo. Si esta en mm, convertir (dividir entre 1000)
- diametro_interior_m: Diametro INTERIOR en metros. Buscar en U-1A embebido si no esta en pagina de datos. Si esta en pulgadas, convertir (1 in = 0.0254 m). IMPORTANTE: Necesitamos diametro INTERIOR, no exterior
- material_cabezales: Material de los cabezales/heads
- espesor_cabezales_mm: Espesor de los cabezales en mm
- fecha_certificacion: Fecha de inspeccion de la pagina 8 (seccion "FECHA DE INSPECCION"). Esta es la fecha correcta y vigente. Formato YYYY-MM-DD. NO usar la fecha del CERTIFICATE OF COMPLIANCE ni la del fabricante
- serial_number: Numero(s) de serie del fabricante
- vessel_type: "Horizontal" o "Vertical"

VALORES RAW (antes de conversion):
- raw_mawp: Valor original tal como aparece (ej: "17.58 kg/cm2")
- raw_hydro_test_pressure: Valor original tal como aparece
- raw_espesor_cuerpo: Valor original tal como aparece
- raw_longitud_cuerpo: Valor original tal como aparece
- raw_diametro_interior: Valor original tal como aparece
- raw_espesor_cabezales: Valor original tal como aparece

REGLAS:
- Combina datos de TODAS las imagenes. La pagina de datos tiene info en metrico, el U-1A en imperial
- IMPORTANTE: fecha_certificacion DEBE venir de la pagina de "FECHA DE INSPECCION" (imagen 2), NO de otras paginas
- Si un campo no se encuentra en ninguna imagen, pon null
- Presiones finales en PSI, espesores en mm, longitudes/diametros en metros
- Para raw_*, copia el texto exacto como aparece
- No inventes datos. Si no es legible, pon null
- Responde SOLO con el JSON, sin texto adicional"""
