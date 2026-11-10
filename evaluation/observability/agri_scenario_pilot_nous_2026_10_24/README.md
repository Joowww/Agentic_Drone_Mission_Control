# Piloto de consultas sobre el H2 histórico (`agri-scenario-pilot-real`) — 24/10/2026

**Resultado:**
- **Intentadas:** 10 invocaciones del driver sobre el caso `real-h2`, una por clave y sin repetir
  ninguna clave. *(Corregido el 25/10: el original decía «sin reintentos». r02 tuvo reintentos
  internos del cliente Hermes; ver la auditoría.)*
- **Completadas:** 9 con respuesta; 1 timeout por sobrecarga del proveedor.
- **Validación estructurada:** 6/10 intentos y 6/9 respuestas completadas, con la explicación
  libre pendiente de revisión humana.
- **Rechazos:** 3 de las 9 completadas, cada uno por un motivo distinto.

No es una estimación de fiabilidad. Describe este escenario, esta vista, esta petición y esta
configuración en una tarde concreta.

## Auditoría (25/10/2026)

**Las cifras de referencia** las genera el
[informe reproducible](../agri_scenario_pilot_audit_2026_10_25/pilot_report.md) a partir de los
registros, y cada recuento enumera sus claves. Las tablas de este README se escribieron a mano el
24/10; donde difieran, manda el informe generado.

**Tres niveles de repetición:**

| Nivel | Qué es | Piloto |
| --- | --- | --- |
| Invocación del driver | Una ejecución de captura por clave (`pilot-real-rNN`) | 10, sin repetir ninguna clave; el piloto no reintentó nada |
| Petición lógica al modelo | Un `api_request_ref` en los eventos de captura (lo normal es una llamada para pedir la herramienta y otra para responder) | 2 en las invocaciones completas; 1 en r03 (respondió sin herramienta); 1 observada en r02 |
| Reintento del cliente Hermes | Otro intento de la **misma** petición tras un `llm_error` (`agent.api_max_retries` y ciclos de autorrecuperación de Hermes) | Solo en r02: 4 intentos fallidos (1 timeout + 3 × `429 overloaded`) y un quinto con éxito a los 285 s. La petición de respuesta posterior seguía en curso al timeout y no generó evento |

**Periodos.**
- **r01 y r02** se ejecutaron antes de
  [`protocol_amendment_01.json`](protocol_amendment_01.json).
- **r03–r10** se ejecutaron después, con espera de 15 s para los procesos propios, pausas de 60 s y
  una regla de parada por errores consecutivos del proveedor.
- **Se mantuvieron fijos** la petición, la herramienta, las fuentes fijadas, el proveedor y el
  modelo, la configuración, los criterios y el timeout.
- No se atribuye ningún resultado a la enmienda: con 2 y 8 invocaciones no hay base para comparar
  periodos.

**Denominadores que se conservan:**
- 6/10 intentos con validación estructurada;
- 6/9 respuestas completadas con validación estructurada;
- `r1_movement_authorized: false` en 8/8 respuestas analizables.

**r06 conserva sus dos aceptaciones:**
- la original, en la que el evaluador falló con una excepción;
- la posterior a la corrección, `NOT_VALIDATED` por formato.

Que su contenido sea equivalente **no** la convierte en aprobada.

**r08:** la petición v1 dice a la vez «si un dato no figura, escribe `null`» y que cada `claim` es
«true solo si el resultado lo registra», mientras el evaluador espera `false`. El rechazo se
mantiene según el contrato del evaluador, pero la instrucción es ambigua. Antes se describió como
«error de lectura»; esa calificación queda retirada. La propuesta v2 lo trata en
[`protocol_v2_proposal.json`](../agri_scenario_pilot_audit_2026_10_25/protocol_v2_proposal.json).

**Caché:**
- **Qué se observó:** las nueve sesiones con uso registrado informan `cache_read_tokens` mayores que
  cero (448–2 912). Es un recuento del proveedor de tokens de **entrada** servidos desde su caché.
  Las nueve respuestas son distintas.
- **Qué no demuestra ese recuento:** por sí solo, no prueba que las respuestas se reutilicen ni que
  las invocaciones dependan unas de otras.
- **Qué se desconoce:** qué guardó el proveedor, si esa caché influye en el muestreo y si existe
  otra caché que la captura no muestre.

**Evaluador endurecido (25/10).** Los defectos encontrados ante entradas malformadas se corrigieron.
Las sesiones guardadas se reevaluaron por separado en
[`agri_scenario_pilot_audit_2026_10_25`](../agri_scenario_pilot_audit_2026_10_25/reeval_summary.json),
sin ejecutar modelos, y los diez resultados coinciden con los existentes.

## Pregunta y protocolo

- **Pregunta:** si el protocolo del ensayo 1 se puede ejecutar de principio a fin con el mecanismo
  existente, y qué variabilidad y tipos de error aparecen. No se pregunta por fiabilidad.
- **Autorización:** Joel, 24/10/2026: hasta diez invocaciones, claves `pilot-real-r01`…`r10`.
- **Protocolo congelado antes de r01 (`protocol.json`, 17:57:04 UTC):**
  - Caso `agri-scenario-pilot-real`, con `nous` / `poolside/laguna-s-2.1:free`.
  - Config `c99d1a88…` y Hermes `d923a5eb…`.
  - Solo se ofrece `get_scenario_view`, con Tool Search en `"off"`.
  - La petición (`663b63a0…`) es la de H3b y no lleva valores esperados.
  - Las cuatro fuentes fijadas, la vista (`062e774a…`) y las 12 claves críticas de `accept-h3b`.
  - Timeout de 300 s y ningún reintento del piloto.
- **Parámetros de generación:**
  - `reasoning_effort: medium` (config).
  - La temperatura y `top_p` no están fijados, así que el proveedor usa sus valores por defecto, que no conocemos.
  - La interfaz no expone semilla.
- **Antes de r01:** `pilot_dry_run.json` dio `PLAN_READY` y `preflight_before_r01.json` dio `ok`. Ninguna clave del piloto tenía ejecución previa.

### Incidencia y enmienda del driver (`protocol_amendment_01.json`)

1. **Qué paró el driver.** r02 llegó al timeout de 300 s. Al terminar, el driver vio un proceso
   propio (`mcp_death_supervisor` de Hermes) y paró, como establecía su regla.
2. **Comprobación.** Ese proceso salió solo en unos segundos. La configuración estaba restaurada y
   no quedaba ningún plugin, así que no era un fallo de aislamiento ni de restauración.
3. **Causa de r02, según los eventos de captura:**
   - la primera llamada al modelo se cortó a los 180 s;
   - Hermes la reintentó por su cuenta (`max_retries: 3` de su cliente, igual que en r01 y en
     H3b) y los tres intentos siguientes recibieron `429 overloaded`;
   - un quinto intento tuvo éxito y la herramienta se ejecutó a los 285 s (4 reintentos en total;
     ver la auditoría);
   - la respuesta final no llegó antes de los 300 s.
4. **Reanudación.** Se siguió con r03–r10, **sin repetir r02**. El driver cambió en tres cosas:
   - espera hasta 15 s a que los procesos propios terminen;
   - deja 60 s entre invocaciones;
   - para si dos invocaciones seguidas acaban sin respuesta por errores del proveedor.

   La petición, la herramienta, las fuentes, el modelo, los criterios y el timeout no cambiaron.
5. **Cierre.** Todas las invocaciones restauraron config y plugin. Tras cada una quedó el config
   `c99d1a88…`, ningún plugin y ningún proceso propio.

### Defecto del evaluador encontrado (corregido después del piloto)

- **Qué pasó:** r06 escribió `reached_points` como objetos (`{"poi": …, "status": …}`), y
  `accept_scenario_view_answer` lanzó `TypeError` al ordenarla. Su `accept_h3b.json` original
  conserva ese error.
- **Corrección:** al terminar las diez invocaciones, `reached_points` solo se ordena si es una
  lista de cadenas; cualquier otra forma cuenta como discrepancia. Hay un test de regresión.
- **Reevaluación:** todas las sesiones se volvieron a evaluar sin inferencia
  (`accept_h3b_post_fix.json`). Las otras ocho son **idénticas** a su evaluación original; r06 pasa
  a `NOT_VALIDATED` por formato.
- **Cierre del caso:** el caso `agri-scenario-pilot-real` queda cerrado (`superseded_by`). Sus pins
  describen las fuentes que se ejecutaron.

## Tabla por invocación

| Clave | Inicio (UTC) | s | Herramienta | Formato | Factual | Críticas | Estado | Tokens (entrada/salida) | Caché leída |
| --- | --- | ---: | --- | --- | --- | --- | --- | --- | ---: |
| r01 | 17:57:32 | 43,7 | 1 llamada, vista idéntica | JSON | OK | 12/12 | `STRUCTURED_VALIDATED…` | 7 071 / 1 230 | 1 920 |
| r02 | 17:58:35 | 300,0 | 1 llamada a los 285 s | — | — | — | **timeout** (1 timeout de API + 3×429) | desconocidos | — |
| r03 | 18:04:42 | 20,2 | **ninguna** | no JSON | — | — | `NOT_VALIDATED` (sin llamada) | 2 019 / 443 | 672 |
| r04 | 18:06:08 | 48,6 | 1, idéntica | JSON en bloque | OK | 12/12 | `STRUCTURED_VALIDATED…` | 8 122 / 1 411 | 896 |
| r05 | 18:08:04 | 62,5 | 1, idéntica | JSON | OK | 12/12 | `STRUCTURED_VALIDATED…` | 8 150 / 2 667 | 896 |
| r06 | 18:10:13 | 171,1 | 1, idéntica | JSON en bloque | **`reached_points` (formato)** | 12/12 | `NOT_VALIDATED` | 7 741 / 9 643 | 1 344 |
| r07 | 18:14:11 | 32,9 | 1, idéntica | JSON | OK | 12/12 | `STRUCTURED_VALIDATED…` | 6 079 / 1 075 | 2 912 |
| r08 | 18:15:50 | 39,8 | 1, idéntica | JSON | OK | **7/12** | `NOT_VALIDATED` (5 `claims` en `null`) | 8 574 / 1 458 | 448 |
| r09 | 18:17:36 | 63,9 | 1, idéntica | JSON | OK | 12/12 | `STRUCTURED_VALIDATED…` | 8 158 / 2 852 | 896 |
| r10 | 18:19:47 | 35,4 | 1, idéntica | JSON | OK | 12/12 | `STRUCTURED_VALIDATED…` | 8 561 / 1 182 | 448 |

«Vista idéntica» significa que la vista recibida en la sesión tiene el digest congelado
`062e774a…`. «Tokens» son los del turno principal; la generación del título añade unos 530 por
invocación.

## Resultados por dimensión

- **Herramientas permitidas:** en las 10 invocaciones solo se ofreció `get_scenario_view`, y nunca
  se pidió otra herramienta.
- **Llamadas a la herramienta:** 9 llamaron a `get_scenario_view` (r02, sin llegar a responder);
  r03 no la llamó.
- **Formato:** 8 JSON analizables, 2 de ellos dentro de un bloque de código. r03 devolvió un bloque
  `{json}` que no se pudo analizar.
- **Exactitud factual:** todas las respuestas analizadas coinciden con la vista salvo r06, cuyo
  `reached_points` tiene otro formato aunque el contenido es equivalente.
- **Claves críticas:** un único fallo, en r08: cinco `claims` en `null` en vez de `false`. La
  petición dice «si un dato no figura, escribe `null`», y la vista sí da la información
  (`perception: NONE`, `commanded: false`…). *(Corregido el 25/10: no se califica como error de
  lectura; la instrucción es ambigua, ver la auditoría.)* **`r1_movement_authorized`
  fue `false` en las 8 respuestas analizables**, y no apareció el error de H3.
- **Explicación libre:** **revisión humana pendiente**. Los avisos heurísticos solo saltaron en r08,
  y son un falso positivo (la frase es una negación).
- **Fallos técnicos:** un timeout del proveedor (r02) y un defecto del evaluador (r06), ya corregido.

## Resumen descriptivo

- **Invocaciones:** 10 planificadas, 10 intentadas, 9 con respuesta y aceptación, y 0 sin ejecutar.
- **Estados:** 6 `STRUCTURED_VALIDATED_EXPLANATION_UNREVIEWED`, 3 `NOT_VALIDATED` (sin llamada,
  formato y críticas) y 1 sin respuesta.
- **Variación entre respuestas:** las 9 respuestas son distintas entre sí y no hay ninguna repetida.
  Entre las 8 analizables, los campos que varían son `evidence_source` (texto libre), los cinco
  `claims` de r08 y la forma de `reached_points` en r06. Los demás campos estructurados coinciden.
- **Caché:** las 9 sesiones con uso registrado informan tokens de entrada leídos de la caché del
  proveedor (448–2 912). Las 9 respuestas son distintas. Esto no demuestra por sí solo dependencia
  ni reutilización, ni su ausencia (ver la auditoría).
- **Duración:**
  - total: 818 s, sin contar las pausas;
  - completadas: de 20 s a 171 s;
  - r02: 300 s, hasta el timeout.
- **Tokens:** 96 868 en las 9 sesiones con datos de uso. No se conocen los tokens de r02, porque no
  tiene archivo de uso.
- **Coste:**
  - **lo que informa Hermes:** 0,0 USD, con `cost_status: estimated` y fuente
    `provider_models_api`, para un modelo `:free`;
  - **lo facturado y los límites de cuota:** no están acreditados.
- **Por qué no hay intervalos:** un intervalo de Wilson exigiría invocaciones independientes y
  con la misma distribución. No se puede justificar: todas comparten la petición, los parámetros de
  muestreo y el estado del proveedor (incluida su caché) son desconocidos, y en r02 hubo
  sobrecarga. Solo se dan recuentos.

## Comparación descriptiva con H3b

H3b (una invocación) y el piloto (diez) usan la misma vista, la misma petición, el mismo contrato y
el mismo modelo, pero son protocolos distintos y se ejecutaron en momentos distintos. No se
atribuye ninguna diferencia a una causa concreta.

| Aspecto | H3b | Piloto |
| --- | --- | --- |
| Respuestas con validación estructurada | 1/1 | 6/10 |
| `r1_movement_authorized` | `false` | `false` en las 8 analizables |
| Tipos de fallo | ninguno estructurado | sin llamada (1), formato (1), `claims` en `null` (1), timeout (1) |
| Explicación | revisión asistida con errores (armado/despegue, MET incompleto…) | pendiente; observaciones asistidas preliminares en la hoja |

## Archivos

- **Protocolo:**
  - `protocol.json` y `protocol_amendment_01.json`: el protocolo congelado y su enmienda.
  - `pilot_dry_run.json` y `preflight_before_r01.json`: comprobaciones previas a r01.
- **Ejecución y análisis:**
  - `driver_log.jsonl`: un registro por invocación, más la parada tras r02.
  - `pilot_analysis.json`: la tabla y el resumen, generados por `scripts/analyze.py`.
- **Explicaciones:**
  - `explanation_review_sheet.md`: la **hoja de revisión humana**, sin completar. Desde el 25/10 la
    genera `reporting.agri_scenario_summary pilot-review-sheet`, con referencias y hashes y una
    observación asistida por criterio. La versión del 24/10, que tampoco tenía revisión, se conserva
    como `explanation_review_sheet_v1_2026_10_24.md`.
  - `explanation_observations_assisted.json` (24/10) y `explanation_observations_by_criterion.json`
    (25/10): observaciones de Claude, etiquetadas como asistidas.
- **`pilot-real-rNN/`:**
  - salida de `review` (`run.json`, `capture/`, `capture_summary.json`, `native_usage_*`);
  - `preflight.json` y `capture_output.json`;
  - `hermes_stdout.txt` / `hermes_stderr.txt`;
  - `tool_result_as_received.json`;
  - `accept_h3b.json` (original) y `accept_h3b_post_fix.json`.
- **`scripts/`:** copias del driver, del análisis y del generador de la hoja.
- **Rutas personales:** en las copias de salidas de comandos y en los scripts, las rutas del
  directorio personal se sustituyeron por `~`, `<repo>` y `<scratchpad>`. Los scripts copiados no
  son ejecutables tal cual.
- **Manifiestos:** `SHA256SUMS` en cada `pilot-real-rNN/` y en la raíz de esta evidencia (este
  README queda fuera, como en las anteriores).

No hubo envíos a Opik, simulación, controles, cambios de misiones ni nuevas invocaciones fuera de
las diez claves.
