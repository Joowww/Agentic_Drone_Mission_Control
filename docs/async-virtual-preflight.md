# Seguimiento asíncrono del virtual preflight

El ensayo `d4519cab-ebd1-4359-b547-44be38294a6a` continuó después de los 300 s de
espera MCP y guardó `FAILED` por WP3, con recuperación LAND confirmada. Para
separar esa espera de la ejecución se añaden dos operaciones MCP:

- `start_virtual_preflight(mission_path, request_key)` admite un único ensayo,
  persiste su identidad y la copia de entrada, reserva `v1`, lanza un worker
  independiente y devuelve `run_id`, hash y rutas sin esperar al workflow/vuelo.
- `get_virtual_preflight(run_id=...)` o `get_virtual_preflight(request_key=...)`
  consulta exactamente un identificador. Es de sólo lectura: no crea directorios,
  cambia reservas, lanza workers ni reanuda/repite vuelos.

Ambas herramientas se descubren al reconectar MCP. **El inicio requiere una
solicitud explícita de ensayo**: su worker puede armar, despegar y mover sólo el
vehículo simulado `v1` y utiliza el aterrizaje/recuperación existentes. No inicia
ni reinicia la simulación. Obtener un ID no significa haber aprobado validación.

## Identidad, persistencia e idempotencia

Hermes debe elegir y recordar `request_key` antes de solicitar el inicio. Admite
1–96 caracteres: primer carácter alfanumérico y después letras ASCII, dígitos,
punto, guion o guion bajo. El índice usa SHA-256 de la clave como nombre de archivo.
El directorio del ensayo es un UUID canónico:

```text
missions/generated/preflights/requests/<hash_clave>.json
missions/generated/preflights/<run_id>/job.json
missions/generated/preflights/<run_id>/input.json
missions/generated/preflights/<run_id>/mission.json
missions/generated/preflights/<run_id>/report.json
missions/generated/preflights/<run_id>/worker.log
```

`input.json` conserva los bytes leídos durante la admisión, con límite de 5 MB.
El workflow existente vuelve a copiarlos a `mission.json`, conserva su SHA-256
y exige que coincida con el hash admitido antes de validar/volar. Se mantienen
los controles de integridad previos y posteriores al executor. Esto no elimina
las limitaciones TOCTOU ya documentadas.

La clave queda asociada permanentemente al primer ensayo, incluso si ya terminó.
Una repetición accidental con la misma clave devuelve `EXISTING` y el mismo ID,
sin spawn. Si el contenido aportado ha cambiado devuelve `REQUEST_CONFLICT`,
también sin spawn. No se admite otro ensayo silenciosamente. Para una nueva
solicitud explícita del operador hace falta otra clave. Perder la respuesta no
justifica repetir start: recuperar el ID mediante la consulta por clave.

La admisión y reclamación del worker se serializan con un lock de archivo. El
worker sólo acepta una admisión no reclamada, con su identidad de proceso y un
token de lanzamiento cuyo hash queda en `job.json`. Ejecutar su módulo sólo con
un `run_id` no permite iniciar/reanudar el ensayo. No se instala supervisor que
reinicie workers ni se reanuda trabajo en una recarga de MCP.

El proceso se crea con sesión separada, stdin `/dev/null`, stdout/stderr en
`worker.log` y cierre de descriptores heredados; no comparte stdio MCP. Una
petición completada o el cierre habitual del servidor/conexión no controla la
vida del worker. Un reinicio del host, una política externa que mate procesos
o la pérdida del disco sí pueden interrumpirlo: no se promete ejecución durable
frente a esos fallos. La identidad usa PID, ticks de creación de `/proc` y boot ID,
no sólo un PID que pueda reciclarse.

## Estados separados

| Campo | Valores y significado |
| --- | --- |
| `admission_status` | `ACCEPTED`: solicitud persistida; `EXISTING`: misma clave; `REQUEST_CONFLICT`: clave ligada a otro contenido; `VEHICLE_BUSY`: no admitida por exclusión; `ERROR`: error de admisión/lectura; `LEGACY`: informe anterior sin job. |
| `job_state` | `ADMITTED`: registro previo al spawn; `STARTING`: worker lanzado; `RUNNING`: reclamó el ensayo; `FINISHED`: existe informe final; `INTERRUPTED`: worker registrado ya no coincide/está vivo y no hay final; `UNCONFIRMED`: identidad o resultado no confirmados; `REJECTED`/`NOT_FOUND`/`ERROR`: solicitud no admitida, no encontrada o error de consulta. |
| `result_status` | Sólo `PASSED`, `FAILED`, `BLOCKED` o `ERROR` cuando hay informe final. En admisión y durante el trabajo es `null`. Su semántica de aceptación no cambia. |
| `phase` | Nodo actual o última fase persistida; no es una lectura de telemetría en tiempo real. |

El worker publica progreso antes de los nodos del mismo LangGraph. Durante
el vuelo la fase es `execute`; los eventos y muestras se actualizan al devolver
el executor, no como streaming durante cada waypoint. La consulta incluye informe
provisional/final disponible, identidad del worker, errores del worker, tiempos,
rutas y la restricción actual de `v1`. Un `job_state=ERROR` de consulta no es un
`result_status=ERROR` del ensayo.

Un informe final válido se puede leer aunque el worker haya salido antes de
actualizar `job.json`. Eso no hace que la consulta libere una reserva pendiente.
Si no hay final y el worker desaparece, `INTERRUPTED`/`UNCONFIRMED` no significa
aterrizado, fallido con recuperación, ni ensayo seguro para repetir. La consulta
no escribe un resultado sintético ni modifica el informe original.

## Exclusión de v1 y fallos no confirmados

`tools/vehicle_execution_lock.py` combina un mutex de ejecución `flock` entre
procesos y una reserva persistente en:

```text
missions/generated/vehicle_locks/v1.json
```

La admisión asíncrona reserva `v1` incluso antes de validar. Comparte la exclusión
con el executor síncrono, el preflight síncrono a través de ese executor y
`scripts/run_demo.sh` mediante `tools/guarded_demo.py`. Dos claves concurrentes
no pueden admitir dos workers sobre `v1`. Las llamadas anidadas del worker al
executor reutilizan el ámbito que ya posee el mutex; no copian el gate ni sus
órdenes de vuelo. El bloqueo no hace del preflight un requisito del gate.

Si muere el propietario, el kernel libera el mutex, pero **la reserva persistente
permanece**. Ni una consulta, timeout, reconexión, nueva clave, parada de simulación
ni el paso del tiempo la elimina automáticamente. Una excepción, resultado sin
confirmación de aterrizaje, recuperación incompleta o fallo de persistencia dejan
la reserva en estado no confirmado y bloquean otras entradas del proyecto.

La liberación normal requiere un workflow terminado y persistido que no haya
llamado al executor, o un resultado del executor con rechazo previo a comandos,
o evidencia explícita de aterrizado/desarmado/no volando. Una recuperación LAND
confirmada puede liberar la exclusión, pero el resultado del ensayo sigue siendo
`FAILED`. Un resultado `COMPLETED` sin evidencia de aterrizaje tampoco basta para
liberarla. El demo interactivo espera confirmación de aterrizaje de `v1`, además
de la aceptación de LAND que ya mostraba.

No se añade una herramienta MCP para desbloquear una reserva no confirmada.
Hace falta reconciliar con el operador el estado real del vehículo y de los
procesos antes de una intervención de mantenimiento. No borrar el archivo sólo
porque el PID desapareció. Esta exclusión coordina los puntos de ejecución de
este checkout; no es una barrera de seguridad contra órdenes ROS manuales,
QGroundControl, otros checkouts, manipulación de archivos o comandos externos.
No añade bloqueo independiente de `v2` ni convierte start/stop de infraestructura
en una orden de aterrizaje. `PASSED` no autoriza hardware ni una nueva ejecución.

## Informes anteriores y rutas

La consulta acepta UUIDs canónicos, rechaza rutas/IDs no válidos y comprueba que
los artefactos queden bajo el almacenamiento configurado, incluso con symlinks.
Nunca usa una ruta suministrada por el cliente o leída de `report_path` para abrir
un informe. También busca UUIDs en las evidencias fijas del repositorio bajo
`simulation/ros2_gazebo/results/virtual_preflight_*/*_report.json`.

Se puede consultar `d4519cab-ebd1-4359-b547-44be38294a6a` y obtener su `FAILED`
y su recuperación LAND sin iniciar ningún proceso. Los informes históricos no
adquieren retroactivamente un job, clave o identidad de worker. La ruta devuelta
para el informe es la copia encontrada, no una ruta antigua incrustada en JSON.

## Herramientas síncronas existentes

`run_virtual_preflight` y `execute_approved_mission` siguen disponibles y siguen
siendo **síncronas**: mantienen la llamada durante el workflow o vuelo. No
reciben automáticamente una clave de solicitud ni se convierten en un job.
Sus límites de espera dependen del cliente MCP; un timeout, incluido el observado
de 300 s, no cancela ni confirma el fin del backend. El executor ahora participa
en la exclusión común, pero eso no proporciona seguimiento por clave de una
llamada síncrona cuya respuesta se perdió. El preflight síncrono conserva su
informe como antes; la ejecución directa sólo devuelve su resultado.

Para ensayos nuevos se recomienda start + get. La variante asíncrona evita
mantener abierta la llamada de vuelo; no cambia el timeout configurado de MCP,
los waits de 180 s, las tolerancias, AP_DDS, QoS, recuperación, diagnóstico de
waypoint, exportación QGC ni análisis de aceptación.

## Uso desde Hermes

Elegir y comunicar una clave antes de empezar; conservarla junto al `run_id`.
Tras el inicio, consultar el mismo ensayo cada 15–30 s, sin un bucle de consultas
rápidas. No emitir otro inicio por respuesta perdida o reconexión. Ejemplos,
cada prompt en un turno y una sola línea:

```text
Solicito un único virtual preflight asíncrono de missions/examples/simulation_navigation_3waypoint.json con clave joel-preflight-async-01; autorizo el armado, despegue, recorrido y aterrizaje del v1 simulado para este ensayo, no arranques ni reinicies la simulación y conserva run_id y rutas para consultar el mismo ensayo después.
```

```text
Consulta únicamente el virtual preflight asociado a la clave joel-preflight-async-01; recupera su run_id si hace falta y muestra estado de admisión, ejecución, fase e informe disponible, sin iniciar ni repetir vuelos.
```

```text
Consulta únicamente el informe histórico del ensayo d4519cab-ebd1-4359-b547-44be38294a6a y explica su resultado y recuperación, sin iniciar procesos ni vuelos.
```

## Pruebas y pendientes

Las pruebas offline usan Popen, readiness y executor dobles, y recorren también
el grafo real. Comprueban admisión sin vuelo ni espera al workflow, desconexión de
stdio, identidad persistida, sólo lectura, resultados finales, carreras entre
claves, idempotencia, recarga, PID reciclado, worker desaparecido, reserva
conservada, exclusión con herramientas síncronas/demo e informes históricos.

Pendiente probar operativamente el worker separado y la recarga MCP; no se han
hecho vuelos ni llamadas operativas en esta implementación. No hay cancelación,
reanudación automática, streaming de telemetría ni interfaz para reconciliar
reservas no confirmadas. El almacenamiento es local y no dispone de retención o
limpieza automática de jobs/claves/logs.


## 2026-10-17 — Verificación operativa del ensayo asíncrono y revisión

### Evidencia guardada comprobada offline

Ensayo `f5f55084-5af6-4e58-ab1a-ce30a13832b3`, asociado por el operador a la clave
`joel-preflight-async-01`. Archivos conservados:

- `simulation/ros2_gazebo/results/virtual_preflight_2026_10_17/passed_async_mission.json`
- `simulation/ros2_gazebo/results/virtual_preflight_2026_10_17/passed_async_report.json`

El SHA-256 calculado de los bytes de la misión coincide con `mission_sha256` y
`expected_sha256` del informe:

```text
2366d5a2c38f092e7ce5b01220f49463001dbf8164db6706899ff26beb9d56d1
```

El informe registra `PASSED`, persistencia confirmada, validación `FEASIBLE` /
`APPROVED`, executor `COMPLETED`, tres waypoints completados, regreso solicitado
y alcanzado y `LANDED` con `landed=true`, `armed=false`, `flying=false`.
Todos los checks del análisis son verdaderos y la lista de motivos está vacía.

| Evento alcanzado | Error horizontal (m) | Error vertical (m) |
| --- | ---: | ---: |
| WP1 | 0.451579 | 0.030029 |
| WP2 | 0.227774 | 0.000000 |
| WP3 | 0.480681 | 0.039978 |
| Regreso al lanzamiento | 0.000000 | 0.000000 |

Son valores del executor, no medidas independientes de precisión física.
El despegue registra error vertical 0.070007 m. El informe abarca desde
20:20:20.241103 hasta 20:24:17.155436 UTC del 17/10/2026: 236.914333 s.
La sección de ejecución abarca 227.265168 s. No son mediciones de latencia de la
llamada de admisión. Este ensayo concreto no excedió 300 s.

### Verificaciones operativas según la transcripción del operador

El operador comunica admisión rápida y recepción de `run_id`/rutas; consultas
del mismo ensayo antes y después de `/reload-mcp`, sin repetir el inicio; y
consulta final con resultado persistido y restricción de `v1` liberada.
Después de finalizar, la parada devolvió `remaining=[]`; una comprobación
posterior, ejecutada secuencialmente, devolvió `NOT READY`.

Estos pasos de interacción, recarga, liberación de reserva y parada se registran
según la transcripción del operador. Los dos JSON conservados respaldan el
contenido, vuelo y resultado del ensayo, pero no contienen por sí solos una
transcripción de todas las llamadas ni el estado de la reserva tras la consulta.
No se volvieron a ejecutar operaciones Docker, simulación, vuelos ni MCP durante
esta revisión. La indicación anterior de prueba operativa pendiente queda
actualizada para este escenario de worker y `/reload-mcp`.

La prueba no demuestra resistencia a reinicios del host, pérdida de disco o
muerte del worker. Tampoco demuestra haber resuelto la causa del fallo anterior
de WP3 en `d4519cab-ebd1-4359-b547-44be38294a6a`. Se mantienen los límites de
hardware, velocidad, acciones agrícolas, RTL y asociación por hash ya descritos.

### Revisión offline de concurrencia y persistencia

La revisión incluyó el diff seguido y los archivos nuevos del incremento.
Se reprodujeron con dobles y corrigieron estos defectos:

- Un `Context` copiado podía conservar la identidad del propietario después de
  salir del ámbito y saltarse la exclusión; dos contextos del mismo propietario
  también podían invocar executors simultáneamente. La autoridad ahora se revoca
  al cerrar el ámbito, revalida propietario/proceso y admite sólo una llamada
  simultánea. El mutex de ejecución no se libera mientras una llamada prestada
  siga activa. No se añade una cola de vuelos ni un reintento.
- Un índice de solicitud `{}` se trataba como ausencia de clave y podía admitir
  otro ensayo cuando la reserva previa ya había terminado. Registros vacíos o
  JSON que no sean objetos ahora producen `ERROR`, sin spawn ni liberación.
  Se distingue un archivo ausente de un registro persistente inválido; los
  originales dañados no se sobrescriben al consultar.
- La admisión leía todo el archivo antes de aplicar el límite de 5 MB y podía
  bloquearse al abrir una FIFO bajo el lock de admisión. Ahora exige archivo
  regular, comprueba el tamaño y acota la lectura; rechaza FIFOs y dispositivos.

Las correcciones mantienen gate, tolerancias, recuperación, análisis y evidencias.
Los tests nuevos son offline: contextos e hilos con comandos dobles, registros
corruptos, FIFO sin lectura bloqueante, límite de entrada y comprobación del
informe PASSED mediante el analizador existente, sin reproducir su vuelo.

Siguen pendientes cancelación, reconciliación explícita de reservas no
confirmadas, limpieza de almacenamiento y evaluación ante fallos del host.
La exclusión sigue siendo cooperativa entre entradas de este checkout; no
controla órdenes ROS externas ni resuelve todas las carreras TOCTOU de archivos.


### Resultado de verificación de esta revisión

- Suite completa offline: 198 passed in 6.44s.
- Los tests de regresión reprodujeron primero los defectos de contexto copiado,
  registros dañados y lectura de FIFO; pasan después de las correcciones.
- Sintaxis Bash de los tres scripts: correcta. git diff --check: sin errores.
- Se verificaron por SHA-256 los 17 artefactos de evidencia, sin modificaciones.
- El contenido anterior de este documento se conserva íntegro como prefijo.
- Sin Docker real, simulación, vuelos, llamadas MCP operativas, commit ni push.


## 2026-10-17 — Vínculos con planificación y revisiones

El nuevo flujo de planificación, geometría, propuestas y consulta se documenta en
[Planificación, revisiones y explicación de estado](mission-lifecycle-demo.md).
No sustituye start/get ni cambia su admisión, gate, exclusión o recuperación.

En una admisión nueva desde un snapshot finalizado/revisado con sidecar verificable,
`job.json` guarda `source_artifact` (tipo, identificador, hash de misión y de registro).
El worker lo conserva en el mismo estado/informe LangGraph. Un JSON ordinario sin
sidecar sigue siendo una entrada válida y su vínculo con un borrador es desconocido.
La consulta global sólo asocia por estos vínculos e integridad, nunca por nombre,
fecha o igualdad aparente de rutas. No añade un índice global ni migra evidencias.

Se puede obtener una propuesta persistente de un informe final y construir una
revisión con cambios explícitos aceptados, declaración de condiciones físicas y
validación/exportación existentes. Eso no ensaya la revisión ni hereda el PASSED,
readiness o consentimiento de su fuente; tampoco libera restricciones de `v1`.
La consulta de estado no revalida, exporta, comprueba la simulación ni ejecuta.

Hermes debe conservar además `draft_id`/versión, `finalization_id`, `proposal_id`/hash
y `revision_id` cuando existan. Finalizar y construir una revisión ya validan y
exportan: no repetir esos pasos para explicar el resultado. La autorización
explícita sigue siendo necesaria para cada ensayo del snapshot revisado; guardar
o validar lo solicitado no necesita una aprobación adicional.

El resolvedor compartido ahora rechaza un UUID histórico presente en varios
informes, en lugar de escoger uno por orden de archivos. Los vínculos nuevos se
han verificado offline con dobles de infraestructura/worker; no tienen un nuevo
vuelo operativo. Las evidencias, parada y límites del ensayo f5f55084 documentados
arriba permanecen sin cambios, incluida la causa desconocida del fallo WP3 anterior.


## 18/10/2026 — Resumen y detalle de consultas

El wrapper MCP 0.3.0 de `get_virtual_preflight` devuelve `view=summary` por defecto;
`view=detail` conserva la respuesta completa anterior con el resultado bruto.
El backend Python, admisión, worker, snapshot, análisis y exclusión no cambian.
El resumen conserva estado de admisión/ejecución/resultado, restricción de v1,
análisis/motivos, recuperación y readiness registrada; no resume un worker
interrumpido como aterrizado ni omite errores para reducir bytes. Detalles de
compatibilidad y mediciones en [la guía](mission-lifecycle-demo.md).

SITL requiere solicitud del ensayo simulado, no autorización de hardware real.
PASSED no demuestra la causa del fallo WP3 anterior. Un qgc_plan_path nulo sólo
indica que esa operación no registró una exportación, sin demostrar ausencia de
planes anteriores. Los nombres de controles se toman de la salida real; los que
siguen a un fallo temprano no se dan por ejecutados. La reducción de payload se
comprobó offline; el efecto sobre compacciones de Hermes está pendiente.

## 18/10/2026 — Ensayo geométrico persistido y revisión del árbol

El ensayo `4bb6a20e-3aff-48ce-8b6f-e66e92a0e6a4`, clave
`joel-rectangulo-preflight-01`, conserva PASSED, cinco puntos, regreso y
aterrizaje/desarmado. Se verificaron offline sus bytes, vínculo explícito con la
finalización 8be78baa del borrador 1f84f808 y análisis recalculado; no se repitió
el ensayo. Workflow 480,344587 s y executor 471,332987 s: supera 300 s, sin que
estos intervalos equivalgan a tiempo en vuelo. FINISHED consta en job.json;
la consulta final con vehicle_restriction=null procede del operador y no se ha
encontrado una respuesta de consulta guardada que pruebe la liberación histórica.
Inventario, errores finales, hashes y límites en el
[archivo de evidencias](../simulation/ros2_gazebo/results/hermes_conversational_2026_10_18/README.md).

Corrección del estado de la documentación anterior: la revisión actual detecta
que el wrapper sigue en 0.2.0 y no conecta las vistas ni acepta `view`. Por tanto,
la sección de resumen/detalle conserva un contrato previsto, pendiente de conectar
y verificar, no una capacidad MCP comprobada en este árbol. Se detallan los
[defectos reproducidos y evaluación actualizada](mission-lifecycle-demo.md#18102026--evaluación-actualizada-tras-el-ensayo-geométrico).
El funcionamiento asíncrono start/get existente y sus límites no se modifican.

## 18/10/2026 — Corrección offline posterior del wrapper de consulta

El defecto de vistas descrito arriba queda corregido en el registro MCP 0.3.0:
get_virtual_preflight expone `view` summary/detail, default summary; detail entrega
el resultado completo anterior y el backend Python mantiene su contrato. La
consulta conserva fase, resultado, incertidumbre, restricción de v1, razones,
readiness guardada y análisis; no inicia ni repite un ensayo. ERROR/NOT_FOUND
se devuelven completos. `error_evidence` del resumen usa una lista `{path, value}`
con ubicación en la respuesta completa y valores sin truncar.

Se verifican esquemas, despacho real en proceso y salidas del SDK, incluyendo
interrupción sin aterrizaje inferido y restricciones conservadas. Las pruebas son
offline, posteriores al PASSED del rectángulo 4bb6a20e, que no se repitió y cuyas
evidencias permanecen intactas. Su consulta mide 11.658 bytes de detalle y 6.414 de
resumen como JSON UTF-8 indentado, no tráfico MCP total, tokens o compacciones.
[Contrato, tests y otras mediciones](mission-lifecycle-demo.md#18102026--corrección-posterior-offline-de-las-vistas-registradas).
Falta probar conversacionalmente estos wrappers después de recargar Hermes;
no se acredita aquí resistencia a reinicios del host ni se cambia start/worker.
