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

La primera imagen es la pagina de "DATOS DEL PRODUCTO" (puede estar en espanol con unidades metricas).
La segunda imagen (si existe) es el formulario ASME U-1A embebido en el certificado.

Extrae los siguientes campos combinando informacion de AMBAS imagenes y devuelve SOLO un JSON valido (sin markdown, sin ```).

CAMPOS A EXTRAER:
- fabricante: Nombre del fabricante
- asme_code_edition: Ano/edicion del codigo ASME
- mawp_psi: Presion maxima de trabajo. Si esta en kg/cm2, convertir a PSI (1 kg/cm2 = 14.2233 PSI). Si esta en bar, convertir (1 bar = 14.5038 PSI)
- hydro_test_pressure_psi: Presion de prueba hidrostatica en PSI (buscar en el U-1A embebido si no esta en la pag de datos). Mismas conversiones
- material_cuerpo: Material del cuerpo/shell (ej: "SA-516 GR.70")
- espesor_cuerpo_mm: Espesor del cuerpo/shell en mm. Si ya esta en mm, dejarlo. Si esta en pulgadas, convertir (1 in = 25.4 mm)
- longitud_cuerpo_m: Longitud del cuerpo en metros. Si ya esta en metros, dejarlo. Si esta en mm, convertir (dividir entre 1000)
- diametro_interior_m: Diametro INTERIOR en metros. Buscar en U-1A embebido si no esta en pagina de datos. Si esta en pulgadas, convertir (1 in = 0.0254 m). IMPORTANTE: Necesitamos diametro INTERIOR, no exterior
- material_cabezales: Material de los cabezales/heads
- espesor_cabezales_mm: Espesor de los cabezales en mm
- fecha_certificacion: Fecha de certificacion del FABRICANTE (Date en CERTIFICATE OF COMPLIANCE, NO la fecha del inspector) en formato YYYY-MM-DD
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
- Combina datos de ambas imagenes. La pagina de datos tiene info en metrico, el U-1A en imperial
- Si un campo no se encuentra en ninguna imagen, pon null
- Presiones finales en PSI, espesores en mm, longitudes/diametros en metros
- Para raw_*, copia el texto exacto como aparece
- No inventes datos. Si no es legible, pon null
- Responde SOLO con el JSON, sin texto adicional"""
