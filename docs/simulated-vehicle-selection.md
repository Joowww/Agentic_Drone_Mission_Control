# Selección de vehículo simulado y exclusión global

Incremento sobre `041d266`, 18/10/2026. Estado inicial: **implementado y comprobado
offline** con dobles de ROS/Docker/readiness/worker, todavía sin ensayo operativo
nuevo de v2. La sección final registra el primer ensayo posterior de este incremento
en drone_02/v2, contrastado offline; no demuestra coordinación simultánea o separación.

## Contrato de selección

`MissionDefinition.vehicle.vehicle_id` determina el destino mediante el resolver
común `tools/simulated_vehicle.py`:

| Vehículo lógico | Interfaz SITL | Namespace ROS2 |
| --- | --- | --- |
| `drone_01` | `v1` | `/ap/v1` |
| `drone_02` | `v2` | `/ap/v2` |

No hay búsqueda por prefijo, sustitución, inferencia de «drone 2» ni fallback para
IDs desconocidos. El executor Python conserva `vehicle` como argumento opcional:
si se omite (`None`) resuelve desde la misión; si se proporciona debe ser exactamente
la interfaz correspondiente. Por ejemplo, misión drone_02 con `vehicle="v1"` se
bloquea antes del gate, de reservar y de leer/mandar ROS. Las misiones existentes
con drone_01 siguen resolviendo v1. Los builders conservan sus defaults existentes;
este resolver no rellena ni modifica la misión original.

No se amplían las capacidades del executor: multirrotor, ArduPilot (o el valor
`unknown` que ya admitía), ruta waypoint, acción navigate y altura inicial positiva.
Se mantiene el gate determinista interno y el virtual preflight sigue siendo un
workflow independiente; no se convierte en requisito nuevo del gate. El gate añade
resolución de identidad antes de su validación/readiness, sin cambiar sus reglas de
seguridad. La compatibilidad de acciones/vehículo sigue comprobándose por el executor
y el workflow antes de comandos; un READY del gate no sustituye esa comprobación.

## Ejecución y ROS2

El executor resuelve antes de entrar en la exclusión y vuelve a comprobar la
correspondencia con la misión que carga después de su gate. Cada lectura y orden
usa esa interfaz: status, origen, geopose/filtered del lanzamiento, GUIDED, armado,
despegue, objetivos, regreso, LAND, waits y recuperación. El mapper conserva la
geometría relativa alrededor de la **posición real de lanzamiento del seleccionado**;
`gps_global_origin` no pasa a ser HOME de ejecución. El mapper es independiente del
namespace; no se copia ni se crea una ruta alternativa para v2.

Las primitivas ROS2 validan interfaces antes de interpolarlas en comandos. Las que
emiten órdenes requieren la autoridad de ejecución viva, del mismo vehículo y
proceso, dentro del ámbito del executor/worker; llamadas sueltas fuera de él se
rechazan. Las lecturas no adquieren ni liberan reservas. No se cambian frame 6,
type mask 3576, QoS best_effort, tolerancias, polling, timeout, envío de objetivos o
criterios de aterrizaje/desarmado. La recuperación LAND conserva el mismo destino.

## Una ejecución global, reservas por vehículo

Las reservas persistentes están en `missions/generated/vehicle_locks/v1.json` o
`v2.json`; cada registro nuevo declara interfaz y vehículo lógico. La admisión se
serializa y rechaza si **cualquiera** tiene reserva, aunque el solicitado sea otro.
No se permiten dos workers admitidos a la vez. Los dos vehículos comparten el mutex
OS existente `v1.execution.lock`: el nombre se conserva para compatibilidad, pero
su función es global, no específica de v1. `registry.lock` serializa los cambios.

El ámbito mantiene autoridad revocable, PID e identidad de proceso y verifica el
vehículo en las llamadas anidadas. No basta un Context copiado, un PID reciclado o
un run_id sin token para ejecutar. El alias Python `serialized_v1` se conserva,
pero ahora también protege v2; ya no existe la rama que lo dejaba fuera del lock.

Se conserva la reserva si el resultado es incierto, el worker desaparece, la
recuperación no confirma aterrizaje/desarmado o la identidad contradice la admisión.
Una reserva malformada o reservas conflictivas tampoco se interpretan como hueco
libre. Ni consulta, timeout, recarga, nueva clave ni fin del mutex borran reservas.
Sólo el propietario con evidencia positiva de no ejecución o aterrizaje confirmado
del seleccionado puede liberarla por la lógica normal existente. No se añade una
herramienta de desbloqueo ni se reanuda/repite un vuelo automáticamente.

La demo antigua `run_demo.sh` arma y despega ambos drones, por lo que su wrapper
`tools.guarded_demo` y verificación de hijo quedan **bloqueados antes de subprocess**.
No basta proteger aquel vuelo paralelo con una única reserva de v1. Se conserva el
script histórico, pero sus dos entradas al wrapper no permiten ejecutarlo bajo esta
política. No se implementa una nueva demo de dos vuelos ni se habilita concurrencia.

Es coordinación cooperativa entre las entradas del proyecto y primitivas públicas,
no una barrera de seguridad contra ROS/QGC externos, edición manual de registros o
código externo. No se promete separación espacial, evitación de colisiones o
supervivencia durable a reinicios del host. No actualizar código durante un worker
activo: la compatibilidad de ficheros no acredita despliegue en caliente entre
versiones. No se ha ejecutado esa situación operativamente.

## MCP, admisión y evidencia

Se mantienen nombres y argumentos de las herramientas MCP: el vehículo se obtiene
del contenido, sin un segundo selector que pudiera contradecirlo. En particular,
execute_approved_mission ya no fija v1 en su wrapper. Continúa con progress=False;
la variante síncrona puede superar el timeout y éste no cancela la ejecución.
Start/get conservan claves recuperables, stdio separado y logs por ensayo.

La admisión comprueba identidad/modelo para reservar el destino correcto; no evalúa
todavía seguridad/readiness/aceptación. Un input inválido/ID desconocido devuelve
ERROR sin worker o reserva; ACCEPTED no significa PASSED. La clave sigue ligada a
los bytes de la primera admisión: mismo contenido devuelve EXISTING; otro contenido,
incluso cambiar sólo el dron, REQUEST_CONFLICT con el ID y selección originales.
Perder la respuesta exige consultar esa clave o run_id, sin otro start.

Jobs nuevos usan `schema_version=2`; informes nuevos `schema_version="1.1"`.
Admisión, consultas summary/detail e informe exponen:

```json
{"vehicle_selection": {"vehicle_id": "drone_02", "simulated_vehicle": "v2"}}
```

El informe conserva además mission_identity con ambos campos y el resultado bruto
incluye vehicle_id lógico y vehicle como interfaz. El análisis estricto nuevo exige
que coincidan con MissionDefinition, además de los once criterios existentes. Se
verifica binding de admisión frente a input/SHA-256, informe frente a snapshot y
resultado, e identidad del worker. Una contradicción detectada es ERROR de consulta
sin efectos o impide aceptar/liberar el ensayo; no se inventa un aterrizaje.
Un error de integridad de consulta no es un nuevo resultado de vuelo.

`vehicle_restriction` corresponde al vehículo del ensayo consultado;
`global_flight_restriction` muestra el bloqueo global actual, que puede pertenecer
al otro dron. Son observaciones de reserva, no readiness o consentimiento actual.
Las consultas conservan el informe bruto; summary conserva estos campos y los
mismos errores de integridad. Las reservas actuales no reescriben resultados pasados.

Los informes históricos 1.0 se leen con su interfaz registrada v1. No se añaden
campos a sus archivos ni se recalculan sus hashes; si no guardaban vehículo lógico,
se mantiene desconocido, sin rellenarlo con drone_01. La respuesta marca
`vehicle_selection_basis=LEGACY_RECORDED_V1`; el análisis de fuentes históricas
conserva sus criterios v1, y no reinterpreta una misión antigua como ejecutada en v2.
Las consultas nuevas usan MISSION_SNAPSHOT como base de selección, sin autenticar
la historia ni eliminar todos los TOCTOU. Se mantienen copias, hashes, QGC, validación,
consentimiento y semántica del preflight; PASSED no autoriza otra ejecución o hardware.

## Preparación operativa posterior

Hay un JSON nuevo revisable: `missions/examples/simulation_navigation_drone02.json`,
derivado del ejemplo de tres waypoints con vehículo lógico explícito drone_02.
Sus valores son de escenario SITL; no telemetría ni decisiones personales atribuidas.
No se ensayó ni exportó durante la implementación offline; el ensayo posterior del
operador se documenta abajo. Los ejemplos existentes no
cambian. El skill de dominio 1.1.0 sólo actualiza el alcance factual de selección y
exclusión; no acredita fidelidad del agente ni mejora conversacional medida. Las
evaluaciones anteriores 1.0.x se conservan como historia con sus versiones.

Después de revisar el cambio, recargar MCP y precargar el skill actualizado en una
sesión nueva si se usa. Primero validar y comprobar readiness sin arrancar ni volar:

```text
Comprueba si missions/examples/simulation_navigation_drone02.json está preparada para ejecución simulada; informa del vehículo lógico, interfaz y controles de readiness realmente realizados, sin arrancar simulación ni ejecutar un vuelo.
```

Sólo cuando el operador haya preparado y comprobado la simulación y revisado el
snapshot, se puede solicitar un único ensayo:

```text
Solicito un único ensayo virtual asíncrono de missions/examples/simulation_navigation_drone02.json con clave joel-drone02-preflight-01; autorizo armado, despegue, recorrido y aterrizaje exclusivamente de drone_02 en v2 simulado, no arranques ni reinicies la simulación ni ejecutes otro vehículo, conserva el run_id y consulta ese mismo ensayo.
```

La clave de ejemplo debe usarse sólo para esa solicitud. Si ya existe, consultar y
reconciliar; no inventar otra para repetir una respuesta perdida. Consulta posterior:

```text
Consulta el ensayo con clave joel-drone02-preflight-01 y explica la identidad lógica e interfaz simulada, fase, resultado y reservas del vehículo y global; sólo consulta, sin iniciar ni repetir ninguna ejecución.
```

Las comprobaciones de exclusión entre v1/v2 están probadas con dobles, no con vuelos
simultáneos. Readiness sigue usando los cinco controles existentes del stack y
comprueba ambos drones; no se inventa un chequeo aislado por namespace. La operación
v2, AP_DDS y su seguimiento real en Gazebo quedaban pendientes al cerrar la
implementación offline; el resultado operativo posterior se registra a continuación.

## Comprobaciones registradas

- Grupo de selección, ejecución, preflight, reservas, ROS y MCP: **163 passed in 4.20s**.
- Suite completa: **388 passed in 11.70s**.
- Los 42 casos nuevos son contratos offline de código, no evidencia de un vuelo v2.
- Ejemplo nuevo validado sin exportar: FEASIBLE/APPROVED, sin errores.

El inventario completo de archivos y comprobaciones de conservación/diff queda en
[`simulated_vehicle_selection_2026_10_18.json`](../documentation/verification/simulated_vehicle_selection_2026_10_18.json).

## 18/10/2026 — Primer ensayo operativo de este incremento en drone_02/v2

El operador ejecutó el ensayo asíncrono
`7162bce5-3635-4a76-bf02-6a5a22612aab`, clave `joel-drone02-preflight-01`.
Esta revisión **no lo ejecuta ni consulta por MCP**: contrasta archivos ya guardados
y la transcripción adjunta. La clave ya está usada; sirve para recuperar este mismo
ensayo, no para autorizar otro vuelo. Se preserva la verificación offline inicial
como historia, sin convertir sus tests en evidencia operativa.

Archivo de evidencias: [simulated_vehicle_v2_2026_10_18](../simulation/ros2_gazebo/results/simulated_vehicle_v2_2026_10_18/README.md).
Contiene ocho copias exactas: mission.json, input.json, job.json, report.json,
worker.log, índice de request_key, ejemplo fuente y transcripción completa, más
manifiesto SHA-256 y comprobaciones derivadas. No se modifica ningún original ni
archivo de resultados anterior, incluidas las 37 copias del archivo conversacional.

### Hechos persistidos y comprobados offline

- Snapshot, input y ejemplo fuente: mismos 1717 bytes, SHA-256
  `ce94effedb4c977b0db3c64e41d4a2b86bba9a78c494cfeda4305d069d54bebb`.
  Coincide con input_sha256, expected_sha256 y mission_sha256; el índice de clave
  apunta al mismo run_id/hash. source_artifact=null: es un ejemplo JSON autónomo,
  sin vínculo a una finalización de borrador.
- job schema 2: FINISHED, phase=analyze, selección drone_02/v2, identidad de worker
  con PID/start_ticks/boot_id. Report schema 1.1 y executor coinciden en selección,
  misión y hash. No se comprueba ahora la vida del proceso ni el código desplegado
  exacto del worker histórico. El log contiene dos líneas: admisión reclamada y fin
  PASSED; no es una captura independiente de comandos/telemetría.
- Executor: success=true, COMPLETED, 14 eventos; GUIDED, ARM, despegue a 5 m,
  WP1→WP2→WP3, regreso a SIMULATION_HOME, LAND y LANDED. Final:
  landed=true, armed=false, flying=false; no error ni recuperación registrados.
  Regreso por navegación más LAND, no activación del modo RTL.
- Errores horizontales WP1/WP2/WP3: 0.396771/0.227774/0.480681 m; errores
  verticales: 0/0/0.010010 m. Regreso: 0 m horizontal/vertical. Dentro de las
  tolerancias existentes 1.0/0.75 m; error de despegue 0.230042 m.
- El análisis estricto actual reproduce **exactamente los once checks true**, sin
  motivos; validación determinista sin exportación reproduce FEASIBLE/APPROVED.
  Readiness guardada: Docker container, Gazebo server, ArduPilot processes,
  ROS 2 vehicle interfaces y Pre-arm checks, con ambas interfaces/armables en su
  salida. Es evidencia histórica, no disponibilidad actual ni verificación visual.

### Duraciones de operación, no tiempo en vuelo

| Intervalo UTC del 18/10/2026 | Duración |
| --- | ---: |
| report.started_at 17:34:26.794699 → finished_at 17:39:26.637756 | 299.843057 s |
| execution_started_at 17:34:40.657446 → execution_finished_at 17:39:26.629183 | 285.971737 s |
| job.created_at → job.finished_at 17:39:26.640580 | 299.845881 s |

El primer intervalo incluye la admisión previa al workflow; el executor incluye
su gate y esperas, además de órdenes. Ninguno equivale a tiempo en vuelo: los eventos
no tienen timestamps individuales. Este ensayo queda por debajo de 300 s en esos
intervalos; no elimina el límite de timeout de herramientas síncronas.

### Reservas, conversación y límites

La política revisada serializa el vuelo mediante reserva global y mutex común,
con destino v2. La transcripción muestra un inicio y dos consultas del mismo ensayo;
Hermes comunica reserva vehicle/global EXECUTING durante el recorrido y ambas null
en la consulta final. **Son datos comunicados por el resumen de esa consulta**, sin
respuesta estructurada bruta ni auditoría de liberación en los cinco archivos del
ensayo. FINISHED/PASSED y el log son coherentes con el fin normal, pero no se usan
para reconstruir por sí solos el estado de las reservas ni su disponibilidad actual.
La exclusión cruzada y el rechazo concurrente se prueban offline; este ensayo único
no aporta una prueba operativa de contención entre ambos drones.

Se ve la petición explícita de reinicio único stop→start→readiness, la pregunta
visual posterior y la confirmación del operador de que ve mundo/drones antes de
autorizar v2. No se ve comprobación de reservas antes de ese reinicio ni pregunta
visual tras el primer arranque. No se declara PASS global del skill o fidelidad de
argumentos no capturados. El cliente anuncia 21 herramientas y después 0 al actualizar
el agente; la verificación del registro del repositorio conserva 17. Sin captura
estructurada de catálogo/configuración, esa discrepancia queda sin causa demostrada.

No hay observación independiente de posición/status de v1 durante el vuelo: **no
se demuestra que permaneciera inmóvil**. Tampoco coordinación simultánea, separación,
prevención de colisiones, hardware, agricultura, seguimiento de velocidad, carga del
.plan o resolución causal de WP3/pantalla negra. objective_type=precision_agriculture
es metadato heredado del ejemplo: todas las acciones ejecutadas son navigate.
qgc_plan_path=null describe esta validación, no ausencia de exportaciones anteriores.
PASSED no autoriza hardware ni otra ejecución. Persisten los límites de hash/TOCTOU,
control cooperativo frente a clientes externos y falta de interlock atómico entre
lifecycle y vuelo; no se acredita resistencia a reinicio del host.

Cierre de esta revisión: **388 passed in 10.11s**, suite completa offline, sin tests
nuevos ni cambios funcionales/skill; originales y evidencias previas conservados.
git diff --check versionado limpio. La comprobación individual de nuevos archivos
avisa de whitespace en la transcripción bruta por CRLF/espacios: se preserva exacta,
sin normalizar evidencia; los demás archivos nuevos no presentan avisos.

### Cierre posterior comunicado por el operador

El operador amplía la evidencia del mismo ensayo: stop_simulation devolvió SUCCESS
y ausencia de procesos atribuibles al proyecto restantes; **después** se consultó
check_simulation_ready, que devolvió NOT READY. Docker container pasó (contenedor
aún activo), Gazebo server falló y **ArduPilot processes, ROS 2 vehicle interfaces
y Pre-arm checks no se ejecutaron**. No se clasifican como fallidos ni aprobados.
La parada de los procesos del proyecto no implica detener el contenedor Docker.
Ese NOT READY posterior no altera el PASSED ni la readiness histórica del ensayo.

Se conserva la declaración en el [anexo de cierre](../simulation/ros2_gazebo/results/simulated_vehicle_v2_2026_10_18/closure_operator_followup/verification.json),
con texto del mensaje y manifiesto/hashes propios, sin reescribir las ocho copias
o el manifiesto anteriores. La ampliación recibida resume los resultados; no incluye
salidas MCP brutas, argumentos completos ni timestamps de las operaciones. Se
registra como evidencia aportada por el operador, no como chequeo actual realizado
en esta revisión. No acredita por sí sola liberación de reservas, inmovilidad de v1
ni causa de una pantalla negra. No se inicia ninguna operación para comprobarla.


## 19/10/2026 — Exclusión lifecycle/flight y reconciliación offline

La selección drone_01→v1/drone_02→v2 no cambia. Start/stop/restart actualizados
comparten registro y mutex global con el executor: ni la ausencia accidental de
un fichero de reserva permite interrumpir un executor cuyo mutex sigue tomado.
La reserva exterior de secuencia también excluye lifecycle entre hijos.

Se añaden diagnóstico de operaciones, inspección/aplicación de reconciliación y
auditoría consultable, conservando informes e identidad de cada vehículo.
La fuente de suelo admitida es observación visual ACTUAL del operador de drone1
y drone2 apoyados en la pista, separada de AP armed/flying. Sin imagen u otra
vista actual esta versión no puede aplicar reconciliación; no inventa sensor.
[Procedimiento, ámbito de exclusión y límites](reconciliation-and-lifecycle.md).
No hay nuevo ensayo operativo ni demostración de separación/simultaneidad.
