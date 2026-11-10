# Informe reproducible del piloto `agri_scenario_pilot_nous_2026_10_24`

Generado por `reporting.agri_scenario_summary pilot-report` a partir de los registros guardados.
Sin inferencias. Cada recuento enumera las claves que lo forman.

## Denominadores

| Medida | Valor |
| --- | --- |
| structured_validated_of_attempted | 6/10 |
| structured_validated_of_answered | 6/9 |
| r1_false_of_analysable | 8/8 |

## Recuentos y claves

| Categoría | n | Claves |
| --- | ---: | --- |
| `planned` | 10 | r01, r02, r03, r04, r05, r06, r07, r08, r09, r10 |
| `attempted` | 10 | r01, r02, r03, r04, r05, r06, r07, r08, r09, r10 |
| `answered` | 9 | r01, r03, r04, r05, r06, r07, r08, r09, r10 |
| `no_answer_technical` | 1 | r02 |
| `structured_validated` | 6 | r01, r04, r05, r07, r09, r10 |
| `not_validated` | 3 | r03, r06, r08 |
| `tool_not_called` | 1 | r03 |
| `other_tool_requested` | 0 | — |
| `unparseable_answer` | 1 | r03 |
| `schema_failures` | 1 | r06 |
| `critical_failures` | 1 | r08 |
| `analysable_answers` | 8 | r01, r04, r05, r06, r07, r08, r09, r10 |
| `r1_movement_authorized_false` | 8 | r01, r04, r05, r06, r07, r08, r09, r10 |
| `heuristic_flags` | 1 | r08 |
| `client_retries` | 1 | r02 |
| `timed_out` | 1 | r02 |
| `evaluator_error_original` | 1 | r06 |
| `before_amendment` | 2 | r01, r02 |
| `after_amendment` | 8 | r03, r04, r05, r06, r07, r08, r09, r10 |
| `tokens_unknown` | 1 | r02 |

## Por invocación

| Clave | Periodo | s | Peticiones (completadas/observadas) | Intentos fallidos | Reintentos del cliente | Llamadas a la vista | Vista congelada | Formato | Esquema | Críticas | Aceptación original | Tras corrección | Reevaluación idéntica | Tokens totales | Caché leída |
| --- | --- | ---: | --- | ---: | ---: | ---: | --- | --- | --- | --- | --- | --- | --- | ---: | ---: |
| pilot-real-r01 | antes de enmienda | 43.702 | 2/2 | 0 | 0 | 1 | True | JSON_OBJECT | — | — | STRUCTURED_VALIDATED_EXPLANATION_UNREVIEWED | STRUCTURED_VALIDATED_EXPLANATION_UNREVIEWED | True | 10221 | 1920 |
| pilot-real-r02 | antes de enmienda | 300.034 | 1/1 | 4 | 4 | 1 | — | — | — | — | — | — | — | — | — |
| pilot-real-r03 | tras enmienda | 20.176 | 1/1 | 0 | 0 | 0 | — | NOT_JSON | — | — | NOT_VALIDATED | NOT_VALIDATED | True | 3134 | 672 |
| pilot-real-r04 | tras enmienda | 48.575 | 2/2 | 0 | 0 | 1 | True | FENCED_JSON_OBJECT | — | — | STRUCTURED_VALIDATED_EXPLANATION_UNREVIEWED | STRUCTURED_VALIDATED_EXPLANATION_UNREVIEWED | True | 10429 | 896 |
| pilot-real-r05 | tras enmienda | 62.467 | 2/2 | 0 | 0 | 1 | True | JSON_OBJECT | — | — | STRUCTURED_VALIDATED_EXPLANATION_UNREVIEWED | STRUCTURED_VALIDATED_EXPLANATION_UNREVIEWED | True | 11713 | 896 |
| pilot-real-r06 | tras enmienda | 171.112 | 2/2 | 0 | 0 | 1 | True | FENCED_JSON_OBJECT | runs[2f7db1f6].reached_points, runs[febf7c4f].reached_points | — | EVALUATOR_ERROR | NOT_VALIDATED | True | 18728 | 1344 |
| pilot-real-r07 | tras enmienda | 32.888 | 2/2 | 0 | 0 | 1 | True | JSON_OBJECT | — | — | STRUCTURED_VALIDATED_EXPLANATION_UNREVIEWED | STRUCTURED_VALIDATED_EXPLANATION_UNREVIEWED | True | 10066 | 2912 |
| pilot-real-r08 | tras enmienda | 39.768 | 2/2 | 0 | 0 | 1 | True | JSON_OBJECT | — | claims.current_permissions_checked, claims.detections_made, claims.images_captured, claims.speed_commanded, claims.speed_measured | NOT_VALIDATED | NOT_VALIDATED | True | 10480 | 448 |
| pilot-real-r09 | tras enmienda | 63.865 | 2/2 | 0 | 0 | 1 | True | JSON_OBJECT | — | — | STRUCTURED_VALIDATED_EXPLANATION_UNREVIEWED | STRUCTURED_VALIDATED_EXPLANATION_UNREVIEWED | True | 11906 | 896 |
| pilot-real-r10 | tras enmienda | 35.375 | 2/2 | 0 | 0 | 1 | True | JSON_OBJECT | — | — | STRUCTURED_VALIDATED_EXPLANATION_UNREVIEWED | STRUCTURED_VALIDATED_EXPLANATION_UNREVIEWED | True | 10191 | 448 |

## Errores del cliente por invocación

- pilot-real-r02, petición 1: `APIConnectionError` (timeout, HTTP —, retry_count 0, max_retries 3)
- pilot-real-r02, petición 1: `RateLimitError` (overloaded, HTTP 429, retry_count 1, max_retries 3)
- pilot-real-r02, petición 1: `RateLimitError` (overloaded, HTTP 429, retry_count 2, max_retries 3)
- pilot-real-r02, petición 1: `RateLimitError` (overloaded, HTTP 429, retry_count 0, max_retries 3)

## Tiempos, tokens y coste conocidos

- Tokens totales en 9 sesiones con uso registrado: 96868.
- Duración total de las invocaciones (sin pausas): 817.962 s.
- Coste estimado por Hermes: 0 USD (estimación, no facturación).

## Datos desconocidos

- tokens, coste y vista recibida de las sesiones sin uso exportado (pilot-real-r02)
- coste facturado y cuota del proveedor (Hermes solo informa una estimación)
- temperatura, top_p y semilla (valores por defecto del proveedor, no expuestos)
- peticiones en curso cuando el timeout terminó una invocación (no generan evento)
- qué almacenó o reutilizó el proveedor más allá de cache_read_tokens

## Enmienda del driver

Registrada a las 2026-10-24T18:04:33.893782+00:00 (UTC).
Cambió: wait up to 15 s for own processes to exit before declaring them residual, 60 s pause between invocations, stop after two consecutive invocations ending without a final answer due to provider errors/timeouts.
Permaneció fijo: prompt 663b63a0, tool get_scenario_view only, pinned sources, provider/model/config, acceptance criteria, timeout 300 s, no retries by the pilot.
Los periodos se separan por la hora de inicio de cada invocación; no se atribuye ningún resultado a la enmienda.

