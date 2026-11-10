# Comparación experimental de agri_demo_001 (generada)

Generada por `reporting/agri_experiment_comparison.py` desde la evidencia conservada. No ejecuta inferencias ni reevalúa respuestas: cada aceptación es la registrada en su momento. **H3, H3b y el piloto no se agregan en una tasa**: usan prompts, herramientas y protocolos distintos.

**Unidades:** *invocación* = una ejecución de Hermes; *petición al modelo* = llamada de API registrada por Hermes (principal o auxiliar); *intento interno* = intento de una petición registrado por Hermes, fallido o completado (solo lo registra el piloto). Llamarlo reintento depende del contador `retry_count`.

## 1. Invocaciones, peticiones y herramientas

| Caso | Protocolo | Invocaciones | Peticiones al modelo (principal + auxiliar) | Errores de llamada (plugin) | Herramientas ofrecidas | Pedidas | Ejecutadas sin error | Veredicto | Fuente |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| H1 | generación y validación de artefactos de misión a partir de una especificación completa | 1 | 3 + 1 | 0/3 | ONLY_TRIAL_TOOL_OFFERED | 4 | 4/4 | `PLANNING_CALLS_WITHIN_ALLOWED_TOOLS` | `evaluation/observability/agri_planning_h1_nous_2026_10_24/capture_summary.json` |
| H3 | accept-h3 (get_mission_state; claves sin clases) | 1 | 2 + 1 | 0/2 | ONLY_TRIAL_TOOL_OFFERED | 2 | 2/2 | `QUERY_CALLS_WITHIN_ALLOWED_TOOLS` | `evaluation/observability/agri_scenario_h3_nous_2026_10_24/capture_summary.json` |
| H3b | accept-h3b (get_scenario_view; claves factuales y críticas) | 1 | 2 + 1 | 0/2 | ONLY_TRIAL_TOOL_OFFERED | 1 | 1/1 | `QUERY_CALLS_WITHIN_ALLOWED_TOOLS` | `evaluation/observability/agri_scenario_h3b_nous_2026_10_24/capture_summary.json` |

## 2. Respuesta, formato y exactitud estructurada

| Caso | Respuesta | Formato | Claves estructuradas coincidentes | Claves críticas coincidentes | Claves fallidas | Aceptación registrada | Fuente |
| --- | --- | --- | --- | --- | --- | --- | --- |
| H1 | NOT_EVALUATED (los artefactos se juzgan por la vinculación) | — | 2/2 | n/a | ninguna | `BOUND` | `evaluation/observability/agri_planning_h1_nous_2026_10_24/h1_binding.json` |
| H3 | RECEIVED | JSON_OBJECT | 22/23 | n/a | r1_movement_authorized | `NOT_VALIDATED` | `evaluation/observability/agri_scenario_h3_nous_2026_10_24/accept_h3.json` |
| H3b | RECEIVED | FENCED_JSON_OBJECT | 23/23 | 12/12 | ninguna | `STRUCTURED_VALIDATED_EXPLANATION_UNREVIEWED` | `evaluation/observability/agri_scenario_h3b_nous_2026_10_24/accept_h3b.json` |

- **H1:** «coincidentes» cuenta los artefactos `BOUND` con validación `APPROVED`: artefactos BOUND con validación APPROVED y geometría igual a H0.
- **H3, dos denominadores que no se mezclan:** **22/23** cuenta solo las claves comparadas con el valor esperado (22 coinciden; falla `r1_movement_authorized`). **24/25**, en la evidencia de H3, suma además dos comprobaciones de **presencia** (`evidence_source`, `explanation`) que no comparan valores.
- **H3:** el protocolo H3 no separaba claves críticas; r1_movement_authorized es crítica solo bajo el protocolo H3b posterior (clasificación retrospectiva).
- **H1:** decisiones dadas por el operador: todos los valores (vehículos, ids, offsets, altitud, home, límites y acciones), las herramientas a usar y su orden. Aportación de Hermes: trasladar la especificación en español a los argumentos estructurados de update_mission_draft (incluido geometry_intent) sin inventar campos, encadenar draft_id y draft_revision en las 4 llamadas y devolver el JSON final. Lo hizo el código: coordenadas desde los offsets, validación determinista, finalización y vinculación por hash frente a H0.
- **H3b:** factuales y críticas según `accept-h3b`.

## 3. Explicación libre y estado de revisión

| Caso | Estado |
| --- | --- |
| H1 | no aplica: no se usa texto del modelo |
| H3 | clasificación manual en el README de H3 (no registrada como revisión humana de Joel): error crítico «MET autoriza mover el rover», orden basado en la admisión, MET impreciso |
| H3b | UNREVIEWED por Joel; revisión asistida (ChatGPT, transmitida por Joel) con errores factuales: evaluation/observability/agri_scenario_h3b_nous_2026_10_24/explanation_review_assisted.json |
| Piloto | Revisión humana PENDIENTE: `evaluation/observability/agri_scenario_pilot_nous_2026_10_24/explanation_review_sheet.md`; observaciones asistidas, no humanas |

## 4. Tiempos y tokens conocidos (por invocación)

| Caso | Tiempo de pared (s) | Tokens de entrada | Salida | Caché leída | Razonamiento | Total | Total auxiliar | Fin de turno | Fuente |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| H1 | 55.593 | 41211 | 1856 | 23424 | 808 | 66491 | 598 | `text_response(finish_reason=stop)` | `evaluation/observability/agri_planning_h1_nous_2026_10_24/native_usage_reviewed.json` |
| H3 | 49.935 | 7448 | 1102 | 1504 | 35 | 10054 | 664 | `text_response(finish_reason=stop)` | `evaluation/observability/agri_scenario_h3_nous_2026_10_24/native_usage_reviewed.json` |
| H3b | 46.106 | 8543 | 1190 | 448 | 0 | 10181 | 533 | `text_response(finish_reason=stop)` | `evaluation/observability/agri_scenario_h3b_nous_2026_10_24/native_usage_reviewed.json` |

Los tokens son los normalizados por Hermes (`native_usage_reviewed.json`). El coste figura como estimación 0,0 (modelo gratuito) y no se compara.

## 5. Ejecución aérea H2 (sin modelo)

Secuencia `6628bc51-e232-45f5-901e-f5fdeb05c6f4`: FINISHED/PASSED; orden `ACCREDITED_BY_EXECUTION_TIMESTAMPS`; escenario `AERIAL_COMPLETED_GROUND_PENDING`. Tolerancias {'horizontal_m': 1.0, 'altitude_m': 0.75}. Fuente: `evaluation/observability/agri_scenario_view_h2_2026_10_24/scenario_view.json`.

| Vehículo | Resultado | POI alcanzados | Error horizontal máximo (m; incluye despegue, waypoints y regreso) | Regreso | Aterrizaje |
| --- | --- | --- | --- | --- | --- |
| drone_01/v1 | PASSED | 2/2 | 0.21 | CONFIRMED | MISSION_LANDING_CONFIRMED |
| drone_02/v2 | PASSED | 2/2 | 0.85 | CONFIRMED | MISSION_LANDING_CONFIRMED |

Los errores son observaciones del ejecutor por AP_DDS en una sola ejecución SITL; no son una medida de precisión física.

## 6. Piloto (10 invocaciones del mismo protocolo H3b; enmienda separada)

- **Protocolo:** `evaluation/observability/agri_scenario_pilot_nous_2026_10_24/protocol.json` (SHA-256 `13a7595fbc9d5e07…`).
- **Enmienda 01:** tras pilot-real-r02 (timeout; driver stopped by residual-process rule). Cambios del driver: wait up to 15 s for own processes to exit before declaring them residual; 60 s pause between invocations; stop after two consecutive invocations ending without a final answer due to provider errors/timeouts.
- **Sin cambios:** prompt 663b63a0; tool get_scenario_view only; pinned sources; provider/model/config; acceptance criteria; timeout 300 s; no retries by the pilot.

| Segmento | Invocaciones | Con respuesta | `STRUCTURED_VALIDATED…` |
| --- | --- | --- | --- |
| protocolo original (pilot-real-r01, pilot-real-r02) | 2 | 1/2 | 1/2 |
| tras enmienda 01 (pilot-real-r03, pilot-real-r04, pilot-real-r05, pilot-real-r06, pilot-real-r07, pilot-real-r08, pilot-real-r09, pilot-real-r10) | 8 | 8/8 | 5/8 |

| Clave | Segmento | Respuesta | Peticiones lógicas (completadas) | Intentos fallidos | Reintentos derivados | Formato | Factuales | Críticas | Claves rechazadas | Aceptación | s | Tokens |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| pilot-real-r01 | protocolo original | RECEIVED | 2 (2) | 0 | 0 | JSON_OBJECT | 23/23 | 12/12 | — | `STRUCTURED_VALIDATED_EXPLANATION_UNREVIEWED` | 43.702 | 10221 |
| pilot-real-r02 | protocolo original | NO_ANSWER_TECHNICAL | 1 (1) | 4 | 4? | — | n/a | n/a | — | `—` | 300.034 | — |
| pilot-real-r03 | tras enmienda 01 | RECEIVED | 1 (1) | 0 | 0 | NOT_JSON | n/a | n/a | — | `NOT_VALIDATED` | 20.176 | 3134 |
| pilot-real-r04 | tras enmienda 01 | RECEIVED | 2 (2) | 0 | 0 | FENCED_JSON_OBJECT | 23/23 | 12/12 | — | `STRUCTURED_VALIDATED_EXPLANATION_UNREVIEWED` | 48.575 | 10429 |
| pilot-real-r05 | tras enmienda 01 | RECEIVED | 2 (2) | 0 | 0 | JSON_OBJECT | 23/23 | 12/12 | — | `STRUCTURED_VALIDATED_EXPLANATION_UNREVIEWED` | 62.467 | 11713 |
| pilot-real-r06 | tras enmienda 01 | RECEIVED | 2 (2) | 0 | 0 | FENCED_JSON_OBJECT | 21/23 (2 por forma) | 12/12 | runs[2f7db1f6].reached_points (forma), runs[febf7c4f].reached_points (forma) | `NOT_VALIDATED` | 171.112 | 18728 |
| pilot-real-r07 | tras enmienda 01 | RECEIVED | 2 (2) | 0 | 0 | JSON_OBJECT | 23/23 | 12/12 | — | `STRUCTURED_VALIDATED_EXPLANATION_UNREVIEWED` | 32.888 | 10066 |
| pilot-real-r08 | tras enmienda 01 | RECEIVED | 2 (2) | 0 | 0 | JSON_OBJECT | 23/23 | 7/12 | claims.current_permissions_checked, claims.detections_made, claims.images_captured, claims.speed_commanded, claims.speed_measured | `NOT_VALIDATED` | 39.768 | 10480 |
| pilot-real-r09 | tras enmienda 01 | RECEIVED | 2 (2) | 0 | 0 | JSON_OBJECT | 23/23 | 12/12 | — | `STRUCTURED_VALIDATED_EXPLANATION_UNREVIEWED` | 63.865 | 11906 |
| pilot-real-r10 | tras enmienda 01 | RECEIVED | 2 (2) | 0 | 0 | JSON_OBJECT | 23/23 | 12/12 | — | `STRUCTURED_VALIDATED_EXPLANATION_UNREVIEWED` | 35.375 | 10191 |

- **Denominadores del informe del piloto:** {'structured_validated_of_attempted': '6/10', 'structured_validated_of_answered': '6/9', 'r1_false_of_analysable': '8/8'}. Fuente: `reporting.agri_scenario_summary.pilot_report(evaluation/observability/agri_scenario_pilot_nous_2026_10_24, evaluation/observability/agri_scenario_pilot_audit_2026_10_25)`.
- Wilson 95 % para 6/10 = [0,354; 0,879] es solo descriptivo: las invocaciones comparten prefijo y caché, y los parámetros de muestreo son desconocidos (`pilot_analysis.json`).
- `r03` no llamó a la herramienta y su salida no es JSON: «Factuales» y «Críticas» no se aplican (n/a).
- **«Reintentos derivados»** es un cálculo de `pilot_report` (intentos fallidos seguidos de un intento completado), no un contador de Hermes. `?` indica que el contador `retry_count` registrado no es monótono y el número de reintentos no puede afirmarse.

- **pilot-real-r02:** eventos registrados (1 petición lógica, `sha256:4195422380faf93a`): 18:01:43 llm_error APIConnectionError/timeout retry_count=0; 18:01:51 llm_error RateLimitError/429 retry_count=1; 18:02:22 llm_error RateLimitError/429 retry_count=2; 18:02:54 llm_error RateLimitError/429 retry_count=0; 18:03:29 llm_call (tool_calls). El contador `retry_count` vuelve a 0 en el último fallo: los registros no permiten afirmar cuántos de esos intentos contó Hermes como reintentos de un mismo ciclo. La petición siguiente (respuesta final) no tiene evento antes del timeout de 300 s; no se reinvocó.
- **pilot-real-r06:** `NOT_VALIDATED` por **forma**: runs[2f7db1f6].reached_points, runs[febf7c4f].reached_points se escribió como objetos (`{poi, status}`) en lugar de una lista de cadenas. El contenido coincide con la vista recibida (mismos POI `REACHED`); el rechazo se conserva y **no** se cuenta como hechos incorrectos. Su evaluación original terminó con una excepción del evaluador, corregida después; ambas aceptaciones se conservan.
