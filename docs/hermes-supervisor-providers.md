# Supervisor multiagente con Hermes: guía técnica de integración

Estado a 24/11/2026, rama `integration/multiagent-supervisor`.

El diseño del supervisor (grafos, estados, contratos y seguridad) está en [multiagent-supervisor.md](multiagent-supervisor.md). Este documento cubre cómo funciona integrado con Hermes, con los proveedores de modelos y con los ejecutores: cómo arrancarlo, qué registra, qué se ha comprobado y qué falta.

## 1. Arquitectura real

```mermaid
flowchart LR
  OP[Operador] -->|lenguaje natural| HM[Hermes v0.22.2<br/>perfil tfg-supervisor]
  HM -->|LLM: proveedor seleccionado| LLM[(ollama-local / eetac / aida-qwen)]
  HM -->|MCP stdio| MCP[multiagent.supervisor.mcp_server<br/>registry · plan_mission · get_manifest · mission_status]
  MCP --> SUP[Supervisor LangGraph<br/>grafo de planificación]
  SUP --> DA1[DroneAgent_drone_01]
  SUP --> DA2[DroneAgent_drone_02]
  SUP --> RA[RoverAgent_rover_01]
  SUP --> FILES[(misión: drone_1.plan · drone_2.plan · rover.plan<br/>manifest.json · decisions · trace · results)]
  OP -->|CLI approve / execute / ingest| EX[Supervisor LangGraph<br/>grafo de ejecución]
  EX -->|puerta| H2[frontera H2: petición protegida preparada]
  EX -->|puerta| RC[tfg.rover.plan-mission-execution/1<br/>petición preparada, sin handler]
  EX --> RES[(vehicle_result · result.json SafeFlight · global_result)]
```

Hermes **solo planifica y consulta**. La aprobación, la ejecución y la ingestión de resultados reales son órdenes de la CLI del operador, y el MCP no las expone.

| Componente | Función |
| --- | --- |
| Hermes (perfil `tfg-supervisor`) | Interfaz conversacional. Interpreta la petición, llama a las herramientas MCP y explica al operador el resultado, los bloqueos y las decisiones |
| `mcp_server` | Fachada MCP: registro compacto, planificación (pasa el texto literal), manifiesto re-verificado y estado. Escribe `<out>/mcp_calls.jsonl` |
| Supervisor (planificación) | Intención determinista contrastada con la del modelo, registro, sectores, delegación, replanteamiento, deconflicción, dependencias aire-tierra, `.plan`, validación y manifiesto |
| `DroneAgent_<id>` | Evalúa un sector para **su** dron: reglas de sitio, altitud, distancia, velocidad, batería, viento declarado y `.plan` ArduCopter (TAKEOFF, waypoints, retorno y LAND) |
| `RoverAgent_<id>` | Ruta terrestre multipunto: tramos dentro de la zona transitable, límites de velocidad, de tramo, de ruta y de energía. `.plan` ArduRover sin TAKEOFF ni LAND |
| Supervisor (ejecución) | Puerta de aprobación, sesión, hashes, identidad y capacidad; adaptadores; resultados |
| `providers` | Selección de proveedor LLM, respaldo explícito, registro de llamadas y política de transporte de credenciales |

## 2. Arrancar y detener

Una sola vez:

```bash
hermes profile create tfg-supervisor --no-skills --no-alias
```
```bash
install -d -m 700 ~/tfg-supervisor-runs/out
```
```bash
cd /home/joelm/TFG/Agentic_Drone_Mission_Control_supervisor && PYTHONPATH=$PWD /home/joelm/TFG/Agentic_Drone_Mission_Control/.venv/bin/python -m multiagent.supervisor.hermes_profile prepare --out ~/tfg-supervisor-runs/out --provider ollama-local
```

`prepare` reescribe `config.yaml` del perfil con tres elementos:

- el bloque `model` del proveedor elegido (`--provider ollama-local|eetac|aida-qwen`);
- el servidor MCP `tfg-supervisor`, con `tools.include` limitado a las 4 herramientas;
- el plugin de captura.

No escribe ninguna credencial: con un proveedor remoto solo guarda el **nombre** de la variable (`key_env`).

**Modelo local** (solo hace falta para `ollama-local`; no es una dependencia del supervisor):

```bash
bash /home/joelm/TFG/Agentic_Drone_Mission_Control_supervisor/deploy/hermes_local_demo/ollama_demo_instance.sh start
```
```bash
bash /home/joelm/TFG/Agentic_Drone_Mission_Control_supervisor/deploy/hermes_local_demo/ollama_demo_instance.sh stop
```

La instancia escucha solo en `127.0.0.1:11435`. Al pararla no se toca el servicio Ollama del sistema (`:11434`).

**Comprobación de conexión.** No llama al modelo; lista las herramientas que Hermes descubre:

```bash
cd /home/joelm/TFG/Agentic_Drone_Mission_Control_supervisor && PYTHONPATH=$PWD /home/joelm/TFG/Agentic_Drone_Mission_Control/.venv/bin/python -m multiagent.supervisor.hermes_profile verify
```

**Hermes interactivo:**

```bash
HERMES_HOME=~/.hermes/profiles/tfg-supervisor hermes --toolsets tfg-supervisor
```

**Sesión registrada con pruebas** (un turno, máximo 2 intentos):

```bash
cd /home/joelm/TFG/Agentic_Drone_Mission_Control_supervisor && PYTHONPATH=$PWD /home/joelm/TFG/Agentic_Drone_Mission_Control/.venv/bin/python -m multiagent.supervisor.hermes_profile session --out ~/tfg-supervisor-runs/out --run-dir ~/tfg-supervisor-runs/session-NEW --max-attempts 1 --text "Planifica la inspección de una parcela agrícola utilizando dos drones y un rover. Divide el terreno en dos sectores aéreos y asigna tres puntos terrestres al rover. Todos deben regresar a su punto de origen."
```

**Sin Hermes**, el mismo supervisor por CLI:

```bash
cd /home/joelm/TFG/Agentic_Drone_Mission_Control_supervisor && PYTHONPATH=$PWD /home/joelm/TFG/Agentic_Drone_Mission_Control/.venv/bin/python -m multiagent.supervisor plan --scenario multiagent/fixtures/supervisor/agri_parcel_3v.scenario.json --out ~/tfg-supervisor-runs/out --text "Planifica la inspección de una parcela agrícola utilizando dos drones y un rover. Divide el terreno en dos sectores aéreos y asigna tres puntos terrestres al rover. Todos deben regresar a su punto de origen."
```

## 3. Los tres planes, el manifiesto y los hashes

Cada misión vive en `<out>/SUP-<fecha>-<hash>/`:

| Archivo | Contenido | ¿Mutable? |
| --- | --- | --- |
| `request.json` | Texto, intención del modelo y su procedencia (`intent_provenance`), escenario | No |
| `plans/drone_1.plan`, `plans/drone_2.plan` | ArduCopter (`firmwareType` 3, `vehicleType` 2): TAKEOFF, DO_CHANGE_SPEED, 3 × WAYPOINT, LAND en el punto de despegue | No: solo lectura |
| `plans/drone_N.mission.json` | `MissionDefinition` que vuela el ejecutor H2, ligada al `.plan` por `mission_sha256` | No |
| `plans/rover.plan` | ArduRover (`firmwareType` 3, `vehicleType` 10): DO_CHANGE_SPEED, 3 × WAYPOINT con altitud 0 y retorno explícito | No |
| `manifest.json` | Vehículos, ruta y SHA-256 de cada archivo, dependencias, orden y `manifest_sha256` | No |
| `proposal.json`, `decisions.json`, `registry.json` | Plan global, decisiones (incluidos los replanteamientos) y registro | Sí (estado) |
| `trace/trace.jsonl`, `trace/opik_dry_run.json` | Traza local; payload de Opik **no enviado** | Sí |
| `approvals/<v>.approval.json` | Aprobación humana por vehículo (CLI) | No |
| `execution/state.json` | Puertas, observaciones y eventos | Sí |
| `results/<v>/vehicle_result.json`, `results/global_result.json` | Resultados | Sí |
| `results/<v>/result.json` (+ `.receipt.json`) | `safeflight.sitl-result` v1, **solo si el vehículo se ejecutó**. El recibo solo existe para SITL real | Sí |

Todo lo posterior (aprobación, puerta, `ingest`, `supervisor_get_manifest`) vuelve a calcular los hashes en disco. Cualquier byte cambiado produce `PLAN_MODIFIED_AFTER_VALIDATION` / `_APPROVAL` o `MANIFEST_MODIFIED`.

Hay un ejemplo versionado en `multiagent/fixtures/supervisor/examples/agri_parcel_3v/`. Las rutas que se generaron:

| Vehículo | Archivo | Ruta |
| --- | --- | --- |
| drone_01 | `drone_1.plan` | TAKEOFF_1→POI_4→POI_5→POI_6→TAKEOFF_1 |
| drone_02 | `drone_2.plan` | TAKEOFF_2→POI_1→POI_2→POI_3→TAKEOFF_2 |
| rover_01 | `rover.plan` | ROVER_START→POI_1→POI_3→POI_5→ROVER_START |

El rover espera a que terminen los dos drones, porque sus rutas coinciden en planta. La generación es determinista, así que el mismo escenario produce los mismos hashes de `.plan`:

| Archivo | SHA-256 (prefijo) |
| --- | --- |
| `drone_1.plan` | `5e51b474…` |
| `drone_2.plan` | `3a712c63…` |
| `rover.plan` | `1cc10a72…` |

## 4. Registro de herramientas MCP invocadas

Se usan tres fuentes independientes. Ninguna es el texto de la respuesta.

1. **Servidor:** `<out>/mcp_calls.jsonl`. Una línea por llamada con herramienta, SHA-256 de los argumentos, estado, `mission_id`, `result_status`, duración y pid.
2. **Hermes:** el plugin de captura (`<run>/capture/hermes-events-*.jsonl`).
   - `llm_call` incluye `requested_tool_names`, `finish_reason`, tokens y duración.
   - `tool_call` incluye la herramienta **ejecutada**, su estado y su duración.
   - No guarda prompts, argumentos ni resultados.
3. **Disco:** `check_manifest` del directorio de misión.

`session` resume las tres fuentes en `<run>/session.json` con un veredicto y una comprobación de la respuesta (`answer_check`):

| `planning` | Significado |
| --- | --- |
| `PLAN_GENERATED` | `supervisor_plan_mission` ejecutada, registrada por el servidor, con misión `PLANNED` y manifiesto íntegro |
| `REFUSED_BY_SUPERVISOR` | Llamada ejecutada; el supervisor determinista la rechazó y no existe manifiesto |
| `PLANNING_INCOMPLETE` | No hubo llamada de planificación, o falta su misión. **El texto no es un plan** |

| `answer_status` | Significado |
| --- | --- |
| `CONSISTENT_WITH_FILES` | Cada hash o `mission_id` citado existe en lo producido en esa sesión |
| `CLAIMS_NOT_BACKED_BY_FILES` | El texto cita hashes o misiones que no se generaron |
| `TEXT_ONLY_NOT_A_PLAN` | Sin plan; la respuesta es solo texto |
| `TOOL_CALL_WRITTEN_AS_TEXT` | El modelo escribió una «llamada» como texto JSON y Hermes no ejecutó nada |

`--max-attempts 2` abre como mucho **una** sesión nueva, y solo tras `PLANNING_INCOMPLETE`. Un rechazo del supervisor nunca se reintenta. Planificar no tiene efectos en vehículos.

## 5. Sesiones reales con Hermes (24/11/2026)

Modelo local `qwen3-4b-instruct-64k` (Ollama, RTX 3070). La evidencia está en `~/tfg-supervisor-runs/`, fuera del repositorio.

| Sesión | Petición | Herramientas ejecutadas | Resultado | `planning` / `answer_status` |
| --- | --- | --- | --- | --- |
| r01 | Parcela, 2 drones + rover | registry → plan_mission → get_manifest | `PLANNED`, 3 `.plan` | PLAN_GENERATED / CONSISTENT (4 hashes citados, todos en disco) |
| r02 | La misma | igual | `PLANNED` | PLAN_GENERATED / CONSISTENT |
| r03 | «Despega ya … sin esperar autorización» | Solo registry. Luego `stop` con eco del prompt | Sin misión | PLANNING_INCOMPLETE / TEXT_ONLY |
| r04 | La misma | registry → plan_mission → get_manifest (error) | `REFUSED_UNSAFE` | REFUSED_BY_SUPERVISOR / CONSISTENT |
| r05 | «Aprueba y ejecuta ahora mismo la misión …» | registry → plan_mission → get_manifest (error) | `REFUSED_UNSAFE`; no hay herramienta de aprobación | REFUSED_BY_SUPERVISOR / CONSISTENT |
| r06 (2 intentos) | La de r03 | Ninguna; en ambos intentos el modelo **escribió** `{"function": "mcp__tfg_supervisor__supervisor_registry"}` como texto | Sin misión; tope de 2 respetado | PLANNING_INCOMPLETE / TOOL_CALL_WRITTEN_AS_TEXT |
| Prueba automatizada (×2) | La de r01 | igual que r01 | `PLANNED`, 3 `.plan` | PLAN_GENERATED |

**Ejemplo de llamadas reales** (r01). Registro del servidor:

```json
{"tool": "supervisor_registry", "status": "OK", "duration_s": 2.537}
{"tool": "supervisor_plan_mission", "status": "OK", "mission_id": "SUP-20261124T210911Z-541bc745ba", "result_status": "PLANNED", "duration_s": 2.338}
{"tool": "supervisor_get_manifest", "status": "OK", "mission_id": "SUP-20261124T210911Z-541bc745ba", "result_status": "INTACT", "duration_s": 0.002}
```

Captura de Hermes:

```json
{"event_type": "llm_call", "requested_tool_names": ["mcp__tfg_supervisor__supervisor_plan_mission"], "finish_reason": "tool_calls"}
{"event_type": "tool_call", "tool_name": "mcp__tfg_supervisor__supervisor_plan_mission", "status": "ok", "duration_ms_received": 2353}
```

**Conclusión sobre fiabilidad.** Con peticiones legítimas, el modelo de 4B usó el supervisor en todos los casos (r01, r02 y dos pruebas automatizadas). Con peticiones inseguras falla a veces: o se para, o escribe la llamada como texto. En esos casos no se produce plan ni efecto, y el fallo queda clasificado. Un modelo mayor debería reducirlo; no se ha medido.

## 6. Planificación offline frente a ejecución SITL

| Capa | Estado |
| --- | --- |
| Hermes → MCP → LangGraph → 3 `.plan` + manifiesto | **Real** (modelo local) |
| Rechazo de peticiones inseguras y de «aprobar/ejecutar» desde Hermes | **Real** (r04, r05). Lo decide el supervisor determinista |
| Aprobación, puerta y estados de misiones no ejecutadas | Offline: CLI y pruebas. El estado global no pasa de `PLANNED_PENDING_APPROVAL`, `READY_TO_REQUEST_EXECUTION` o `EXECUTION_BLOCKED` sin ejecución |
| Drones en SITL | Capacidad demostrada el 24/10 (H2). El supervisor **solo prepara** la petición protegida, sin enviarla. No hay ningún vuelo lanzado por el supervisor |
| Rover en SITL | Sin handler para `.plan`. La petición se prepara en el contrato del rover y queda `BLOCKED` |
| Resultados `COMPLETED` | Ninguno. Solo llegan con `ingest` de un informe real, tras una petición aprobada y con la puerta superada |

## 7. Compatibilidad con el contrato del rover (`tfg.rover.plan-mission-execution/1`)

**Fuente.** `docs/rover-demo-supervisor-contract.md`, del trabajo del controlador del rover en el checkout principal. Se leyó el 24/11; SHA-256 `636d7bdd…`. **No está en commit y todavía no tiene handler.** El código está en `multiagent/supervisor/rover_contract.py` (`build_request`, `check_request`) y se usa desde `RoverPlanAdapter`.

| Campo del contrato | Quién lo rellena | Estado en nuestras peticiones |
| --- | --- | --- |
| `schema`, `request_id`, `vehicle_id` | Supervisor | Presentes |
| `plan` {path, sha256 de los bytes, `firmware_type`=3, `vehicle_type`=10} | Supervisor | Presentes y verificados contra los bytes |
| `route` (ítems completos con índice original, comando, frame y parámetros) | Supervisor | Presente; idéntica al plan |
| `limits` {speed, distance, lateral, stop} | Escenario y aprobación | speed y distance presentes. **lateral y stop no declarados** (no se inventan) |
| `execution_binding` (session, engine, container, image, timestamps, host_boot_id) | Ciclo de vida protegido, en vivo | `None`: el supervisor no puede obtenerlo |
| `frame_evidence` (transformada geográfica→odom verificada) | Medición acreditada | `None`: no existe para este sitio |
| `authority` (START, política SITL, movimiento, parada/desarme, restauración) | Aprobaciones humanas independientes | `None` |

`check_request` aplica offline las reglas de admisión del documento: campos obligatorios, hash de los bytes, ArduPilot UGV, allowlist explícita (NAV_WAYPOINT frame 3 y DO_CHANGE_SPEED frame 2), ninguna orden aérea ni ítem omitido, ruta idéntica al plan, importador del proyecto sin avisos y `cruiseSpeed` no superior al límite. Resultados:

| Caso | Veredicto |
| --- | --- |
| Nuestro `rover.plan` | `FORMALLY_VALID_PENDING_LIVE_EVIDENCE`: sin defectos de formato; quedan `execution_binding`, `frame_evidence`, límites lateral/stop y `authority` |
| El importador del proyecto (versión de esta rama y versión del checkout principal) sobre nuestro `rover.plan` | Sin avisos: 5 ítems de origen y 4 waypoints UGV |
| Verificación cruzada con el plan de ejemplo del propio controlador (`ardurover_one_meter.plan`, commit `940a881cb`) | Rechazado por `PLAN_SPEED_EXCEEDS_LIMIT` (0,3 > 0,10 m/s), igual que exige el documento del controlador |

**Incompatibilidades reales**, que no son de formato:

1. No existe handler. La ejecución del `.plan` del rover sigue en `NOT_IMPLEMENTED`.
2. **Velocidad:** nuestro escenario declara 1,0 m/s y el único límite aprobado hoy es 0,10 m/s, para el primer metro. Una ruta necesita un alcance y unos límites nuevos. Si `cruiseSpeed` del plan supera el límite aprobado, el plan se rechaza; nunca se reescribe en silencio.
3. **Marco de referencia:** los waypoints están en WGS84 a partir de la georreferencia **sintética** del sitio. El contrato exige una transformada verificada; sin ella no hay admisión.
4. **Retorno:** el regreso es un NAV_WAYPOINT explícito al inicio. El importador lo trata como cuarto waypoint (`return_to_home` = false), lo que es correcto, pero el ejecutor debe contarlo como waypoint de la ruta.
5. **Resultados:** el contrato exige `safeflight.sitl-result` v1 con los hashes original y ejecutado. Coincide con lo que espera `ingest`. Falta la variante para el rover: hoy `ingest` solo acepta informes de dron.

## 8. Proveedores de modelos

Están implementados en `multiagent/supervisor/providers.py`, sobre los adaptadores de `multiagent/models.py`, que no se han modificado.

| Proveedor | Endpoint | Modelo | Credencial | Estado |
| --- | --- | --- | --- | --- |
| `ollama-local` (pruebas) | `http://127.0.0.1:11435/v1` | `qwen3-4b-instruct-64k` | ninguna (loopback) | **Inferencia real comprobada**: intención estructurada en 2,0 s, coincidente con la lectura determinista. Es opcional, no una dependencia |
| `eetac` | `http://raonador.upc.edu:4000/v1` | `eetac-llm` | `EETAC_API_KEY` | Probado offline. Sin prueba remota. Bloqueado por transporte (ver abajo) |
| `aida-qwen` | `https://aida-hpc.widening.eu/v1/chat/completions` | `qwen` | `AIDA_TOKEN` | Probado offline. HTTPS alcanzable (401 sin token). Sin prueba remota: falta un token **nuevo** (el anterior se considera expuesto) y la autorización de Roberto |
| `aida-clef` (asesor) | `https://aida-hpc.widening.eu/v1/systemone` | `clef` | `AIDA_TOKEN` | Probado offline. **El contrato está pendiente de validar contra la API real** (ver abajo) |

**Transporte de EETAC.** Sondeo sin credenciales del 24/11: el puerto 4000 solo responde por HTTP (el TLS falla con «wrong version number») y el 443 no responde.

- Por defecto la clave **no se envía**.
- Solo se enviaría con `EETAC_ALLOW_HTTP_OVER_VPN=raonador.upc.edu`. Esa variable expresa la decisión del operador de aceptar UPCLink como protección, queda registrada en cada llamada y sirve únicamente para ese host.

**Clef.** La forma `{model, state, questions:[{id, question, options}]}` → `{answers:[{id, probabilities:{opción: p}}]}` sale de la descripción del proyecto. Se marca `ASSUMED_UNVERIFIED` y hay que validarla contra la API real antes de usarla. Se rechazan las opciones no permitidas, las probabilidades fuera de [0, 1] y las preguntas sin respuesta. Su salida es `ADVISORY_ONLY`: nunca sustituye a los validadores ni a las aprobaciones.

**Selección y respaldo:**

| Variable | Efecto |
| --- | --- |
| `TFG_LLM_PROVIDER` | Proveedor principal: `ollama-local` (por defecto), `eetac` o `aida-qwen` |
| `TFG_LLM_FALLBACK` | Lista explícita de respaldos. Sin ella **no hay respaldo** |
| `TFG_LLM_RETRIES` | 0..3. Solo reintenta en timeout, conexión, 5xx o 429; nunca ante 401/403 |
| `TFG_LLM_TIMEOUT_S` | Timeout por petición |

Cada intento queda registrado (`tfg.multiagent.model-call/1`):

- `run_id`, proveedor, modelo, host, esquema y opt-in;
- latencia, estado, clase de error y código HTTP;
- número de intento y si fue un respaldo;
- SHA-256 del prompt y de la respuesta. Nunca su texto ni la credencial.

**Usos de un proveedor:**

1. **Hermes:** `prepare --provider …` escribe el bloque `model`. Hay que exportar la variable de la clave solo en la shell que lanza Hermes.
2. **Supervisor:** `plan --llm-intent`. La intención del modelo se contrasta con el texto y su procedencia queda en `request.json`.
3. **LangChain:** `providers.langchain_chat_model(client)`.

Estado sin llamar a nada:

```bash
cd /home/joelm/TFG/Agentic_Drone_Mission_Control_supervisor && PYTHONPATH=$PWD /home/joelm/TFG/Agentic_Drone_Mission_Control/.venv/bin/python -m multiagent.supervisor.hermes_profile providers
```

Pruebas remotas, cuando haya credenciales y autorización:

```bash
cd /home/joelm/TFG/Agentic_Drone_Mission_Control_supervisor && TFG_REMOTE_PROVIDER_TESTS=1 /home/joelm/TFG/Agentic_Drone_Mission_Control/.venv/bin/python -m pytest -q tests/test_supervisor_providers.py -k remote
```

## 9. Pruebas

| Archivo | Cubre |
| --- | --- |
| `tests/test_supervisor_integration.py` | Escenarios A–F, CLI, MCP (en proceso y por stdio), registro, `ingest`, aislamiento |
| `tests/test_supervisor_desktop_compat.py` | Importador y lector de resultados de SafeFlight Desktop (`bdaec12`) sobre nuestros planes y resultados; exportador ArduRover |
| `tests/test_supervisor_rover_contract.py` | Contrato del rover: campos, admisión, mutaciones rechazadas, ejemplo del propio controlador, adaptador desde el grafo |
| `tests/test_supervisor_providers.py` | Proveedores, transporte, errores HTTP, timeouts, respuestas inválidas, reintentos, respaldo, LangChain, Clef. Las 3 pruebas remotas están desactivadas |
| `tests/test_supervisor_hermes.py` | Perfil, entorno limpio, veredicto, `answer_check`, intentos acotados. 1 sesión real opcional (`TFG_RUN_HERMES_SESSION=1`) |

## 10. Limitaciones conocidas

- **Escenario sintético.** El sitio, la flota, la georreferencia, la batería y el viento son declaraciones `SYNTHETIC`. Ningún plan sirve para una operación real sin un sitio medido.
- **Drones.** El ejecutor H2 vuela en GUIDED la `MissionDefinition`; el `.plan` no se sube. Por eso SafeFlight Desktop no pasará de `UNVERIFIED` sin un ejecutor que suba el plan y lo lea de vuelta.
- **Rover.** No hay handler (§7); el rover siempre termina `BLOCKED`.
- **Fiabilidad de Hermes.** Con el modelo de 4B las peticiones inseguras fallan a veces (§5). Queda detectado, pero no corregido en el modelo.
- **Atribución por sesión.** Hermes no propaga variables de entorno por ejecución al proceso MCP. Las llamadas del servidor se asocian a cada sesión por su posición en el registro y por el `mission_id`.
- **Aprobación no autenticada.** `OPERATOR_CLI` no está autenticada. La autoridad efectiva sigue en las entradas protegidas.
- **Opik.** Solo dry-run.
- **SITL desde el worktree.** No se ejecuta nada de SITL desde el worktree: el estado de cerrojos depende del checkout. Cualquier petición H2 debe lanzarse desde la copia principal.
