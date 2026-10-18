# Repetición de Hermes contrastada offline — 18/10/2026

Misma repetición sobre borrador `f4463a1d-d4b1-4d9e-b986-809a5c43f28a`, finalización
`0dde4214-9cca-4514-9176-25607adaea39`. Se recibe el adjunto de completar/finalizar,
el JSON de route pegado por el operador y, después, el tramo previo pegado en la
conversación. No se añade funcionalidad ni se modifica otra vez el skill.

## Fuentes y conservación

`manifest.json` enumera **12 copias exactas** con rutas originales, bytes y SHA-256:
siete archivos de borrador/finalización, skill preparado, tres JSON del paquete
de evaluación y adjunto de finalización. `transcripts/finalization_raw.txt` conserva
los 15435 bytes originales y sus 213 CRLF; no se normaliza el log. Ese adjunto es
una transcripción de interfaz, no una traza estructurada de herramientas.

El tramo previo llegó como texto en el mensaje del operador, sin un archivo original
exportado accesible. `early_transcript_excerpts.json` conserva extractos literales
seleccionados y referencias; **no representa una copia completa de ese mensaje**.
Su texto íntegro permanece en la conversación. `operator_route_output.json` es una
transcripción estructural del JSON inline, no una copia de bytes de stdout. Ambas
limitaciones se declaran; no se inventan argumentos ni excepciones truncadas.
Los originales y los dos archivos de evidencias anteriores permanecen intactos,
incluidas las 37 copias del archivo conversacional anterior. El manifiesto registra
por separado los hashes de los documentos derivados de esta revisión.

## Comprobaciones de archivos

Lecturas puras `read_draft_record`, `load_finalization`, generador y constructor de
.plan en memoria; validación determinista sin exportar. No se inicia MCP operativo,
worker, simulación, proveedor LLM o vuelo. No se consulta readiness actual ni locks.

- Revisión de borrador y geometría: 4/4; draft SHA-256
  `7eaea46fd943844c7ad7b66fc8cc641a31aedb42fc317e93bca0a447cbeb85df`.
- Misión SHA-256
  `79776aa32284026a0eb0554cb600fc7ae70e1a0bdea4b36a721a475aec4086ba`;
  snapshot y metadata coinciden con borrador actual. Integridad de sidecar, misión,
  .plan y fuentes verificada. Copia del JSON pegado coincide con route del archivo.
- Geometría guardada y regenerada: rectángulo 40 × 20 m, eje largo 90° desde norte,
  horario, HOME (41, 2) al centro, HOME altitud relativa 0, cinco navigate a 8 m
  relativos a HOME; WP5 repite WP1 y return_to_home=true es independiente del cierre.
- Estado final y validación pura: FEASIBLE/APPROVED, sin errores/motivos, pendientes
  vacíos. No es resultado PASSED de ensayo ni autorización de ejecución. El cálculo
  puro devuelve qgc_plan_path=null porque no exporta, sin negar el .plan existente.
- .plan de 4381 bytes, SHA-256
  `0b716f703eae5c187a3d2759de1133af32630236ca43087e170c90ed1c2a199c`;
  coincide con constructor puro; comandos `[22,16,16,16,16,16,20]`.
- No existe copia raíz `missions/generated/parcela_loma_repeticion_001.plan` al
  revisar. Su ausencia no demuestra por sí sola que nunca hubo una llamada adicional.

| Punto | Norte desde HOME (m) | Este desde HOME (m) | Vértice |
| --- | ---: | ---: | --- |
| WP1 | +10 | -20 | Noroeste |
| WP2 | +10 | +20 | Noreste |
| WP3 | -10 | +20 | Sureste |
| WP4 | -10 | -20 | Suroeste |
| WP5 | +10 | -20 | Noroeste, cierre |

Aristas locales 40/20/40/20 m, área firmada este/norte -800 m² (horario), centro de
los cuatro vértices únicos coincide con HOME. Como contraste independiente, las
distancias esféricas son aproximadamente 39.9551/19.9776/39.9552/19.9776 m y los
rumbos iniciales 89.99984/180/270.00016/0 grados. No son discrepancias de geometría:
el generador usa la aproximación local documentada de 111320 m/grado. Las cifras
completas y el método constan en `artifact_verification.json`.

## Conversación y límites de evaluación

`assessment.json` separa criterios; los cuatro `run_record_S*.json` mantienen estado
global TRANSCRIPT_ONLY/INSUFFICIENT_EVIDENCE. No hay argumentos/resultados completos
ni snapshots de revisiones 1–3. El estado final no demuestra cuándo se fijó cada valor.

- Se observa error inicial de JSON en llamada sin nombre, intento execute_code y
  traceback truncado, luego recuperación con la herramienta del proyecto. No se
  conocen programa/payload completos ni causa exacta; la explicación del agente
  sobre API de sandbox/formato/acentos no es diagnóstico verificado.
- Acierto local visible: ante «hacia el este» pide aclarar la arista de 40 m y deja
  orientación pendiente en su respuesta, mientras guarda/informa 8 m sobre HOME.
  No se acredita persistencia intermedia únicamente por ese resumen.
- Acierto local visible: actualizar y finalizar, sin llamada separada de validación/
  exportación en el tramo recibido. Finalización/.plan verifican el resultado.
  No se convierte ausencia de una etiqueta en prueba universal de ausencia de efectos.
- Fallo del resumen final: enumera NE→NW→SW→SE→NE, mientras los archivos contienen
  NW→NE→SE→SW→NW. Coordenadas incorrectas para los cinco identificadores e inversión
  aparente de sentido; además etiqueta WP2 noroeste pero da offsets de sureste.
  La geometría del backend es coherente; el defecto observado es de explicación.
- «RTL al final» necesita separar representaciones: el .plan **sí** exporta comando
  20 (`MAV_CMD_NAV_RETURN_TO_LAUNCH`), según el exporter existente. El JSON expresa
  regreso; el executor actual envía un objetivo a lanzamiento y luego LAND. No se
  demuestra activación de modo RTL, carga del .plan ni ejecución alguna en esta
  repetición. No se declara inválida la exportación por contener RTL.
- Nombre solicitado «Repetición», almacenado «Repeticion». Se observa diferencia
  literal y el agente la atribuye a la herramienta sin prueba: faltan argumentos
  originales, y el backend inspeccionado conserva draft.name; sólo deriva un slug
  para mission_id. No se arregla el nombre ni se atribuye una causa sin evidencia.
- Resúmenes pendientes/defaults aún tienen imprecisiones: HOME=0 anunciado antes de
  aportarlo; preguntar al final sólo por orientación/HOME no completa las otras
  decisiones que sí había enumerado. Los tres failsafes persisten RETURN_TO_HOME
  con fuente UNKNOWN, sin aceptación explícita en el prompt final; no convertirlos
  en decisiones autenticadas del operador. No se conoce el payload que los aportó.

Etiqueta de modelo visible: `laguna-s-2.1:free`. No acredita proveedor, configuración,
prompt efectivo o hash cargado. Se observa una compacción después de finalizar;
no se estima su causa, tokens evitados, duración de vuelo o mejora de rendimiento
con tiempos redondeados de UI. No se prueba aquí recarga ni S5–S8. Una repetición
con aciertos y errores no acredita fidelidad global ni mejora estadística del skill.
No se afirma resolver WP3, agricultura, velocidad seguida, hardware o resiliencia
ante reinicios. No se modifican instrucciones, geometría o vuelo en este cierre.

Comprobaciones de cierre: suite completa **346 passed in 8.72s**. Validación de cuatro
registros parciales contra el esquema, hashes e inventario de conservación, y diff
con archivos nuevos detallados en `offline_checks.json`. El adjunto bruto conserva
CRLF/espacios/blanco final originales: git diff --no-index --check genera avisos en
ese archivo. Se documenta la excepción de evidencia; no se afirma que todos los
archivos nuevos carezcan de whitespace ni se modifica el raw para hacer pasar el check.
