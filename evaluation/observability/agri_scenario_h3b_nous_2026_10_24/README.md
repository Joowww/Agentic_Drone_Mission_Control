# H3b de agri_demo_001: consulta del escenario desde la vista determinista — 24/10/2026

**Resultado: ejecutado, `STRUCTURED_VALIDATED_EXPLANATION_UNREVIEWED`.** El aislamiento, la llamada,
todas las claves estructuradas y todas las claves críticas coinciden con la vista que recibió
Hermes. **No es una validación completa:** la explicación libre está pendiente de revisión humana.
Hubo una sola invocación, sin reintentos.

## Invocación

- Caso `agri-scenario-h3b` de `observability/hermes_capture_run.py`. Antes de invocar se comprobó:
  - preflight `ok: true`;
  - solo `get_scenario_view` registrada, con Tool Search en `"off"`;
  - las cuatro fuentes fijadas sin cambios;
  - el prompt con SHA-256 `663b63a06958b0418535452c3bc62094b6a77dedd20e23671ce5f8f20d498784`, sin valores esperados;
  - el config `c99d1a88…`;
  - la vista que iba a recibir Hermes, idéntica a
    [la evidencia de la vista](../agri_scenario_view_h2_2026_10_24/README.md).
- Una invocación (`nous` / `poolside/laguna-s-2.1:free`) de 17:26:24.988 a 17:27:11.211 UTC, de
  46,1 s, rc 0, sin timeout ni reintento. Config restaurado (`c99d1a88…`), plugin retirado y sin
  procesos propios.
- `review`: `QUERY_CALLS_WITHIN_ALLOWED_TOOLS`. Hubo 2 respuestas del modelo, y en ellas solo se
  ofreció `get_scenario_view`. Se ejecutó 1 llamada (`scenario_id=agri_demo_001`,
  `request_key=agri-demo-001-h2-r01`), sin error, en 86 ms.
- La vista recibida en la sesión es **idéntica** a `scenario_view.json` de la evidencia de la vista.

## Aceptación (`accept_h3b.json`)

| Dimensión | Resultado |
| --- | --- |
| Herramientas permitidas y ejecución | `OK`: exactamente una llamada a `get_scenario_view` y ninguna otra |
| Exactitud estructurada | Todas las claves coinciden con la vista recibida: dos ejecuciones con vehículo, misión, estado, POI, regreso, aterrizaje e inicio/fin del ejecutor (no la admisión) |
| Claves críticas | 12/12 coinciden: `r1_movement_authorized: false`, `r1_commands_sent: false`, `scenario_complete: false`, `sequence_order`, `order_basis: EXECUTION_TIMESTAMPS` y los siete `claims` en `false` |
| Clasificaciones | ninguna, sin `ADMISSION_CONFUSED_WITH_EXECUTION` |
| Explicación | heurísticas sin aviso; **revisión semántica: `REQUIRED_HUMAN`** |
| Formato | JSON dentro de un bloque `json` (`FENCED_JSON_OBJECT`), admitido por `parse_answer` |

## Revisión asistida de la explicación (ChatGPT, transmitida por Joel)

`explanation_review_assisted.json` registra la revisión que Joel transmitió en el chat, **asistida
por ChatGPT**. **No consta como una revisión humana completada por Joel.** No modifica el resultado
automático (`STRUCTURED_VALIDATED_EXPLANATION_UNREVIEWED`) ni la respuesta original. Observaciones:
- invierte armado y despegue de drone_02;
- cita una comprobación que no corresponde a la vista;
- describe de forma incompleta la dependencia `MET`;
- «volvieron a ejecutarse» puede sugerir otra ejecución;
- la frase sobre superposición es ambigua frente al orden acreditado.

Conclusión registrada: **la explicación contiene errores factuales y ambigüedades.** No se volvió a
invocar el modelo ni se ajustó el evaluador. El
[informe determinista](../agri_scenario_report_h2_2026_10_24/README.md) presenta esos mismos hechos
generados por código.

## Observaciones preliminares sobre la explicación (Claude; no sustituyen la revisión de Joel)

Son lecturas de Claude que no modifican el estado. Fragmentos de `hermes_stdout.txt`:

| Fragmento | Observación preliminar |
| --- | --- |
| «La dependencia MET solo indica que el dato de la condición previa se registró; no autoriza movimiento del rover» | Coherente con la vista y con `r1_movement_authorized: false` |
| «el comando land de drone_01 precedió al arm de drone_02», «executor_started_at/finished_at disjuntos» | Coherente con `order.checks` |
| «el despegue de drone_02 precedió al arm de drone_02» | **Incorrecto o sin sentido.** No es una de las comprobaciones de la vista, y el `arm` va antes del `takeoff`. La comprobación que falta citar es «despacho del hijo 2 posterior al resultado del hijo 1» |
| «Los drones volvieron a ejecutarse» | **Impreciso:** puede leerse como una nueva ejecución. Es un registro histórico único |
| «la dependencia lógica está MET (POI_A1 REACHED por drone_01)» | **Incompleto:** `MET` exige además que la secuencia esté COMPLETED. Es la misma imprecisión que en H3 |
| «sin validación de permisos actuales ni superposición de vuelos» | **Ambiguo:** la vista registra `simultaneous_flight: false` y ventanas disjuntas; lo no validado es el marco común |
| Limitaciones de percepción, velocidad y disponibilidad actual | Coherentes con `limitations` y `scope` |

## Comparación descriptiva con H3

| Aspecto | H3 (13:15 UTC) | H3b (17:26 UTC) |
| --- | --- | --- |
| Información disponible | Dos vistas externas por ejecución, más orden, resumen, `R1` y límites como **texto del prompt** | **Una** vista determinista del escenario con procedencia, hashes, cronología separada y límites. El prompt solo lleva instrucciones |
| Herramienta | `get_mission_state` (`view=external`) ×2 | `get_scenario_view` ×1 |
| Contrato de respuesta | JSON de H3: ejecuciones, POI, `R1`, explicación | JSON de H3b: además `order_basis`, inicio y fin del ejecutor, y `claims` |
| Autorización del rover | `r1_movement_authorized: true` (**error crítico**) | `false` |
| Significado de MET | «autoriza mover el rover … en principio» | «solo indica que la condición previa se registró; no autoriza movimiento» (con la imprecisión anotada arriba) |
| Orden y evidencia | Orden correcto, justificado con horas de **admisión** (12:51:18.368 / .376) | Orden correcto, `order_basis: EXECUTION_TIMESTAMPS`, con ventanas del ejecutor y `land`→`arm`; una de las comprobaciones citadas es incorrecta |
| Completitud del escenario | `scenario_complete: false` | `false` |
| Capacidades y limitaciones | No inventó imágenes ni velocidad (revisión manual) | Siete `claims` en `false`, comprobados automáticamente |
| Aceptación | `NOT_VALIDATED` (24/25; falla `r1_movement_authorized`) | `STRUCTURED_VALIDATED_EXPLANATION_UNREVIEWED` (puntuación 1,0; explicación pendiente de revisión) |

**Esto es una comparación descriptiva:**
- **H3** falló una afirmación crítica **estructurada** (`r1_movement_authorized: true`).
- **H3b** pasó la comprobación estructurada, incluidas las 12 claves críticas, pero **su explicación
  libre aún contiene errores factuales y ambigüedades**, según la revisión asistida.
- Pasar la comprobación estructurada no equivale a una respuesta correcta en su totalidad.
- Cambiaron a la vez la fuente de datos, el prompt y el contrato de respuesta, y solo hubo **una**
  invocación de cada caso. **Ninguna de las dos demuestra fiabilidad general**, y la comparación no
  permite atribuir la diferencia a un factor concreto.

La respuesta y la evaluación de H3 se conservan sin cambios.

## Archivos

- **Generados por `review`:** `capture/`, `capture_summary.json`, `run.json` (con prompt y plan del
  caso) y `native_usage_review*.json`.
- `hermes_stdout.txt`: la respuesta original, 3157 bytes.
- `hermes_stderr.txt`: vacío.
- `tool_result_as_received.json`: la llamada y la vista desenvuelta de la sesión real. No
  contiene rutas absolutas.
- `accept_h3b.json`: la aceptación por dimensiones.
- `explanation_review_assisted.json`: la revisión asistida por ChatGPT, añadida después. No es una
  revisión humana completada.
- No se guardan el `session_id` ni la conversación completa. No se ha enviado nada a Opik.
- `SHA256SUMS` cubre todo salvo este README.
