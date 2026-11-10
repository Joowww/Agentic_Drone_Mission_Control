# Primer movimiento del rover en SITL: BLOCKED antes de arrancar el simulador (03/11/2026)

| Clase | Estado |
| --- | --- |
| `SIMULATED_REAL_EXECUTION` | **NOT_EXECUTED.** No se arrancó el contenedor ni el simulador. No se envió ningún comando al rover |
| `OFFLINE_TEST` | Ejecutado: [`verify_blockers.py`](verify_blockers.py) y las pruebas offline del rover, el coordinador R1 y el lifecycle |
| Resultado | **BLOCKED** |

- **Rama:** `feature/rover-sitl-first-motion`, creada desde `ddbb7c33e`.
- **Sin cambios de código.** No se modificó ninguna reserva, lease, sesión, disposición histórica ni evidencia anterior.
- **Agente:** Claude, por encargo de Joel.

## Por qué no hubo ensayo

Los bloqueos están en este orden. Cada uno impide el siguiente paso aunque se resolviera el anterior.

### 1. Infraestructura: ningún perfil puede arrancar ([`diagnostic-precheck.stdout`](diagnostic-precheck.stdout))

- **Contenedor:** `tfg-ardupilot-gazebo` (`0274e4fd…`) está `exited`, con código 255, desde el `2026-11-01T11:53:00Z` ([`container-inspect.json`](container-inspect.json)).
- **Sesión diagnóstica:** la `891dab60…` está `CLOSED`. Mientras exista, `run_lifecycle` exige `diagnostic_precheck_locked` en **todo** `start`/`restart`, sea `two_drones` o `two_drones_rover`.
- **Resultado del precheck de hoy:**
  - `BLOCKED`, con el motivo «Current environment is UNKNOWN; no complete recovery inventory»;
  - auditoría `DISPOSED_DIAGNOSTICALLY_INCOMPLETE`.
- **Boot del host:** el actual es `fd538729…` ([`host.json`](host.json)). El scope sucesor que Codex preparó el 01/11 exige `11f52aeb…`, así que ya no es aplicable (ver `evaluation/operations/rover_successor_authorized_2026_11_01/`).

### 2. Política operativa ([`verify_blockers.stdout`](verify_blockers.stdout))

`OPERATIONAL_ROVER_ENABLED = False`:
- `admit_ground_trial` devuelve `BLOCKED / OPERATIONAL_ROVER_POLICY_DISABLED` antes de escribir nada (`run_root_unchanged: true`);
- `start_ground_trial` devuelve `BLOCKED`.

### 3. Acreditación de la fuente de movimiento

- **Sin productor de `MotionBinding`:** no hay ningún productor fuera de `tests/` (`motion_binding_producers_outside_tests: []`).
- **Guarda heredada:** la guarda sin `source_contract` bloquea siempre («Identity worker record absent»).
- **Camino con `source_contract`:** depende del receptor supervisado XRCE. Según los informes de Codex (no verificado aquí), sus capturas del 30 y 31/10 quedaron incompletas.

### 4. No existe camino de armado para una navegación

- **Lo que exige `ROVER_NAVIGATE_V1`:** el rover ya armado, en `GUIDED`, con `external_control` y sin failsafe.
- **Por qué nada lo arma:**
  - `_request` rechaza la clave `preparation` en una navegación;
  - `_assert_preparation_scope` solo permite GUIDED + ARM dentro de un trabajo `ROVER_PULSE_V1` en `PREPARING`.

### 5. Lugar de ejecución

- **El problema:** el ejecutor y las reservas viven en el host, pero `rclpy` no está en `.venv` (`host_rclpy_available: false`). `NativeRos2Session` lo importa.
- **Lo que existe:** el repositorio está montado en el contenedor en `/workspace/tfg`.
- **Lo que no se ha comprobado aquí:** si la identidad de proceso de las reservas es coherente entre los espacios de PID del host y del contenedor.

## Comprobaciones de comunicación (A–G)

**Todas `NOT_EXECUTED`,** porque el simulador no está en marcha:
- presencia del rover en Gazebo;
- `/ap/v3`;
- topics y servicios;
- pose;
- comandos;
- modo;
- condiciones.

No hay posición inicial ni final observada, distancia recorrida ni estado de parada. Los datos de días anteriores (por ejemplo, la captura en reposo `4ac58516` del 26/10) son históricos y no acreditan el estado de hoy.

## Pruebas offline ([`offline-tests.stdout`](offline-tests.stdout))

- **Alcance:** 67 archivos `tests/test_rover_*`, coordinador R1 y lifecycle.
- **Resultado:** **5 failed, 3227 passed, 4 skipped**; retorno 1.
- **Los 5 fallos son de `tests/test_rover_passive_odometry_fields.py`:**
  - recorre con `rglob` todos los `journal.jsonl` presentes en disco bajo `simulation/ros2_gazebo/results/`;
  - aquí encuentra 9 en lugar de 5;
  - los 4 que fallan (`sdk-evidence/18/journal.jsonl` y `reader/journal.jsonl`) están **ignorados por Git** y solo existen en este checkout.
- **Interpretación:** el fallo depende del contenido local del disco, no de un cambio de código. Ninguno se ha corregido.

## Correcciones mínimas para continuar

Se indica quién actúa en cada paso.

1. **ACCIÓN NECESARIA DE JOEL:** autorizar el arranque del mismo contenedor y una revisión sucesora de la disposición para el boot nuevo. Es el protocolo de Codex; Codex ejecuta el dry-run y la aplicación con el scope exacto que se apruebe. Así se satisface el precheck.
2. **Decisión de Joel con Codex:** añadir a `ROVER_NAVIGATE_V1` una preparación GUIDED + ARM tras observar el rover parado, con su propia aserción de alcance, como la de `ROVER_PULSE_V1`. Hoy la navegación no puede empezar nunca.
3. **Productor real de `MotionBinding`:** a partir de evidencia actual (identidad del entorno, configuración del bridge, GID del publicador de `/rover1/odometry` y marco `odom`), o validación del receptor XRCE.
4. **Worker en un entorno con `rclpy`:** con reservas coherentes.
5. **Habilitar la política:** solo entonces, con un cambio revisado de `OPERATIONAL_ROVER_ENABLED` y nunca de forma global ni por variable de entorno, ejecutar un único ensayo `two_drones_rover`.

[`SHA256SUMS`](SHA256SUMS) cubre todos los archivos salvo este README.
