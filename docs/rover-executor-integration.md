# Propuesta de integración: Rover Agent → ejecutor del rover (contrato del subsistema rover)

Este documento es una **propuesta**: no se ha conectado nada.
- **Contrato del subsistema rover:** `tools/rover_vehicle_contract.py` y `tools/jetracer_dry_run_adapter.py`, en el commit `218697f40` de su rama. Solo se han leído; no se importan ni se modifican.
- **Puente en este worktree:** `multiagent/rover_executor_bridge.py`, que produce y comprueba las mismas formas como diccionarios, con 4 tests.

## Separación de responsabilidades

```
LLM (Rover Agent, contrato v3)  ─propone→  rover_gate.check_v3 + agente rover determinista  ─valida→
coordinador (multiagent/mission_coordinator.py)  ─READY_FOR_AUTHORIZATION→  humano  ─autoriza un alcance→
precondiciones en ese instante  ─si todas se cumplen→  RoverVehicleExecutor.execute()   (hoy: nunca)
```

El LLM nunca ve ni produce velocidad, timeout, autorización ni nada ejecutable.

| Pregunta | Respuesta |
| --- | --- |
| **Qué emite el Rover Agent** | Una decisión tipada por objetivo: `PLAN_TO_DECLARED_POI`, `WAIT_FOR_OBSERVATION` o `CANNOT_PLAN` más un motivo cerrado. Tras la compuerta queda como tarea terrestre `{task_id, vehicle_id, start_point, target_point (POI declarado), after_aerial_point (derivado)}` dentro de una propuesta `PENDING_AUTHORIZATION` |
| **Qué acepta el ejecutor** | `NavigationPlan(plan_id, frame, target_x_m, target_y_m, max_speed_mps, timeout_s)`. `rover_executor_bridge.navigation_plan` lo construye desde el POI declarado, en el marco del sitio. `max_speed_mps` y `timeout_s` salen **solo** de la autorización humana |
| **Validaciones obligatorias** (`preconditions`) | Autorización humana con el `scope_sha256` exacto; fuente de posición declarada; estado del vehículo en el mismo marco que el plan; posición presente; odometría fresca (≤ 1 s); vehículo sano y sin failsafes; velocidad dentro de la capacidad; adaptador no dry-run. Cualquier fallo significa que no hay `execute()` |
| **Cómo se representa la autorización** | `ExecutionAuthorization(scope_sha256, human_authorized)`. El alcance es el hash del plan exacto, el vehículo y la propuesta (`authorization_scope`): otra velocidad, otro objetivo u otra propuesta dan `AUTHORIZATION_SCOPE_MISMATCH` |
| **Qué feedback devuelve el vehículo** | `ExecutionFeedback(status, state, error, physical_effect)`, que `feedback_event` traduce a un evento del coordinador: `GROUND_TASK_REFUSED_BY_EXECUTOR`, `GROUND_TASK_FAILED`, `GROUND_TASK_STATUS` o `GROUND_TASK_PHYSICAL_EFFECT_REPORTED` (este último no se espera offline y obliga a parar y revisar) |
| **Cómo se solicita una parada** | `stop_request` → `RoverVehicleExecutor.stop()`. Siempre está permitida y no necesita autorización; su *feedback* se propaga igual (`NO_PHYSICAL_OUTPUT` en el adaptador dry-run) |
| **Cómo se propaga un error** | Un `error` en el *feedback* produce un evento al coordinador, que bloquea la tarea; nunca se infiere éxito del silencio |
| **Si falta localización** | `NO_POSITION_SOURCE` / `NO_POSITION`: no se ejecuta. El agente puede seguir **planificando** a POI declarados: la localización es una condición de ejecución, no de planificación (contrato v3) |
| **Si la odometría caduca** | Antes de ejecutar: `ODOMETRY_STALE`, sin `execute()`. Durante la ejecución (futuro): el coordinador pide `stop()` y la tarea queda `BLOCKED_*`, como ya hace con los informes caducados del dron (`BLOCKED_DRONE_REPORTS_STALE`) |

## Estado actual con el JetRacer (lo que declara el adaptador del subsistema rover)

Con la autorización correcta, `preconditions` sigue devolviendo siete motivos de bloqueo: `NO_POSITION_SOURCE`, `FRAME_MISMATCH`, `NO_POSITION`, `ODOMETRY_STALE`, `VEHICLE_NOT_HEALTHY`, `SPEED_NOT_WITHIN_CAPABILITY` y `DRY_RUN_ADAPTER`. Solo un vehículo hipotético, plenamente acreditado, deja la lista vacía (test).

## Qué falta para conectarlo

1. Una fuente de posición acreditada del JetRacer.
2. La transformación del marco del sitio a la odometría del rover.
3. Un driver real con stop y watchdog (subsistema rover).
4. Un registro de autorizaciones por `scope_sha256`.
5. El cableado del coordinador con el ejecutor, con parada ante caducidad.
6. Pruebas en SITL del rover primero (hoy NO_GO, el subsistema rover).

## Contrato `tfg.rover.mission-execution/1` del subsistema rover (comprobado el 06/11/2026)

**Qué se ha comparado.** `schemas/rover-mission-execution-v1.schema.json` y `tools/rover_mission_payload.py` del subsistema rover, en `f2fd78ae1`, que es su último cambio y está contenido en `b6d07388a`. Se leen con `git show`, nunca desde el árbol de trabajo del subsistema rover, que ese día tenía cambios sin confirmar. No se ha modificado nada del subsistema rover.

**El adaptador.** `multiagent/rover_mission_payload_bridge.py` traduce nuestra `rover-execution-request/1` al formato del subsistema rover sin inventar nada. Lo que falta queda vacío, y el validador del subsistema rover lo rechaza.

**Las pruebas.** `tests/test_multiagent_rover_contract_v1.py` pasa cada caso por el validador y el esquema **del subsistema rover**:

| Caso | Decisión del subsistema rover |
| --- | --- |
| Solicitud de la demo tal cual (sin límites humanos, sin autorización, sin localización) | `REJECTED`: `LOCALIZATION_MISSING_OR_UNVALIDATED`, `LOCALIZATION_PROVENANCE_MISSING`, `CONSTRAINTS_MISSING`, `HUMAN_AUTHORIZATION_MISSING_OR_INVALID` |
| Fixture completo con una localización `TEST_FIXTURE` y una autorización con el *scope* exacto | `READY_TO_SUBMIT`, con `commands: []` y `movement_authorized: false` (el subsistema rover nunca devuelve `READY_TO_EXECUTE`) |
| Localización en otro marco, no validada o sin procedencia; observación sin sha | `REJECTED` con el motivo correspondiente |
| Ventana de validez caducada o futura | `PAYLOAD_EXPIRED` / `PAYLOAD_NOT_YET_VALID` |
| Tarea condicional que aún espera su observación | No se traduce: no hay coordenadas y no se inventan |

**La autorización es un registro, no un booleano** (`human_authorization.py`, `tfg.multiagent.human-authorization/1`). El registro contiene:
- el operador identificado;
- la misión, el rover y la propuesta;
- el `plan_id` y el `plan_sha256`, y el `scope_sha256`;
- los límites autorizados y una ventana de validez;
- su propio *digest*.

`check()` recalcula el plan y el *scope* a partir de la solicitud. `preconditions()`, el coordinador y el adaptador al subsistema rover solo aceptan este registro.

**Chequeos de entrega** (`handoff_checks`), más estrictos que el v1 del subsistema rover:
- identidad de misión y de rover;
- plan y autorización;
- marcos, o una transformación acreditada;
- incertidumbre (objetivo + localización) y edad de la localización frente a los límites del operador;
- validez del *payload* dentro de la de la autorización y del objetivo;
- dependencias cumplidas;
- ningún movimiento si el objetivo es condicional.

Pasarlos solo permite **enviar** la propuesta al executor protegido, que vuelve a comprobarla.

**Fixtures.** Hay 14 casos fijos en `fixtures/rover_contract_mission_execution_v1_cases.json`, con la decisión que debe dar cada lado; las pruebas los regeneran para detectar derivas.

**Borrador v2 del subsistema rover.** `schemas/rover-mission-execution-v2.schema.json` existe sin commit en su árbol. Añade `plan_id`, `plan_sha256` y `operator_limits` (velocidad, tiempo, distancia, incertidumbre y edad de la localización). Va en la misma dirección, pero no se prueba contra él hasta que el subsistema rover lo confirme.

**Discrepancias registradas** (`DISCREPANCIES` en el módulo):
1. **Objetivo.** Nosotros usamos un POI declarado; el subsistema rover, coordenadas x/y en un marco. Se traduce desde el punto del sitio.
2. **`conditional`.** el subsistema rover exige coordenadas también para una tarea condicional; nosotros mantenemos la espera en el coordinador.
3. **Autorización.** El validador del subsistema rover solo comprueba la forma de `scope_sha256`: un *payload* con un *scope* ajeno y `human_authorized: true` llega a `READY_TO_SUBMIT`. Nuestro adaptador no pasa esa autorización y nuestras `preconditions` la rechazan (`AUTHORIZATION_SCOPE_MISMATCH`). **Punto abierto para el subsistema rover:** el executor protegido debe recalcular el *scope*.
4. **Restricciones.** el subsistema rover acepta un objeto libre (`minProperties` 1); nosotros usamos `max_speed_mps` y `timeout_s` tipados, que solo pone un humano.
5. **Localización.** el subsistema rover no exige frescura (`observed_monotonic_s` es opcional); la frescura sigue en nuestras `preconditions` (≤ 1 s).
6. **Dentro del subsistema rover.** Su esquema JSON no puede expresar «marco de localización = marco del objetivo»; solo lo rechaza el validador en Python. Hay que ejecutar siempre el validador, no solo el esquema.
7. **Formas distintas.** Las dependencias son objetos en nuestro lado y cadenas en el del subsistema rover (`after:condition[:point]`). La parada son cadenas de `stop_conditions` en el *payload*; nuestro `stop_request` y `feedback_event` no cambian.
8. **Límites del operador.** El v1 del subsistema rover acepta (`READY_TO_SUBMIT`) una incertidumbre excesiva, una localización caducada, dependencias sin cumplir y una validez más larga que la autorización. Nuestros chequeos de entrega lo bloquean. Su borrador v2 añade `operator_limits`.
9. **Transformación de marcos.** El v1 exige que la localización esté en el marco del objetivo. Una transformación acreditada tendría que aplicarse antes de construir el *payload*, y hoy no hay ninguna acreditada.

## Contrato v2 del subsistema rover (`1514053da`, comprobado el 07/11/2026)

Se ha confirmado `tfg.rover.mission-execution/2` y un adaptador de nuestra `rover-execution-request/1` (`tools/rover_agent_adapter.py`). Nuestro adaptador versionado, `rover_v2_bridge.py`, y 23 pruebas lo validan contra su código, leído con `git show`.

Qué comprueban las pruebas:
- **la solicitud real de M4c-r1 espera** (`WAITING`), porque ningún humano ha fijado límites;
- el *hash* del plan;
- los marcos y las transformaciones rígidas;
- la vigencia;
- el recibo de operador autenticado: ausente, revocado, no autenticado o ligado a otro plan;
- la velocidad y el tiempo máximo, que salen del plan humano;
- las formas mal construidas y el STOP;
- que nunca sale un comando.

Problemas de compatibilidad:
1. **Forma de la autorización.** Su adaptador espera `{scope_sha256, human_authorized}`, y nuestro registro no tiene esa forma. `bridge_view()` deriva esa forma **solo** de un registro comprobado.
2. **Inconsistencia dentro de su contrato.** El adaptador exige `bridge_scope_sha256` en el recibo y lo copia a `payload.authorization`, pero su esquema v2 no admite ese campo. El validador Python devuelve `READY_TO_SUBMIT` y el esquema rechaza ese único campo. **Queda como punto abierto para el subsistema rover.**
3. **Responsabilidades que siguen en nuestro lado.** La validez de la observación y que las dependencias aéreas estén cumplidas las comprueba `handoff_checks`.
