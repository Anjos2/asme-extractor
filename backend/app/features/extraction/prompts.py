"""
Prompts para el LLM vision segun tipo de PDF (Type 1 U-1A / Type 2 Certificado).
- Finalidad: Define SYSTEM_PROMPT (rol experto ASME) y prompts especificos
  por tipo de PDF con campos, conversiones de unidades y reglas de extraccion.
  Incluye reglas de normalizacion: fabricante sin direccion, materiales sin prefijo "ASME".
  fecha_certificacion: fecha del INSPECTOR, formato USA MM/DD/YYYY.
  diametro_interior: prioridad ID directo, fallback OD→ID con formula.
  asme_code_edition: rangos con "to" (ej: "2004 to 2006") para evitar corrupcion en Glide.
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
- fabricante: Solo el nombre de la empresa hasta la forma juridica. Ejemplos: "Trinity Industries de Mexico S de RL de CV", "Arcosa Industries de Mexico S. de R.L. de C.V.", "Buffalo Tank Division"
- ano_fabricacion: Ano de fabricacion del recipiente. Extraer del campo "DATE" del formulario U-1A (solo el ano, ej: "2017"). Si no hay fecha explicita, usar el ano de fecha_certificacion
- asme_code_edition: Ano/edicion del codigo ASME usado. Copiar el texto tal como aparece en el documento (ej: "2019", "2004 to 2006", "2021 Edition"). Si es un rango de anos, usar "to" entre los anos (ej: "2004 to 2006")
- mawp_psi: Maximum Allowable Working Pressure en PSI (numero decimal)
- hydro_test_pressure_psi: Presion de prueba hidrostatica en PSI (numero decimal). Buscar "HYDRO", "Hydrostatic test", "Proof test", "Test pressure" en el formulario
- material_cuerpo: Solo la designacion del material del cuerpo/shell. Ejemplos: "SA-455", "SA-516 GR.70", "SA-285 Gr. C"
- espesor_cuerpo_mm: Espesor del cuerpo/shell. Si esta en pulgadas, convertir a mm (1 in = 25.4 mm)
- longitud_cuerpo_m: Longitud del cuerpo/shell. Si esta en pies/pulgadas, convertir a metros (1 ft = 0.3048 m, 1 in = 0.0254 m). Ej: 12' 7.563" = 3.850 m
- diametro_interior_m: Diametro INTERIOR del recipiente. Primero buscar un valor marcado con "(ID)" o "Inner diameter" en la seccion 6 del formulario. Si solo hay un valor marcado con "(OD)" (diametro exterior), calcular el interior asi: ID = OD - (2 x espesor nominal del cuerpo, que esta en la misma seccion 6). Convertir el resultado a metros. Ej con ID directo: 3' 4.484" = 1.028 m. Ej con OD: OD=40.96", espesor=0.239", ID=40.96-(2x0.239)=40.482", en metros=1.028 m
- material_cabezales: Solo la designacion del material de los cabezales/heads. Ejemplos: "SA-285 Gr. C", "SA-516 GR.70"
- espesor_cabezales_mm: Espesor de los cabezales/heads. Si esta en pulgadas, convertir a mm
- fecha_certificacion: Fecha del INSPECTOR AUTORIZADO. Buscar la ULTIMA fecha "Date" en el back del U-1A, en la seccion "CERTIFICATE OF SHOP/FIELD INSPECTION", firmada por el Authorized Inspector. Las fechas en el U-1A estan en formato USA (MM/DD/YYYY). Ejemplo: "06/06/2020" en el PDF significa junio 6 de 2020 → devolver "2020-06-06". Formato final: YYYY-MM-DD
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
- IMPORTANTE: Las fechas en el formulario U-1A estan en formato USA (MM/DD/YYYY). El primer numero es el MES, el segundo es el DIA
- No inventes datos. Si no es legible, pon null
- Responde SOLO con el JSON, sin texto adicional"""

TYPE_2_PROMPT = """Analiza estas imagenes de un Certificado de Inspeccion de recipiente a presion.

Las imagenes incluyen (pueden ser 3, 4, 5 o mas):
- Pagina de "DATOS DEL PRODUCTO" (en espanol con unidades metricas)
- Pagina de "FECHA DE INSPECCION" (contiene la fecha de certificacion correcta)
- Paginas del formulario ASME U-1A embebido (si existe en el certificado)

Extrae los siguientes campos combinando informacion de TODAS las imagenes y devuelve SOLO un JSON valido (sin markdown, sin ```).

CAMPOS A EXTRAER:
- fabricante: Solo el nombre de la empresa hasta la forma juridica. Ejemplos: "Trinity Industries de Mexico S de RL de CV", "Arcosa Industries de Mexico S. de R.L. de C.V.", "Buffalo Tank Division"
- ano_fabricacion: Ano de fabricacion del recipiente. Buscar en "DATOS DEL PRODUCTO" o en CERTIFICATE OF COMPLIANCE. Extraer solo el ano (ej: "2015"). Si no hay fecha explicita, usar el ano de fecha_certificacion
- asme_code_edition: Ano/edicion del codigo ASME. Copiar el texto tal como aparece (ej: "2019", "2004 to 2006"). Si es un rango de anos, usar "to" entre los anos
- mawp_psi: Presion maxima de trabajo. Si esta en kg/cm2, convertir a PSI (1 kg/cm2 = 14.2233 PSI). Si esta en bar, convertir (1 bar = 14.5038 PSI)
- hydro_test_pressure_psi: Presion de prueba hidrostatica en PSI. Buscar "HYDRO", "Hydrostatic test", "Proof test", "Test pressure" en TODAS las imagenes (especialmente en el U-1A embebido, seccion 9). Mismas conversiones de unidad
- material_cuerpo: Solo la designacion del material del cuerpo/shell. Ejemplos: "SA-455", "SA-516 GR.70", "SA-285 Gr. C"
- espesor_cuerpo_mm: Espesor del cuerpo/shell en mm. Si ya esta en mm, dejarlo. Si esta en pulgadas, convertir (1 in = 25.4 mm)
- longitud_cuerpo_m: Longitud del cuerpo en metros. Si ya esta en metros, dejarlo. Si esta en mm, convertir (dividir entre 1000). Si esta en pies/pulgadas, convertir (1 ft = 0.3048 m, 1 in = 0.0254 m)
- diametro_interior_m: Diametro INTERIOR en metros. Primero buscar un valor marcado con "(ID)", "Inner diameter" o "diametro interior" en TODAS las imagenes. Si solo hay "Diametro Exterior" u "(OD)", calcular el interior: ID = OD - (2 x espesor nominal del cuerpo). Convertir el resultado a metros. Ej con OD: OD=40.96", espesor=0.239", ID=40.96-(2x0.239)=40.482", en metros=1.028 m
- material_cabezales: Solo la designacion del material de los cabezales/heads. Ejemplos: "SA-285 Gr. C", "SA-516 GR.70"
- espesor_cabezales_mm: Espesor de los cabezales en mm
- fecha_certificacion: Fecha de inspeccion de la pagina "FECHA DE INSPECCION" (imagen 2). Esta es la fecha correcta y vigente. Formato YYYY-MM-DD
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
- IMPORTANTE: fecha_certificacion viene de la pagina de "FECHA DE INSPECCION"
- Si un campo no se encuentra en ninguna imagen, pon null
- Presiones finales en PSI, espesores en mm, longitudes/diametros en metros
- Para raw_*, copia el texto exacto como aparece
- No inventes datos. Si no es legible, pon null
- Responde SOLO con el JSON, sin texto adicional"""
