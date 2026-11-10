# R1: coordinador y ejecutor conectados, con la interfaz física sustituida — 25/10/2026

**Resultado.** El coordinador y el ejecutor de Codex se han probado juntos.
- **Reales:** el coordinador, su adaptador, `admit_ground_trial`, `run_ground_worker`,
  `Ros2RoverAdapter`, `RoverControlCore.navigate`, `lookup_ground_trial` y `query_ground_trial`.
- **Sintética:** solo la sesión física, un modelo cinemático que integra las órdenes de velocidad que
  calcula el controlador.

**Ningún rover se ha movido, no hay ejecución real y el escenario no está completo.**

**Los dos relojes de la sesión sintética:**
- sellos de cabecera en tiempo simulado;
- recepción en el reloj monotónico de la misma `Clock`.

**Origen sintético acreditado en todos los registros:**
- entradas etiquetadas `TEST_DOUBLE`;
- el ejecutor declara `origin: SYNTHETIC_TEST_DOUBLE`;
- la parte aérea es la vista guardada de H2 reidentificada como escenario de demostración, sin
  ninguna clave ni registro de H2.

**Reproducción:**

```bash
.venv/bin/python -m pytest -q tests/test_agri_ground_joint.py tests/test_agri_ground_coordinator.py
AGRI_JOINT_EVIDENCE_DIR=<directorio-nuevo> .venv/bin/python -m pytest -q tests/test_agri_ground_joint.py -k joint_deterministic_report
```

**Archivos** (rutas temporales de pytest sustituidas por `<pytest-tmp>` tras la exportación):
- [`joint_report.md`](joint_report.md): informe determinista;
- [`r1_record.json`](r1_record.json): registro del coordinador;
- [`executor_report.json`](executor_report.json): informe del worker.

## Recorrido demostrado

**Cadena:** vista aérea → candidato (destino, transformación `VERIFIED` declarada como doble,
límites) → autorización vinculada al candidato y a la sesión → `ROVER_NAVIGATE_V1` con
`coordination_context` → admisión real (reserva v3 en un `LOCK_ROOT` temporal) → worker real →
`navigate` → parada → informe → `lookup` y `query` reales → aceptación.

**Resultado en el caso nominal:**
- **Contrato evaluado sobre las muestras del propio worker:** `VERIFIED` (error mínimo 0,048 m con
  0,05 m de tolerancia, permanencia 5,05 s en reloj de simulación, parada confirmada, sin pérdidas).
- **Estado de R1:** `UNCERTAIN`, porque el trabajo del ejecutor queda `UNCONFIRMED`. HOLD no es
  desarme, y el ejecutor solo da `FINISHED` y libera la reserva con una parada **desarmada**.
- **Escenario:** `AERIAL_COMPLETED_GROUND_UNCERTAIN`, completo: **no**.

## Matriz de compatibilidad (código actual)

> **Superada (25/10/2026, 20:20).** El ejecutor ya ofrece `start_ground_trial` y la finalización `DISARM_AFTER_OBSERVED_STOP_V1`. La matriz, los estados y los bloqueos vigentes están en [la evidencia de cierre](../agri_r1_joint_closure_2026_10_25/README.md). Esta sección se conserva como registro.

| Elemento | Ejecutor actual (Codex) | Coordinador | Estado |
| --- | --- | --- | --- |
| Hechos del intento | `executor_facts()` (política, `ROVER_NAVIGATE_V1`) | `RoverGroundExecutorAdapter.facts()` lo consume; sin él, `UNKNOWN` | (a) existe y probado |
| Petición | `ROVER_NAVIGATE_V1 {kind, limits, goal}`; `NavigationGoal` exige `IDENTITY_SAME_ACCREDITED_FRAME`, yaw y su tolerancia, `command_hz`, `max_samples` y `progress_rad` | `navigation_request(candidate)` la construye solo desde el candidato; sin `execution_limits` no se construye | (a) probado: el ejecutor guarda exactamente esa petición |
| Admisión | `admit_ground_trial(…, coordination_context={candidate, authorization})`; política primero y validación después | El adaptador llama tal cual y conserva los rechazos | (a) probado (con política real: `BLOCKED`) |
| Autorización del ejecutor | `{mission_sha256, request_fingerprint, statement}` | La construye el adaptador con `fingerprint` de Codex | (b) en el adaptador |
| Candidato y autorización del coordinador | `_coordination` comprueba `candidate_sha256 = fingerprint(candidate)`, la misión, el destino y el marco | El mismo objeto y la misma función en los dos lados | (a) probado |
| Sesión | La toma de la autorización (UUID). El worker exige que coincida con la del transporte (`probe().session_id`) y la guarda en el trabajo y en el resultado | La autorización la incluye; la aceptación la compara | (a) probado |
| Marco | El worker exige `pose_reference_sha256` del adaptador igual al `frame_sha256` del candidato; la etiqueta del resultado sigue siendo `DECLARED_…` | La acepta solo si la transformación del candidato es `VERIFIED` (dato de entrada) **y** el ejecutor ligó ese mismo digest | (a) vínculo probado; (d) falta verificar la transformación real |
| Consulta por clave | `lookup_ground_trial(key)` valida índice, instantánea y alcance | Recupera una respuesta perdida sin volver a admitir | (a) probado |
| Consulta por trabajo | `query_ground_trial(run_id)`: estado, sesión, `coordination_binding`, informe verificado por hash | Fuente única del resultado aceptado | (a) probado |
| Resultado | `report.r1_ground_result` con las muestras, los dos relojes, los GID, las órdenes y la parada | `evaluate_ground_result` sin traducciones; las muestras se recalculan desde `report.r1.samples` para comprobar que no se pierde ni cambia ninguna | (a) probado |
| `FINISHED` y liberación | Solo con parada desarmada; HOLD armado da `UNCONFIRMED` y la reserva se mantiene | `UNCERTAIN`; el coordinador nunca libera | (c)/(d): **decisión pendiente** sobre el desarme en R1 o un cierre explícito |
| Lanzamiento del worker | `run_ground_worker(run_id, launch_token, …)` sin entrada propia; el token se entrega solo al admitir | El adaptador lo guarda solo en memoria | (c) **ausente**: si se pierde la respuesta, el trabajo admitido no puede arrancar y queda `EXECUTOR_UNCONFIRMED` |
| Estado «admitido sin worker» | `query` lo informa como `UNCONFIRMED`, igual que un worker perdido | Lo trata como `EXECUTOR_UNCONFIRMED`, que sigue vivo y se vuelve a consultar | (c) falta distinguir los dos casos en el ejecutor |

## Contrato de identificadores y hashes

**Función común en los dos lados:** `planning.artifact_store.fingerprint`, es decir, JSON con
`sort_keys`, `ensure_ascii=False`, `allow_nan=False`, UTF-8 y SHA-256. Registro `tfg.agri-r1-task/2`.

| Identificador | Autoridad | Objeto hasheado | Dónde se fija | Cómo llega al resultado | Cómo se contrasta |
| --- | --- | --- | --- | --- | --- |
| `candidate_sha256` | Coordinador | El candidato (dict) | Registro R1, `coordination.json` y `coordination_binding` del trabajo | `binding.candidate_sha256` | Igualdad, con la misma función y el mismo objeto |
| `authorization_sha256` | Coordinador (declaración, **no autenticación**) | La autorización del coordinador | Registro R1 y `coordination_binding` | `binding.authorization_sha256` | Igualdad. **No** se compara con `job.authorization_sha256`, que corresponde a la autorización del ejecutor, otro objeto |
| Autorización del ejecutor | Ejecutor | `{mission_sha256, request_fingerprint, statement}` | `job.authorization` / `authorization_sha256` | — | Igualdad del objeto con el que envió el coordinador |
| `mission_sha256` | Ejecutor (bytes del archivo) | `sha256(bytes)` | `job.mission_sha256` | `binding.mission_sha256` | Igualdad con la misión del candidato |
| Petición | Ejecutor | `request.json` (bytes) y `fingerprint(request)` | `job.request_sha256` y alcance | — | Igualdad del objeto guardado con el enviado |
| `session_id` | Ciclo de vida, declarada en la autorización | UUID | `job.session_id`; el worker la compara con la del transporte | `binding.session_id` | Igualdad con la autorización |
| `frame_sha256` | Coordinador (transformación) y adaptador (`pose_reference_sha256`) | Digest declarado de la transformación | `coordination_binding.frame_sha256` | — | Igualdad con la transformación del candidato |
| `ground_run_id` | Ejecutor (UUID del trabajo) | — | Índice por clave y trabajo | `binding.ground_run_id` | Igualdad con el `run_id` recuperado |
| Alcance de la admisión | Ejecutor | `fingerprint([misión, fingerprint(request), autorización del ejecutor, coordination_context])` | Índice y `job.admission_scope_sha256` | — | Igualdad con el que calcula el coordinador |

**Límite de confianza.** Estas comprobaciones prueban que el resultado aceptado es exactamente el
que guardan los registros locales del ejecutor para esta clave, este trabajo, esta petición, esta
autorización y esta sesión, y que no se ha mezclado con otras muestras ni reutilizado de otra
ejecución. **No autentican** quién produjo esos registros: alguien con permiso para reescribirlos
todos de forma coherente puede falsificarlos. Ni un `origin: EXECUTED` ni una bandera del adaptador
bastan nunca. Un origen `SYNTHETIC_TEST_DOUBLE` o unas entradas dobles limitan el resultado a
`VERIFIED_SYNTHETIC`.

## Pruebas del recorrido conjunto (`tests/test_agri_ground_joint.py`, 17)

**Casos que llegan a la meta:**
- objetivo alcanzado con permanencia;
- inicio dentro del radio;
- salida del radio durante la permanencia (la permanencia se reinicia).

**Fallos que nunca dan éxito y conservan la reserva del ejecutor:**
- falta de progreso;
- pérdida de observación;
- cambio de marco;
- cambio de fuente (GID).

**Casos `UNCERTAIN`:**
- cancelación;
- objetivo alcanzado con parada incierta (HOLD rechazado).

**Recuperación:**
- respuesta de admisión perdida: se recupera con `lookup_ground_trial` y no se vuelve a admitir;
- consulta antes de que arranque el worker: no congela el registro;
- reinicio del coordinador: cada `track` lo hace un adaptador nuevo.

**Solicitudes y autorización:**
- solicitud duplicada: `EXISTING`;
- distinto candidato o sesión: `REQUEST_CONFLICT`, sin segunda llamada al ejecutor;
- autorización de un destino anterior: rechazada.

**Procedencia y escenario:**
- resultado mezclado con los registros reales: `REJECTED_RESULT`;
- H2 real: `BLOCKED` y nunca completo.

**Coordinador aislado (`tests/test_agri_ground_coordinator.py`):**
- dos **procesos** con la misma clave: una sola llamada de admisión;
- interrupción antes de la intención, tras la intención, durante la consulta y antes de persistir la
  aceptación.

**Pruebas de Codex reutilizadas sin cambios:** `test_rover_navigation.py` y
`test_rover_ground_executor.py`.

## Bloqueos reales para el primer R1 en SITL

1. **Decisión de producto (Joel y el tutor, con Codex):** cómo termina R1. Hoy el ejecutor solo
   cierra (`FINISHED`) y libera con una parada desarmada. Hay que decidir si R1 incluye un desarme
   controlado o si existe un cierre protegido para HOLD.
2. **Codex:** una entrada de lanzamiento del worker, o un modo de recuperar o cancelar un trabajo
   admitido cuyo token se perdió. También distinguir en `query` «admitido sin worker» de «worker
   perdido».
3. **Medición y decisión:** la transformación real (la comprobación de tres vehículos), que dé
   `frame_transform` `VERIFIED` y el `pose_reference_sha256` del adaptador.
4. **Medición:** una captura `/3` en reposo para fijar la tolerancia, los umbrales y los límites del
   controlador. Puede ser headless solo si Codex la soporta y la ejecuta con su procedimiento
   protegido.
5. **Codex:** cadena de identidad del rover y transporte real con `probe().session_id`.
6. **Joel:** aprobar los parámetros de R1, la misión `rover_01` y una autorización explícita; después,
   un único ensayo autorizado.
