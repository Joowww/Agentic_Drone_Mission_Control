# Ensayo operativo drone_02/v2 — 18/10/2026

run_id: `7162bce5-3635-4a76-bf02-6a5a22612aab`; request_key:
`joel-drone02-preflight-01`. Operación realizada por el operador; este archivo se
prepara verificando offline lo ya guardado, sin Docker, vuelos o MCP operativo.

`manifest.json` enumera ocho copias exactas con ruta original absoluta, ruta de copia,
bytes y SHA-256. Incluye los cinco archivos del ensayo, el índice de la clave, el
ejemplo fuente y la transcripción adjunta. `offline_checks.json` y esta guía son
análisis derivados, separados de los originales. La transcripción y worker.log se
copian byte a byte, sin normalizar líneas, formato ni contenido.

Snapshot/input/ejemplo fuente: 1717 bytes cada uno, SHA-256
`ce94effedb4c977b0db3c64e41d4a2b86bba9a78c494cfeda4305d069d54bebb`.
Consistencia verificada con job schema 2, report schema 1.1 y el índice de clave.
source_artifact=null: origen JSON autónomo, no finalización de borrador. Es el primer
ensayo operativo de v2 documentado para el incremento de selección por misión.

## Resultado comprobado

- Identidad coherente drone_02/v2 en misión, admisión, informe y executor.
- Job FINISHED/analyze, informe PASSED; executor COMPLETED/success=true.
- 14 eventos: GUIDED, ARM, TAKEOFF_COMMAND/REACHED, tres pares
  WAYPOINT_COMMAND/REACHED WP1/WP2/WP3, RETURN_HOME_COMMAND/REACHED,
  LAND_COMMAND y LANDED con landed=true/armed=false/flying=false.
- Regreso por navegación y LAND, no modo RTL. Sin recuperación/fallos registrados.
- Reanálisis estricto: igualdad con los once checks true guardados, incluidos
  identidad y consistencia posicional con el mapper/posición real de lanzamiento.
  No es un registro independiente de telemetría.
- Validación pura sin exportación: igual a la guardada, FEASIBLE/APPROVED.
- Readiness guardada READY para ambos drones: histórica, no consultada ahora.
- Worker.log: dos líneas de admisión/finalización PASSED, sin traza de comandos ni
  auditoría explícita de reservas. Identidad del worker preservada, no comprobada
  ahora contra /proc ni contra una versión desplegada autenticada.

| Intervalo de operación | Segundos |
| --- | ---: |
| report.started_at → finished_at, incluida admisión previa | 299.843057 |
| execution_started_at → execution_finished_at | 285.971737 |
| job.created_at → finished_at | 299.845881 |

Son diferencias de timestamps UTC; no tiempo en vuelo. Los eventos no tienen tiempos
individuales. No supera 300 s en esos intervalos; no demuestra eliminar timeouts.

## Conversación y reserva global

El adjunto muestra activación del skill sin versión verificable, petición de un
reinicio único por pantalla negra y llamadas stop/start/readiness en orden. El
operador confirma después que ve mundo/drones y autoriza un solo ensayo v2. No se
capturan argumentos/resultados estructurados ni comprobación de reservas previa al
reinicio; no se certifica obediencia global del skill. La causa de pantalla negra
permanece desconocida. El cliente comunica 21 herramientas y después 0 disponibles
al actualizar el agente; el registro offline del repositorio tenía 17. No se deduce
causa ni versión real desplegada a partir de ese desacuerdo.

Se ven un start y dos get del mismo ensayo. Hermes comunica EXECUTING en restricciones
vehicle/global durante la ejecución y ambas null al finalizar. Se conserva **como
resumen de la consulta del operador**, no como estado persistido en job/report ni
como observación actual o prueba estructurada de liberación. Código y tests offline
mantienen una sola ejecución global; este vuelo no prueba contención operativa,
coordinación simultánea o separación. No hay evidencia independiente de inmovilidad
de v1. El JSON dice precision_agriculture, pero las tres acciones son navigate:
no prueba trabajo agrícola, seguimiento de velocidad, carga del .plan o hardware.
PASSED no autoriza otro vuelo ni explica el fallo antiguo WP3.

Suite completa offline de cierre: **388 passed in 10.11s**. Los hashes preservan
bytes locales, sin autenticar diálogo, ejecución histórica o todos los TOCTOU.
git diff --check versionado limpio; la revisión individual de nuevos archivos avisa
de trailing whitespace en transcripts/hermes_raw.txt por CRLF/espacios del original.
Se conserva exacto, sin normalizar ni ocultar los avisos. Los otros archivos nuevos
no presentan errores de whitespace.
