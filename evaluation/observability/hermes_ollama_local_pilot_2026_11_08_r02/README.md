# Hermes + Ollama local planning pilot r02 (08/11/2026) — REAL, cadena completada con desviaciones

**Tipo: REAL.** Segundo y último piloto autorizado del caso `local-planning-demo`, con los mismos dos prompts
registrados que r01 (`observability/hermes_capture_run.py`, `LOCAL_DEMO_TURN_1/2`). Única diferencia con r01:
el servidor de demo añade una guía a las descripciones de sus dos herramientas (commit `5ad919ea9`, hash del
servidor `277da516…` en `turn-*.json`); esquema de argumentos y backend iguales a los del servidor completo.

Entorno: Hermes Agent `d923a5eb`, perfil `tfg-demo-local`, modelo `qwen3-4b-instruct-64k` (Qwen3 4B
Instruct 2507 Q4_K_M, contexto 65 536) en Ollama 0.34.2, instancia propia en `127.0.0.1:11435` con flash
attention y caché KV q4_0 (37/37 capas en GPU, 5,6 GB). Sin red externa, sin simulador, sin vehículos,
sin credenciales.

## Resultado

| Comprobación | Resultado |
| --- | --- |
| Hermes usa Qwen local | Sí: 7 `llm_call`, todas `custom` / `qwen3-4b-instruct-64k`, 0 errores |
| Herramientas ofrecidas | Solo `mcp__tfg_demo_planning__update_mission_draft` y `…finalize_mission_draft` en las 7 peticiones |
| Veredicto de aislamiento | `PLANNING_CALLS_WITHIN_ALLOWED_TOOLS` |
| `update_mission_draft` | 3 ejecuciones `ok` (78, 65 y 27 ms) |
| `finalize_mission_draft` | 2 ejecuciones `ok`: turno 1 → `INCOMPLETE` (sin finalización); turno 2 → `VALIDATED` (23 ms) |
| Validación determinista (LangGraph) | `mission_status: FEASIBLE`, `execution_status: APPROVED`, sin motivos de fallo |
| Exportación QGC | `REFUSED`: falta la altitud AMSL del *home*; comportamiento esperado, no es un error |
| `mission.json` / `finalization.json` | Existen; SHA-256 de la misión verificado (`203779464bcb…`) |
| Autorización de vuelo | `NOT_GRANTED` |
| Opik | Solo dry-run: 2 trazas, 7 spans, proyecto `tfg-hermes-local-demo`, **no enviado** |

Duración por turno: 29,4 s y 40,3 s (incluye el arranque de Hermes y del servidor MCP). Llamadas al modelo:
de 2,4 s a 15,7 s; tokens de entrada por llamada de 125 a 7 378 (contadores normalizados de Hermes).

## Desviaciones del modelo (no ocultas por el veredicto)

1. **Turno 1:** guardó el borrador `fd342a48…` con los datos del operador y la ruta generada por el
   planificador, pero **omitió `vehicle_type`** aunque el prompt decía «multirrotor». Llamó a
   `finalize_mission_draft` con campos pendientes (el backend respondió `INCOMPLETE` y no creó nada). La
   aclaración al operador pidió el tipo de vehículo y los tres límites. La respuesta cita una ruta de archivo
   **inexistente** (`…/cache/scratch/drafts/…json`).
2. **Turno 2:** **no continuó el mismo borrador.** Creó `1ac2503e…` solo con los tres límites (borrador
   huérfano) y después `e219b490…` con todos los datos, `vehicle_type` tomado del turno 1 y los dos waypoints
   copiados del resultado del turno 1. Ese es el borrador finalizado.
3. **Consecuencias en la misión finalizada:** ningún valor inventado ni distinto de los del operador; los
   waypoints coinciden en todas sus cifras con la ruta determinista del turno 1. Pero `mission_id` no se pasó
   y el backend aplicó su valor de compatibilidad declarado, `agri_demo_001_h1_sector_a_001` (el operador dio
   `agri_demo_001_h1_sector_a`); `vehicle_id` también quedó por defecto (`drone_01`, que coincide con el del
   operador); la procedencia de la ruta se perdió (`route_provenance: null`, procedencia de campos `UNKNOWN`).

Lectura: la cadena Operador → Hermes → Ollama/Qwen → MCP → MissionDefinition → validación LangGraph →
finalización → captura → resumen → dry-run funciona de extremo a extremo con un modelo local. La continuidad
del borrador entre turnos y la fidelidad de identificadores siguen siendo débiles con Qwen3 4B; un único piloto
no mide fiabilidad.

## Contenido

`capture/`, `capture_summary.json` (total y por turno), `outcome.json`, `planning_result.json` (los tres
borradores y la finalización, con los valores por defecto aplicados), `mission-13162233-….json` (la misión
validada), `turn-1.json`, `turn-2.json`, `answer-turn-*.txt` (respuestas de Hermes con `~` en lugar del
directorio personal), `native-usage-turn-*.json`, `opik_dry_run.json` y `view.html`. Manifiesto: `SHA256SUMS`.
Registro sellado: no se modifica ni se regenera.
