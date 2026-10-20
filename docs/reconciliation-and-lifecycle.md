# Cierre offline: diagnóstico, reconciliación y lifecycle (19/10/2026)

> Actualización posterior del 19/10: [SITL detenido y cierre administrativo](stopped-sitl-reconciliation.md). Las limitaciones de suelo visual de este cierre anterior describen la vía ACTIVE; no se exige telemetría ni imagen de un entorno terminado verificablemente. La aplicación real sigue pendiente.

Implementación y pruebas con dobles. **No se han ejecutado Docker, ROS, controles,
inspecciones de telemetría, reconciliaciones ni vuelos reales en este incremento.**
Los resultados operativos anteriores conservan su identidad e informes originales.

## Estado de partida y resultado esperado

La secuencia `c6eeb645-17d2-4081-9afb-cecfd23af393`, clave
`joel-secuencia-sitl-01`, sigue incompleta. Su hijo v1
`467f7ec6-b2a6-4b68-9d97-766d85732f8e` tiene PASSED; el hijo v2
`1b69dfc7-0707-4b68-a009-062610418fe4` tiene ERROR, retorno 124,
`executor_result=null`, `analysis=null`. Las reservas de secuencia/v2 se conservan
UNCONFIRMED. Las muestras del **18/10 a las 23:42 CEST** son históricas, no
telemetría de hoy ni autorización para liberar nada. El PASSED individual anterior
de v2 (`7162bce5-3635-4a76-bf02-6a5a22612aab`) tampoco repara este intento.

## Diagnóstico del executor

Las lecturas iniciales de origen global y geopose ahora están dentro del manejo
de errores, antes de GUIDED/ARM. Se devuelve FAILED estructurado con identidad,
observaciones disponibles y cadena de excepciones; el workflow conserva el bruto,
lo analiza y escribe el informe. Un origen leído no inventa una posición inicial
si falla la siguiente lectura. Sin intento de control no se ordena recuperación.

`operation_diagnostics` conserva las primeras 16 operaciones y las últimas 96,
con contador de omisiones. Registra vehículo lógico/interfaz, etapa, operación,
topic/servicio, UTC, duración monotónica de pared, timeouts configurados, retorno,
salida de transporte acotada y error. Los datos recibidos son observaciones, no
estimaciones añadidas. Los headers ROS dentro de la salida no se restan del reloj
de pared ni se convierten en edad absoluta de generación.

`control_attempts` distingue intento previo a la llamada de confirmación positiva;
`controls_not_attempted` identifica tipos de orden no intentados. Confirmar una
publicación/servicio no confirma llegada al waypoint. Si ARM falla o agota timeout,
puede haber armado: se mantiene la recuperación LAND existente. Un fallo previo
a cualquier control no justifica LAND ni demuestra por sí solo contacto con suelo.
El gate, hashes, geometría, tolerancias, AP_DDS, QoS del executor y plazos de vuelo
siguen iguales; no hay reenvíos de objetivos ni reintentos de vuelo.

Un proceso matado antes de devolver el resultado puede perder diagnóstico todavía
en memoria: el informe de intención persistido y la reserva continúan inciertos.
No se reconstruye retrospectivamente la lectura que falló el 18/10 ni la causa
del 124. El error nuevo explica futuros intentos, no modifica el ERROR histórico.

## Reconciliación en dos fases y consulta de auditoría

1. `inspect_execution_reconciliation(target_id)` recibe el UUID de un propietario
   retenido, no una ruta. Lee reservas, admisiones, snapshots/informes disponibles,
   hashes, vínculos y procesos. Intenta tomar sin espera el mutex global del executor
   y el registro común. Un ejecutor activo bloquea la inspección. Persiste sólo una
   auditoría separada; no cambia jobs, reservas ni modos.
2. `apply_execution_reconciliation` exige `inspection_id`, SHA-256 exacto, declaración
   de autorización de reconciliación y confirmaciones de suelo concretas. Repite
   lectura de registros/procesos y obtiene nueva telemetría bajo exclusión. Si algo
   cambió, bloquea y exige inspección nueva. No reanuda secuencias ni autoriza vuelos.
3. `get_execution_reconciliation(inspection_id)` recupera la auditoría tras recarga
   o respuesta perdida. No consulta telemetría ni aplica nada. La repetición de una
   aplicación con exactamente los mismos argumentos es idempotente; otra declaración
   o evidencia para la misma aplicación entra en conflicto. No inventar un ID nuevo
   ni regenerar declaraciones para recuperar una respuesta.

Los procesos se identifican por PID, `start_ticks` y `boot_id`; zombis se consideran
terminados, no aterrizados. Un propietario vivo, un PID reciclado, una identidad
ausente o un error al inspeccionarla impiden aplicar. El proceso de admisión de una
secuencia se registra aparte del coordinador que ejecuta; no se confunden sus roles.
En un executor síncrono o lifecycle cuyo propietario es el propio servidor MCP,
un PID todavía vivo bloquea esta primera versión aunque su llamada haya devuelto
error: no se mata automáticamente. Resolver su actividad/terminación es una acción
administrativa separada, conservando las reservas; recargar una conexión no demuestra
por sí solo que ese proceso terminó.

### Evidencia reciente y suelo: fuente realmente admitida

La inspección abre suscripciones ROS nuevas, best-effort/volatile **sólo en el
observador**, sin modificar publishers ni el executor. Recoge hasta 8 muestras por
stream durante 20 s, con timeout externo de 35 s. Se requieren al menos 3 muestras
de status y posición por interfaz, receipts y headers crecientes, último receipt
a no más de 5 s del fin de la ventana, `armed=false`, `flying=false`, sin failsafe
y posición estable. La estabilidad exigida es una política de reconciliación
(variación ≤0,000002° en lat/lon y ≤0,20 m en altura), no una tolerancia de vuelo.
La aplicación repite la ventana y comprueba que la posición no cambió respecto
a la inspección. Se observan **ambas interfaces**, también para una reserva individual,
porque el bloqueo y la posterior liberación afectan a la exclusión global.

Recepción reciente + headers que avanzan **no prueban edad absoluta de generación**:
hay clocks de simulación con orígenes y ritmos distintos. Se registra esa incertidumbre.
La evidencia caduca a los **120 s desde el inicio monotónico de la inspección**, en
el mismo boot. No se acepta tras reinicio del host, retroceso del plazo monotónico,
timeout de observación o caducidad durante la revalidación. Si la simulación avanza
demasiado despacio para reunir muestras, se bloquea; no se aumenta el timeout del
executor para ocultarlo.

La fuente independiente admitida en este incremento es **observación visual actual
del operador en Gazebo**, identificando `drone1` (drone_01/v1) y `drone2`
(drone_02/v2) y viendo cada modelo apoyado en la pista. La configuración del launch
usa esos nombres; si no se pueden identificar en la escena actual, no confirmar.
Por interfaz se exige `source=OPERATOR_VISUAL`, `on_ground=true`, `statement` no
vacío y `observed_at_utc` ISO 8601 con zona, posterior a la inspección. Obtener la
hora de pared, por ejemplo, con una lectura local:

```bash
date -u --iso-8601=seconds
```

Es una **declaración del operador transmitida por el agente**, no una imagen
autenticada ni un sensor de contacto. No se acepta como sustituto un informe viejo,
AMSL parecido al lanzamiento, una captura antigua o sólo `armed=false/flying=false`.
El esquema no puede garantizar que Hermes atribuya fielmente esa declaración.

**Si la GUI sigue negra y no existe otra vista actual del mismo servidor, esta
aplicación queda BLOQUEADA.** No se ha implementado un sensor independiente de
contacto en este entorno y no se inventa uno. Puede obtenerse la declaración cuando
la GUI existente vuelva a mostrar la escena sin parar/reiniciar el backend; si eso
no es posible, hace falta diseñar y revisar otra fuente independiente o una acción
administrativa de recuperación fuera de este procedimiento. No hay un desbloqueo
genérico ni un reinicio ordinario que resuelva circularmente este requisito. Elegir
headless no elimina la evidencia exigida para reconciliar un resultado incierto.
Este es un límite operativo explícito, no una reconciliación completada.

### Aplicación y durabilidad

Se revalidan los bytes de inspección, reservas, jobs, snapshots, informes y procesos
antes y después de la nueva ventana. La autorización queda vinculada al hash revisado.
Antes de retirar una reserva se persisten aplicación APPLYING y una barrera duradera
`reconciliation.json`. Las reservas originales se copian sin sobrescribir a
`vehicle_locks/history/<inspection_id>/`, con fsync. Se registra APPLIED y la
transición; ERROR/PASSED, jobs e informes históricos permanecen intactos. No existe
una transición retrospectiva a PASSED.

Si falta un resultado porque desapareció el worker, puede reconciliarse la restricción
con identidad de admisión verificable, procesos terminados, nueva evidencia suficiente
y confirmación visual explícita: su resultado histórico sigue desconocido y no se crea
un informe sustitutivo. Si falta el job/identidad/snapshot necesario, se bloquea sin
reconstruirlo. Una interrupción durante la retirada mantiene la barrera global; la
repetición devuelve el estado registrado, **no continúa una transacción incompleta**.
Este caso requiere revisión administrativa específica, no force-unlock.

## Exclusión efectiva de lifecycle y vuelos

| Entrada actualizada | Protección y límite |
| --- | --- |
| MCP/Python `start_simulation(gui=true/false)`, `stop_simulation`, `restart_simulation` | Registro común mantenido durante toda la operación. Cualquier reserva activa/incierta bloquea antes de llamar al backend. |
| Scripts `start_sim.sh`, `stop_sim.sh`, `restart_sim.sh` | Entran en el mismo módulo Python; no tienen una ventana propia de check/act. `--headless` selecciona GUI=false. |
| `*_sim_backend.sh` | Requieren propietario vivo e identidad verificable, descriptor heredado del registro e identidad de padre; una variable de entorno sola no basta. Logs separados de stdio MCP. |
| Executor público y primitivas ROS de control | Reserva global y mutex del executor; las primitivas exigen autoridad viva del vehículo. Lifecycle impide admisión nueva mientras actúa. |
| Preflight síncrono, worker asíncrono y secuencia | Reutilizan el executor protegido. La reserva exterior de secuencia permanece entre hijos; el segundo no hereda una autoridad reutilizable. |
| Demo antigua de dos drones | Sigue deshabilitada; no se reabre un camino paralelo. |

El orden de locks evita esperar a un worker manteniendo un bloqueo que necesite
para terminar: lifecycle rechaza si hay reserva; inspección/aplicación toman el
mutex del executor y después el registro, sin espera. Admisión rechaza rápidamente
si lifecycle posee el registro. El reinicio autorizado es **una transacción stop→start**,
sin hueco de admisión entre ambos. No lanzar dos herramientas en paralelo para imitarlo.

Lifecycle registra identidad, acción, GUI/headless, tiempos y log por operación en
`missions/generated/simulation_lifecycle/<id>/`. Un timeout, crash o resultado no
confirmado conserva su barrera; no se transforma en espacio libre al morir el PID.
La consulta histórica de un ensayo no es inventario de procesos ni garantiza idle.

Esta coordinación cubre las entradas **de este checkout actualizado**. No impide
órdenes manuales ROS/QGC, Docker directo, helpers internos del contenedor invocados
fuera del wrapper, otras copias del repositorio o versiones antiguas. No es una
frontera de seguridad contra clientes externos. Una parada de emergencia no se
implementa borrando reservas ni se incluye en la recuperación ordinaria.

## GUI negra: diagnóstico reproducible preparado

Las capturas del 18/10 están en
[el diagnóstico preservado](../simulation/ros2_gazebo/results/sequential_preflight_diagnostic_2026_10_18/c6eeb645-17d2-4081-9afb-cecfd23af393/README.md).
Separan `/tmp/tfg_demo.log`, launch/server, GUI `auto_default.log` y `ogre2.log`.
OGRE registró inicialización GL 4.1/Mesa/D3D12 Intel y errores de recursos
`package://ardupilot_gazebo`; las mallas consultadas existían. No se demuestra causa
de toda la pantalla negra ni vínculo causal con 124. No se importa el exit 139 de
otro arranque. Un proceso GUI vivo y READY no confirman imagen.

Para una próxima inspección autorizada: guardar sin sobrescribir logs del arranque
correcto, PID/start/argv del servidor y GUI, renderer declarado, DISPLAY/QT seleccionados,
rutas de recursos y existencia de las mallas citadas; no volcar variables privadas.
Comparar GUI/servidor/ROS por sus propios timestamps y scope, conservando desacuerdos.
Después de reconciliación y autorización separada, probar **una** recuperación GUI,
check de readiness y pregunta visual; o elegir explícitamente headless. El parámetro
GUI existente ahora llega desde MCP/script al launch: se eliminó su hardcode `true`
en el supervisor y se aclaró la descripción del argumento. No hay parche OGRE,
cambio de renderizador ni promesa de pantalla negra resuelta.

## Prueba nueva preparada, no admitida

[Plan versionable de repetición](../evaluation/operations/sequence_v1_v2_retry_2026_10_19.json):
`simulation_navigation_3waypoint.json` (drone_01/v1) y
`simulation_navigation_drone02.json` (drone_02/v2), en ese orden, con hashes y clave
**joel-secuencia-sitl-20261019-r02**, comprobada no utilizada al preparar el plan.
`authorization_statement=null`: no hay consentimiento anticipado ni job creado.
No reanudar la secuencia fallida ni reutilizar sus hijos. Si se pierde la respuesta
de admisión, consultar la misma clave/ID, sin un segundo inicio.

## Guía operativa corta para Joel (no ejecutada)

La **primera prueba** es una inspección, no una aplicación ni un vuelo:

```text
Inspecciona sólo en lectura la reconciliación de la secuencia c6eeb645-17d2-4081-9afb-cecfd23af393; conserva reservas e informes y devuelve identidad, evidencia reciente de ambas interfaces, motivos, inspection_id, hash y caducidad; no apliques reconciliación ni reinicies ni vueles.
```

Esperado: BLOCKED con motivos o AWAITING_EXPLICIT_GROUND_CONFIRMATION con ID/hash.
Detenerse ante proceso vivo/reciclado, registros ausentes/cambiados, stream insuficiente,
caducidad, cualquier armed/flying/failsafe o imposibilidad de identificar suelo.
No usar las observaciones del 18/10 para superar esta etapa.

**Sólo tras ver ambos modelos sobre la pista**, sustituir los tres marcadores por
datos realmente recibidos/observados, dentro del plazo; si caducó, inspeccionar de nuevo:

```text
Autorizo únicamente aplicar la reconciliación de la inspección <inspection_id> con SHA-256 <inspection_sha256>; a las <hora_ISO8601_con_zona> he visto personalmente drone1/v1 y drone2/v2 apoyados en la pista; registra ambas declaraciones visuales, conserva la historia y no reinicies ni ejecutes vuelos.
```

Esperado: APPLIED, auditoría/historial, sin modificación de informes ni permiso de
vuelo. Cualquier BLOCKED/APPLYING, contradicción o respuesta perdida obliga a detenerse
y consultar el mismo `inspection_id`; no borrar reservas o repetir con datos inventados.

```text
Consulta sólo la auditoría de reconciliación <inspection_id> y explica su aplicación y límites; no vuelvas a inspeccionar, aplicar, reiniciar ni volar.
```

**Recuperación GUI, autorización distinta**, sólo después de APPLIED y sin nuevas restricciones:

```text
Autorizo un único reinicio secuencial protegido del simulador con GUI para recuperar la imagen, sólo si no hay ejecución ni reserva activa o incierta; después comprueba readiness y pregúntame si veo mundo y drones, sin iniciar ensayos.
```

Esperado: una transacción, log, check real [Docker container, Gazebo server,
ArduPilot processes, ROS 2 vehicle interfaces, Pre-arm checks] y pregunta visual.
Si BLOCKED/UNCONFIRMED, NOT READY, imagen negra o sin ventana: parar, sin bucles.
Si el operador decide continuar sin visualización después de reconciliar, la opción
headless requiere su decisión explícita y no concede consentimiento de vuelo.

**Vuelo posterior, tercera autorización distinta**, únicamente con prerequisites satisfechos:

```text
Tras confirmar reconciliación aplicada, ausencia de restricciones y readiness actual, autorizo ensayar en SITL primero missions/examples/simulation_navigation_3waypoint.json en drone_01/v1 y después missions/examples/simulation_navigation_drone02.json en drone_02/v2, con clave nueva joel-secuencia-sitl-20261019-r02 y los hashes revisados; conserva el ID, no reanudes el intento anterior y no repitas vuelos automáticamente.
```

Esperado: admisión rápida y sólo luego validación; el segundo hijo sólo empieza
con primer informe íntegro PASSED, LAND/desarmado y reservas coherentes. Consultar
cada 15–30 s, también tras recarga/respuesta perdida:

```text
Consulta la misma secuencia por la clave joel-secuencia-sitl-20261019-r02 y resume cada hijo, hashes, fases, informes y restricciones; no inicies ni reanudes ni repitas nada.
```

Detenerse ante fallo/bloqueo, worker/coordinador desaparecido, ERROR, UNCONFIRMED,
hash distinto o falta de evidencia. Duración del workflow/executor no es tiempo
en vuelo. PASSED no demuestra velocidad comandada, carga del .plan, agricultura,
hardware, causa de WP3, simultaneidad o separación.

### Matriz pequeña de operación y repetibilidad

| Caso preparado | Evidencia a guardar | Criterio / parada |
| --- | --- | --- |
| Inspección inicial sin control | Auditoría, propietarios, muestras y stamps de ambos, identidad/edad | Ninguna reserva cambia; insuficiencia explica BLOCKED. |
| Aplicación explícita y consulta tras recarga | ID/hash, autorización, declaraciones visuales, aplicación/historial | Mismos argumentos no vuelven a aplicar; historia intacta. No ejecutar sin fuente de suelo. |
| Una recuperación GUI o elección headless | Log del arranque, readiness real y respuesta visual del operador | No repetir automáticamente; backend READY no es imagen confirmada. |
| Secuencia nominal r02 | Plan/hashes, hijos individuales, logs, fases y reservas | Dos PASSED verificados en orden y cierre coherente; de lo contrario detenerse. |
| Repetibilidad nominal, sólo tras revisión/autorización nuevas | Otra clave nueva elegida y guardada antes de admitir; mismas misiones/hashes | Comparar orden, checks y duraciones de workflow/executor. Sin inyección de fallos durante vuelo; no llamar tiempo en vuelo a esos intervalos. |

## Propuesta de commits (no ejecutada)

Revisar cada diff y agrupar con sus tests; estas son propuestas, sin staging:

1. `feat: orchestrate two persistent sequential SITL rehearsals` — incremento previo
   aún sin commit, como base de los siguientes.
2. `feat: persist executor operation diagnostics and initial read failures`
3. `fix: serialize simulator lifecycle with project flight admissions`
4. `feat: add reviewed execution reconciliation with durable audit history`
5. `test: cover lifecycle races and sequential preflight uncertainty`
6. `docs: record demo evidence and prepare authorized SITL recovery checks`

La secuencia persistente y otros cambios previos ya presentes deben conservarse y
revisarse como base/dependencias; no mezclarlos accidentalmente ni descartarlos.
Hay archivos compartidos (locks y servidor MCP): preparar hunks revisados y ejecutar
los tests de cada grupo cuando Joel decida materializar estos commits; no se ha
hecho staging parcial ni se afirma que esa separación ya esté verificada commit a commit.
No se da por completado ningún paso que requiera comprobación operativa.


### Revisión posterior del vínculo de identidad legacy (19/10)

La inspección ad234044 está caducada y no se aplica. La referencia de un error Docker
posterior al ensayo no prueba por sí sola su entorno original. Se exige revisión
administrativa explícita de continuidad y relojes para ese registro legacy, además
de metadatos, procesos/versiones y coherencia temporal bajo exclusión. Los flags de
boot del host no identifican el motor Docker. [Conclusión, contrato y procedimiento
viable](legacy-environment-binding-review.md). No se exige reconstruir un engine_id
histórico no guardado ni obtener telemetría de un entorno terminado.

### Caso excepcional con historia no verificable (19/10)

Joel no puede afirmar continuidad ni comparabilidad de relojes. No debe rellenar
la declaración anterior como true. La consulta histórica de eventos fue vacía con
código 0 según el operador; no prueba ausencia de actividad. Para **sólo** c6eeb645
y su reserva v2 fijadas se implementa un [retiro administrativo separado](administrative-retirement-c6eeb645.md),
con preparación en lectura, aceptación explícita de incertidumbre, versiones exactas,
revalidación bajo exclusión y transacción durable recuperable. No cambia ni relaja
la reconciliación técnica. Resultado ADMINISTRATIVELY_RETIRED_UNVERIFIED, sin afirmar
aterrizaje ni terminación del entorno original y conservando PASSED/ERROR/UNCONFIRMED.
Implementación verificada offline; ninguna aplicación o liberación real realizada.
