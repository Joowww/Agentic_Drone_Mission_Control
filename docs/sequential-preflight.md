# Dos ensayos persistentes en orden, una sola ejecución global

Incremento del 18/10/2026 sobre `7b6e349`. Implementación y tests **offline**;
no se ejecutan ensayos ni se acredita orquestación operativa de la pareja. Las
evidencias individuales anteriores de v1 y v2 se conservan; no demuestran esta
secuencia nueva, coordinación simultánea, separación o prevención de colisiones.

## Contrato MCP

`start_preflight_sequence(mission_paths, request_key, authorization_statement)`:

- Dos rutas JSON, en orden del operador: exactamente una misión `drone_01→v1` y
  otra `drone_02→v2`. Se admite el orden inverso. No hay asignación de tareas ni
  sustitución de IDs. Deben ser archivos regulares de hasta 5 MB dentro de `missions/`
  del proyecto; se rechazan escapes, FIFO, IDs desconocidos y pares del mismo dron.
- Declaración explícita y no vacía de consentimiento a **ambos snapshots y su orden**.
  Se registra como `OPERATOR_DECLARED_VIA_AGENT`, sin autenticar el diálogo. Preparar
  o consultar misiones, READY, APPROVED o PASSED previos no conceden ese permiso.
- Admisión rápida: persiste plan, autorización, copias exactas y SHA-256, dos IDs
  hijos/índices de clave y reserva global; sólo después separa el coordinador de MCP.
  `ACCEPTED/STARTING` no significa validación, despegue o PASSED. Los casos de formato,
  esquema o selección inválidos se rechazan sin lanzar coordinador.
- La clave identifica permanentemente la pareja ordenada de hashes y la declaración.
  Duplicados devuelven EXISTING sin lanzar trabajo; cambios devuelven REQUEST_CONFLICT.
  Si los archivos de un duplicado ya no se pueden leer, EXISTING indica explícitamente
  `request_comparison=UNAVAILABLE`: no verifica igualdad ni repite. Una combinación
  inválida no se acepta como nueva. Otra clave no evita una reserva ocupada.

`get_preflight_sequence(sequence_id=..., view="summary")`, o la misma consulta por
`request_key`, exige exactamente uno de esos identificadores. UUID canónico/clave
validada; nunca recibe una ruta de informe. Summary incluye estados, motivos,
incertidumbres, autorización declarada, IDs/hashes/rutas y restricciones. Detail
añade las respuestas completas de los hijos. Verifica integridad con las mismas
reglas; ninguna vista crea archivos, workers, vuelos o libera reservas. Una recarga
o respuesta perdida exige consultar **la misma** operación por ID/clave; no otro start.

Se mantienen herramientas/argumentos anteriores. Los hijos son jobs normales del
preflight asíncrono y conservan sus informes 1.1. Se consultan individualmente por
`run_id`; summary/detail conservan `sequence_id` y `sequence_index`. No se modifican
informes históricos ni se cambia su significado.

## Persistencia y trabajo

`missions/generated/preflight_sequences/<sequence_id>/` contiene:

- `plan.json`: orden, dos run_id/claves, hashes, selecciones, fuentes y declaración.
- `mission_1.json`, `mission_2.json`: copias exactas que el operador autorizó.
- `operation.json`: hash del plan, identidad PID/start_ticks/boot_id, estados,
  prevalidaciones de ambos y resultados/hashes de informes verificados.
- `coordinator.log`: stdout/stderr del proceso separado; stdin es DEVNULL,
  start_new_session y close_fds. El cierre/recarga de MCP no cancela ese proceso.

Los hijos viven en el almacén existente `missions/generated/preflights/<run_id>/`:
input/job antes de actuar; snapshot/report por el workflow habitual, worker.log
propio. El coordinador ejecuta **inline y secuencialmente** el worker de cada job;
no hay un subproceso adicional por hijo. Comparten PID/identidad del coordinador.
Por ello `worker_alive=true` de un hijo ya finalizado puede indicar que el coordinador
sigue con la pareja, no que ese hijo siga volando. Se usan job, informe y restricciones.

Antes del primer hijo se valida determinísticamente cada misión y su compatibilidad
con el executor/mapper. Si alguna falla, ambas permanecen NOT_STARTED. Esta pasada
no consulta readiness ni sustituye las validaciones/readiness de cada workflow o el
gate interno del executor justo antes de sus órdenes. No arranca/reinicia simulación.

Para continuar, el primer worker debe haber regresado normalmente, el job ser FINISHED,
el informe final persistido íntegro y del hash/vehículo previsto, el análisis estricto
recalculado idéntico y PASSED, con aterrizaje/desarmado confirmado. Se exige liberación
normal de la reserva del hijo y coherencia de la reserva de la secuencia. Se revalida
el primer informe antes del segundo y ambos antes de aceptar el PASSED global. No
basta un rótulo PASSED, un evento parcial, el fin del PID o una respuesta ausente.

## Exclusión sin hueco entre hijos

Encadenar dos starts normales no protege el intervalo entre ellos. Se añade
`vehicle_locks/sequence.json`, usando el registry.lock común. Toda admisión y el
executor síncrono ven esa reserva como bloqueo global incluso sin hijo activo.
El coordinador no retira esa reserva al terminar el primero: consume atómicamente
un slot exacto de la pareja y otorga la reserva normal v1.json/v2.json a ese hijo.
El índice consumido y el completado impiden repetir, saltar o invertir hijos.

Cada hijo mantiene el mutex OS global `v1.execution.lock`, gate, diagnóstico,
tolerancias y recuperación LAND existentes. Su autoridad sólo vale en el mismo
proceso coordinador para ese run_id/vehículo/hash, admite **una llamada al executor**
y se revoca al salir. No se hereda una autoridad de vuelo del padre ni se permite
usar el contexto copiado para repetir o cambiar el snapshot. La liberación normal
del hijo deja intacta la reserva exterior, que bloquea otros starts y ejecuciones
síncronas hasta el final seguro de la operación. La demo paralela sigue deshabilitada.

Ante un FAILED con recuperación LAND/desarmado confirmados, la pareja termina FAILED
y no inicia el siguiente; puede liberar normalmente sus reservas tras verificar
el resultado. BLOCKED sin vuelo también puede cerrar de forma segura. Si hay falta
de evidencia, contradicción, worker perdido o fallo de despacho, se conserva la
restricción y se requiere reconciliación. No se borra por timeout, consulta, clave
nueva, salida del mutex o muerte del proceso. Si el coordinador desaparece, el hijo
en curso puede quedar sin resultado y el autopiloto no queda detenido por ese hecho:
no se presume LAND ni se lanza otro hijo. No hay reanudación automática tras reinicio.

## Estados

| Nivel | Estado/resultado | Significado |
| --- | --- | --- |
| Admisión | ACCEPTED | Metadatos/reserva persistidos, validación pendiente |
| Admisión | EXISTING / REQUEST_CONFLICT | Misma clave recuperada / solicitud distinta; sin nuevo trabajo |
| Admisión | VEHICLE_BUSY / REJECTED, ERROR | Rechazo por ocupación / entrada o infraestructura inválida |
| Operación | ADMITTED, STARTING, RUNNING, FINALIZING | Admisión, inicio, validación/hijos, cierre seguro pendiente |
| Operación | FINISHED + PASSED | Ambos hijos íntegros PASSED, aterrizados/desarmados y cierre normal |
| Operación | FINISHED + FAILED, BLOCKED o ERROR | Resultado terminal conocido; ningún hijo posterior al que detuvo la secuencia |
| Operación | UNCONFIRMED, result_status=null | Resultado/propietario/cierre no confirmado; no continuar/reintentar |
| Consulta | ERROR / NOT_FOUND | Integridad/argumentos inválidos / operación no localizada; no equivalen a reserva libre |
| Hijo | NOT_STARTED | Sin despacho; no se registra como misión fallida; su job permanece QUEUED |
| Hijo | STARTING, RUNNING, VERIFYING | Intención persistida, worker en curso, o informe pendiente de verificación del coordinador |
| Hijo | FINISHED + resultado | Resultado individual verificado y hash del informe retenido |
| Hijo | UNCONFIRMED | Despacho/resultado incierto; informe observado puede existir sin autorizar continuación |

`observed_result_status` en la consulta de un hijo describe su informe disponible;
su aceptación por el coordinador se expresa aparte en state/result_status. Los
informes conservan PASSED/FAILED/BLOCKED/ERROR, sin alterar su análisis existente.

## Límites y evaluación

El control sigue siendo cooperativo entre **entradas actualizadas** del proyecto.
No protege contra ROS/QGC manual, scripts ajenos, manipulación del disco o servidores
antiguos que ignoren el nuevo guard. No desplegar con workers/versiones anteriores
activos. Los scripts de lifecycle no comparten un interlock atómico con vuelo:
no detener/reiniciar para la GUI mientras exista esta reserva o incertidumbre.

Copias, hashes, tokens e identidad de proceso no autentican el diálogo ni resuelven
todo TOCTOU. Ante pérdida/corrupción de archivos se falla de forma conservadora;
no se acredita persistencia frente a corte eléctrico/reinicio del host. No hay
watchdog que aterrice al morir el coordinador. La autorización se limita a esta
pareja: no permite otro ensayo, hardware, agricultura o seguimiento de velocidad.
No se demuestra que el otro dron esté inmóvil ni separación espacial/temporal de
tráfico externo. Duraciones de operación no equivalen a tiempo en vuelo.
Los hijos conservan la semántica temporal del worker existente: el started_at del
informe parte de la admisión del job y puede incluir tiempo en cola, especialmente
en el segundo; execution_started_at/execution_finished_at delimitan el executor.

Los tests offline usan Popen, readiness y control ROS doblados, con jobs, workflow,
análisis, identidad, mutex y registro SDK reales. Las pruebas operativas de esta
orquestación quedan pendientes; los PASSED individuales anteriores no las sustituyen.

Comprobación de cierre: **40 casos nuevos**, grupo afectado **139 passed in 6.65s**,
suite completa **428 passed in 12.91s**; git diff --check y los cuatro archivos nuevos
sin errores de whitespace. Registro SDK con 19 herramientas: se mantienen sin cambio
los esquemas de entrada de las 17 anteriores. Evidencias/runtime previos: 212 archivos
con los mismos SHA-256, sin crear trabajos reales en esos árboles durante el desarrollo.

## Prompts posteriores en Hermes

Revisar ambas misiones/snapshots, valores efectivos y defaults antes de autorizar.
Preparar y comprobar el simulador por separado; la operación no lo inicia. La clave
del ejemplo se debe conservar, sin sustituirla para repetir una respuesta perdida.

```text
Revisa sin iniciar simulación ni vuelos las misiones missions/examples/simulation_navigation_3waypoint.json y missions/examples/simulation_navigation_drone02.json, en ese orden, e informa de vehículos, valores efectivos, límites y datos necesarios antes de autorizar una pareja de ensayos secuenciales.
```

```text
Autorizo una única pareja de ensayos SITL estrictamente secuenciales de missions/examples/simulation_navigation_3waypoint.json y después missions/examples/simulation_navigation_drone02.json, con clave joel-secuencia-sitl-01: armado, despegue, recorrido y aterrizaje de drone_01/v1 y luego drone_02/v2 sólo si el primero pasa íntegramente y confirma aterrizaje y desarmado; no arranques ni reinicies simulación, conserva el identificador y no repitas ni reanudes ante incertidumbre.
```

```text
Consulta únicamente la operación con clave joel-secuencia-sitl-01 y explica el orden, hashes, autorización declarada, estado de cada hijo, informes, motivos y restricciones; no inicies, repitas ni reanudes ningún vuelo.
```

## 18/10/2026 — Primer intento operativo incompleto

La operación `c6eeb645-17d2-4081-9afb-cecfd23af393` con la clave del ejemplo terminó
UNCONFIRMED/reconciliation_required, result_status=null: v1
`467f7ec6-b2a6-4b68-9d97-766d85732f8e` conserva PASSED íntegro; v2
`1b69dfc7-0707-4b68-a009-062610418fe4` tiene informe ERROR por FlightControlError,
retorno 124, executor_result/analysis=null y reservas v2/secuencia UNCONFIRMED.
Job FINISHED significa worker terminado, no vehículo aterrizado. next_index=2 cuenta
despachos consumidos, no dos vuelos completados; completed_count=1.

El [diagnóstico y las capturas](../simulation/ros2_gazebo/results/sequential_preflight_diagnostic_2026_10_18/c6eeb645-17d2-4081-9afb-cecfd23af393/README.md)
conservan originales, logs actuales de servidor/GUI y consultas autorizadas de solo
lectura. En dos ventanas ambos vehículos reportaron armed=false/flying=false y
posición estable al nivel de salida, con mensajes/timestamps progresando. No se
libera ninguna reserva ni se certifica el estado posterior o contacto físico con el
suelo. La pantalla negra repetida es observación del operador; las causas de GUI y
del fallo ROS no se equiparan ni quedan resueltas. El PASSED individual anterior de
v2 `7162bce5-3635-4a76-bf02-6a5a22612aab` permanece intacto: no aprueba esta pareja.
La clave ya está consumida; no reintentar, reanudar o reiniciar para recuperarla.


## 19/10/2026 — Cierre offline de diagnóstico, reconciliación y lifecycle

El ERROR histórico de la secuencia c6eeb645-17d2-4081-9afb-cecfd23af393 y sus
reservas UNCONFIRMED permanecen intactos. El executor corregido explicará errores
futuros de origen/geopose y conserva intentos/confirmaciones; no identifica
retrospectivamente la lectura ni causa del 124. Lifecycle y vuelos comparten
mutex global/registro, también entre hijos. Reconciliación es un procedimiento
separado que no reanuda trabajos ni convierte ERROR en PASSED.

La nueva prueba preparada usa joel-secuencia-sitl-20261019-r02 y las dos misiones
JSON revisadas, con hashes; aún no hay admisión ni consentimiento de esa prueba.
[Guía operativa y criterios de parada](reconciliation-and-lifecycle.md).
La primera prueba es inspección en lectura; sin evidencia actual suficiente o
sin confirmación visual independiente de suelo para ambos, no se aplica nada.


### 19/10: inspección inicial bloqueada por SITL detenido

La inspección `1a977374-4df9-42a6-9409-d0e0c3a991e2` de `c6eeb645-17d2-4081-9afb-cecfd23af393` conserva el error del colector sin telemetría ni aplicación. Se añade una vía de cierre administrativo del entorno terminado con identidad verificable, versiones/propietarios y procesos revalidados bajo exclusión. No se arranca para demostrar que el anterior terminó. Se mantienen ERROR/UNCONFIRMED y PASSED individuales; no hay reanudación. [Procedimiento y límites](stopped-sitl-reconciliation.md). Pendiente operativo.
