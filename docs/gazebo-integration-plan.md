# Plan mínimo: de la demo offline al rover simulado (ArduRover SITL + Gazebo)

Estado a 07/11/2026 (actualizado por la tarde). No se ha abierto Gazebo ni SITL y no se ha emitido ningún comando. El control del rover es **solo** el executor protegido del subsistema rover; este lado no crea otro.

## Flujo

Mission Orchestrator → Drone Agent → Rover Agent → Mission Coordinator → puente de ejecución del rover → validador de seguridad → executor ArduRover (subsistema rover) → ArduRover SITL → Gazebo.

| Componente | Dónde | Estado |
| --- | --- | --- |
| Supervisor `/4`, Drone Agent `/3` y Rover Agent `/3` con Qwen | `brief_provenance.py`, `llm_agents.py` | Probado con Qwen real en M4c-r1 (un caso) y offline |
| Coordinador (dependencias, caducidad, autorización como registro) | `mission_coordinator.py` | Probado offline |
| Puente → `rover-execution-request/1` | `rover_executor_bridge.py` | Probado offline |
| Autorización humana ligada al plan | `human_authorization.py` | Probado offline; sin interfaz humana real |
| Validador de seguridad propio (`handoff_checks`) | `rover_mission_payload_bridge.py` | Probado offline (v1) |
| Adaptador al contrato v2 del subsistema rover | `rover_v2_bridge.py` | Probado contra dos *snapshots*: `57a0e303a` y `2e206f1fa` con su parche de revisión. Con el revisado, 0 errores de esquema |
| Interfaces SITL (objetivo, transformación, *feedback*) | `rover_sitl_interfaces.py`, `frames2d.py` (sitio → `map`/`odom` → `base_link`) | Probado offline; las reglas de transformación coinciden con las del v2 |
| Traspaso real al código del subsistema rover (*snapshot*) | `rover_handoff.py`, `rover_snapshot_runner.py` | Probado en los dos *snapshots*: 18 casos, *ledger*, conversión delegada y la batería de 18 misiones, con cero comandos (`results/codex_integration_v2_2026-11-07_0dab97317/`) |
| Sobre de envío al executor | `rover_handoff.submission_envelope` | Preparado: `READY_TO_SUBMIT_NOT_EXECUTED`, sin comandos. Falta la entrada v2 del executor del subsistema rover, que está sin commitear |
| Recibo de operador autenticado | Servicio de verificación | **Pendiente.** El *ledger* de referencia del subsistema rover (revisado) emite `DECLARED` para *fixtures*, y su v2 lo rechaza como debe |
| Executor protegido, localización acreditada y transformación sitio → `odom` | El subsistema rover | **Pendiente** (en desarrollo; SITL del rover NO_GO) |
| Envío de eventos de SITL al coordinador | `sitl_events.py` | Adaptador preparado y probado con *fixtures*. Hay un puerto inyectado y *namespaces* `/ap/vN` conocidos, pero ningún *topic* acreditado. **Falta** una ingestión SITL acreditada |
| Conversión sitio → rover | `rover_goal_contract.py` y el adaptador del subsistema rover | **Decidido: `ROVER_ADAPTER`.** Este lado entrega `goal_handoff` (`REQUIRED_NOT_APPLIED`). El adaptador del subsistema rover no está en ningún commit |

## Interfaces (este lado prepara; el subsistema rover ejecuta)

| Necesidad | Interfaz | Regla |
| --- | --- | --- |
| Objetivo terrestre en el marco del sitio | `SiteGoal` (desde la compuerta de percepción) | Solo POI declarados; σ propagada |
| Transformación al `odom` del rover | `site_goal_to_odom(goal, transform)` | Solo con una transformación rígida 2D **acreditada** (validada, con procedencia, incertidumbre y vigencia); sin ella, error y nada se convierte |
| Localización | Forma v2: marco, x, y, `uncertainty_m`, fuente con su sha, `validated` y `observed_at_utc` | La da el subsistema rover; edad e incertidumbre frente a los límites del operador |
| Telemetría y estado | `RoverExecutorPort.observe()` / `status()` | Implementación solo en el subsistema rover |
| Autorización | Registro `human-authorization/1` + recibo autenticado (v2) | Nunca a partir de una decisión del LLM; `READY_TO_SUBMIT` no autoriza |
| Inicio | `RoverExecutorPort.submit(payload v2, receipt)` | Solo después de pasar `handoff_checks` y el validador v2 |
| Finalización | `feedback_type("COMPLETED_UNVERIFIED")` | No se acepta hasta que la localización lo confirma |
| Aborto y STOP | `stop_request` → `RoverExecutorPort.stop()` | Siempre permitido; un STOP no confirmado deja la misión en `UNKNOWN` |
| *Feedback* | `feedback_type()` → `EXECUTOR_FEEDBACK` | Lo no reconocido pasa a `UNKNOWN`; nunca se asume éxito |

## Pasos mínimos (cada uno con su propia autorización)

1. **El subsistema rover**: que el SITL del rover salga de NO_GO, que haya una localización acreditada y una transformación sitio → `odom` medida y validada, y que el executor implemente `submit`, `status` y `stop`.
2. **El subsistema rover**: promover a un commit su parche de revisión (resuelve `bridge_scope_sha256`) y su adaptador de entrada v2.
   - Después, este lado cambia `conversion_owner` a `ROVER_ADAPTER` y llama a ese adaptador desde el *snapshot*.
3. **Puente de eventos SITL → coordinador**: una fuente acreditada nueva en `OBSERVATION_KINDS_BY_EVENT_SOURCE`, con pruebas propias.
   - Falta confirmar los *topics* reales bajo `/ap/v1`, `/ap/v2` y `/ap/v3` (línea base `feature/ardupilot-ros2`) y fijarlos en un `TopicMap`.
4. **Primera prueba conjunta sin movimiento**: un *payload* v2 `READY_TO_SUBMIT` y un recibo de prueba hasta el executor, que lo rechaza en dry-run.
5. **Primer movimiento en SITL** solo con autorización explícita de Joel, con los límites del operador, a menos de 1 m y con STOP probado.
