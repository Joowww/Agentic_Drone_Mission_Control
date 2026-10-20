# Reconciliación de SITL detenido — 19/10/2026

> Revisión posterior del criterio legacy: [vínculo con la ejecución original y revisión administrativa](legacy-environment-binding-review.md). Una referencia posterior no basta para aplicar; se requiere declaración de continuidad/relojes y consistencia temporal. Los resultados anteriores de esta página se conservan como historia.

Implementada y probada **offline con dobles**. No se han ejecutado Docker, ROS,
inspecciones operativas, reconciliaciones, liberaciones, arranques ni vuelos en este
incremento. Esta vía complementa, sin sustituirla, la vía de entorno activo de
[reconciliación y lifecycle](reconciliation-and-lifecycle.md).

## Incidencia conservada y alcance de la referencia

La primera inspección operativa de `c6eeb645-17d2-4081-9afb-cecfd23af393` fue
`1a977374-4df9-42a6-9409-d0e0c3a991e2`, SHA-256
`ce2fc0ec49d29a617f81a8236329308c80bf4b91c19dd7ac6f24525765db61b8`.
El JSON local conserva BLOCKED, `reservations_changed=false` y RuntimeError del
colector: Docker identificó el contenedor completo
`0274e4fd856ab21e888a1820ea3867f2e2ec8641e0cb39c4658d8f01f9fcd30f` como no ejecutándose.
No conserva telemetría, propietarios/versiones inspeccionados ni aplicación. El
error por sí solo **no acredita terminación** ni aterrizaje; tampoco que esa fuera
la causa del 124 histórico. Su copia exacta de 452 bytes y hash están en
[el archivo de este incremento](../simulation/ros2_gazebo/results/stopped_sitl_reconciliation_2026_10_19/manifest.json).

El ID completo del error es una referencia local del contenedor al que se dirigió
una inspección anterior de **ese mismo propietario**. No acredita por sí solo el
motor Docker histórico ni la encarnación que ejecutó el vuelo; la respuesta lo
expone como `LEGACY_FAILED_INSPECTION_CONTAINER_ID`, con
`historical_engine_identity_known=false`. Se exige además observar ahora mediante
Docker ese mismo ID completo y nombre exacto, su imagen, creación, estado y tiempos,
identificar el motor actual y comprobar todas las reservas/artefactos/procesos.
No se acepta un texto del operador como sustituto del registro de proyecto.

Las nuevas inspecciones de entorno ACTIVE conservan una referencia más fuerte:
ID del motor, contenedor, imagen, creación e inicio, vinculada a las versiones de
reservas capturadas. La búsqueda sólo lee auditorías UUID bajo la raíz fija del
proyecto y del mismo propietario; no recibe rutas o IDs de contenedor arbitrarios.
Referencias contradictorias bloquean; no se escoge silenciosamente una favorable.
Una inspección STOPPED sin referencia previa queda BLOCKED: no puede convertirse
en su propia referencia repitiendo la inspección. Sin una referencia verificable
no hay desbloqueo genérico: hace falta revisar evidencia administrativa adicional
fuera de esta vía; no arrancar el simulador ni fabricar un vínculo retrospectivo.

## Decisión estructurada

| Observación | Tratamiento |
| --- | --- |
| DOCKER_UNAVAILABLE | No se pudo establecer identidad del motor: ejecutable/daemon inaccesible, timeout o metadatos inválidos. No demuestra estado del contenedor. BLOCKED. |
| CONTAINER_ABSENT | Motor accesible, ningún contenedor con el nombre exacto. No demuestra que el anterior terminó ni identifica un sustituto. BLOCKED. |
| REPLACED_OR_RESTARTED | Identidad de motor/contenedor/imagen/creación contradictoria con la referencia, o entorno actualmente activo reiniciado respecto al vínculo fuerte. BLOCKED. |
| UNKNOWN | Metadatos incompletos, contradictorios, paused/restarting/dead, cambios durante la lectura o fallo posterior al acceso al motor. BLOCKED. |
| ACTIVE | Lecturas nuevas de ambas interfaces y confirmaciones visuales independientes de suelo; se mantiene la vía anterior. Sin evidencia suficiente, BLOCKED. |
| STOPPED con referencia concordante | Candidato a cierre administrativo, sin telemetría ni confirmación visual imposible. Aún requiere autorización separada y revalidación. |

`environment.status` describe los metadatos actuales; `environment_assessment`
añade la concordancia con la referencia anterior. Se conservan los campos conocidos,
`unknown_fields`, operaciones/retornos/errores y tiempos de captura. La inspección
siempre devuelve los propietarios/versiones/procesos capturados cuando están
disponibles, incluso si falla el colector. Si la captura coherente falla, muestra
las reservas legibles como contexto no verificado y no permite aplicar.

La lectura de entorno usa únicamente `docker info` (ID), `docker ps --all` con
filtro de nombre exacto e `inspect` por ID completo con formato seleccionado. No
lee variables de entorno, credenciales ni configuración personal, no hace `exec`
y no arranca procesos. Como máximo cinco llamadas, **3 s por llamada**, con nueva
comprobación del nombre/ID y motor. Un timeout sigue siendo desconocimiento, no
prueba de parada. Las suscripciones ROS sólo se intentan después de verificar
ACTIVE; el colector mantiene su ventana y timeout anteriores.

Para STOPPED se requiere `Status=exited`, `Running=false`, `Pid=0`,
`Paused=false`, `Restarting=false`, `Dead=false` y tiempos válidos
`Created <= StartedAt < FinishedAt`. Son tiempos de pared **del motor Docker**:
no se comparan con ROS ni se afirma edad absoluta por restarlos del reloj local.
Un mismo contenedor ahora detenido también termina sus encarnaciones anteriores;
no se exige reconstruir su telemetría anterior. Lo observado ahora (incluidos
StartedAt y FinishedAt) debe seguir idéntico al aplicar. Si cambia, nueva inspección.

## Autorización, exclusión y resultado

La inspección no modifica restricciones. Si todo concuerda, devuelve
`AWAITING_TERMINATION_RECONCILIATION_AUTHORIZATION`,
`reconciliation_basis=ENVIRONMENT_TERMINATED`, ID y SHA-256,
`telemetry_collection=NOT_APPLICABLE_ENVIRONMENT_STOPPED`,
`requires_ground_confirmations=false`. Admitir la inspección no aplica nada.

La operación de aplicación existente recibe el ID/hash exactos revisados y una
`authorization_statement` explícita de **cierre administrativo**; se omite
`ground_confirmations` (o lista vacía) para esta vía. No rellenar declaraciones de
suelo ficticias. El campo MCP es opcional para permitir este caso; la vía ACTIVE
sigue exigiendo las dos declaraciones `OPERATOR_VISUAL`, posteriores a la inspección,
además de nuevas muestras. No se puede cambiar de vía automáticamente al aplicar.

Ambas fases toman sin espera el mutex global de ejecución y `registry.lock`, en
ese orden. Aplicar revalida propietarios, hashes/versiones, referencias, identidades
PID/start_ticks/boot y ausencia de coordinador/workers/ejecutores registrados;
un PID reciclado también bloquea. El mutex global libre acredita que ningún
executor actualizado lo retiene. El proceso de admisión se audita por separado:
un servidor o shell que sólo admitió un job no es su worker. Identidad de proceso
pertinente ausente o inspección fallida impiden cerrar. Para una reserva global
se incluyen ambos hijos/interfaces y los informes individuales existentes.

Se vuelve a obtener la identidad exacta del motor/contenedor y estado STOPPED
bajo la misma exclusión. Nuevos arranques/admisiones/ejecuciones del checkout
actualizado quedan excluidos, sin ventana de check-then-act ni bloqueo que requiera
que un worker vivo termine mientras se espera. No se heredan permisos de vuelo.
Los clientes Docker/ROS/QGC externos, versiones antiguas y alteraciones manuales de
archivos no participan en esta coordinación; no se promete exclusión frente a ellos.
Se confía en la veracidad de los metadatos del daemon, no en una prueba criptográfica
sobre el hipervisor ni en resistencia probada a clonación/reinicio del host.

La evidencia de aplicación dura **120 s desde el inicio monotónico**, mismo boot,
y se vuelve a comprobar tras la revalidación. Las referencias históricas de
identidad no son telemetría reciente: su hash se vuelve a validar, pero no sustituyen
los nuevos metadatos. Un colector que nunca obtuvo datos se expone como
`evidence_state=NOT_COLLECTED`, `evidence_expired=null`, `remaining_seconds=null`;
no se etiqueta como caducado. Evidencia recogida pero insuficiente puede caducar
sin haber sido nunca aplicable. Las consultas históricas no actualizan evidencia.

Antes de retirar una restricción se persisten APPLYING y barrera duradera, se
archivan las reservas originales con fsync y se registra APPLIED con transición
`ADMINISTRATIVE_CLOSURE_ENVIRONMENT_TERMINATED`. La aplicación idéntica repetida
consulta el resultado sin repetir acciones; argumentos distintos entran en conflicto.
Interrupción durante archivo conserva barrera y no se reanuda automáticamente.
`ground_contact=NOT_ASSERTED`, `flight_authorized=false`: cerrar restricciones
**no afirma aterrizaje, seguridad del vuelo anterior, PASSED ni ejecución posterior**.
Los jobs, operación, ERROR/UNCONFIRMED y PASSED individuales no se reparan ni editan.

## Próxima prueba de Joel: sólo inspección

```text
Inspecciona sólo en lectura las restricciones de la secuencia c6eeb645-17d2-4081-9afb-cecfd23af393 y contempla el caso de SITL detenido; contrasta la identidad previa del contenedor, su motor, estado y tiempos actuales, propietarios, versiones y procesos pertinentes; devuelve inspection_id, SHA-256, base de reconciliación, datos desconocidos, aplicabilidad y caducidad; no apliques reconciliación, no liberes reservas, no arranques ni reinicies la simulación y no vueles.
```

Esperado si el mismo contenedor está detenido y los demás controles pasan:
AWAITING_TERMINATION_RECONCILIATION_AUTHORIZATION, no telemetría aplicable y
`reservations_changed=false`. No anticipar ese resultado: **el estado actual no
se ha consultado en este trabajo**. Ante Docker inaccesible, contenedor sustituido,
referencia ausente, propietario vivo, contradicción o estado desconocido, detenerse
en BLOCKED y revisar los campos precisos; no reiniciar ni repetir con datos inventados.

La autorización de cierre se pide **después** de revisar esta nueva inspección
vigente. Recuperar GUI/arrancar después y ensayar una secuencia nueva requieren
otras decisiones y autorizaciones; nunca reanudar `c6eeb645-...`.

## Verificación offline real

- Selección final: **97 passed in 5.59s**.
- Suite completa final: **532 passed in 19.64s**.
- Sintaxis: 27 archivos Python, 5 scripts con `bash -n` y observador Python embebido.
- `git diff --check` sin avisos en versionados; código/docs nuevos limpios.
  Nueve piezas brutas anteriores conservan avisos de whitespace y sus bytes.
- 472 archivos anteriores/runtime seleccionados conservan sus SHA-256, incluidas
  reservas reales y evidencias anteriores. La copia nueva del BLOCKED coincide.
- Regresiones con dobles: activo/detenido/ausente/sustituido/desconocido; colector
  fallido con contexto parcial; nunca recogido frente a caducado; referencias y
  versiones cambiadas, PID reciclado, TTL/boot, autorización, idempotencia,
  consultas sin efectos, rutas/IDs, exclusión lifecycle/admisión durante aplicación
  y secuencia v1 PASSED/v2 ERROR sin reparación histórica ni segundo vuelo nuevo.

[Logs y manifiesto](../simulation/ros2_gazebo/results/stopped_sitl_reconciliation_2026_10_19/manifest.json).
No son pruebas de Docker/ROS real, reconciliación de la secuencia real, landing,
renderizado, proveedor LLM ni resistencia operativa a reinicios del host.
