# Retiro administrativo exclusivo de c6eeb645 — implementación offline

## Estado vigente desde el 20/10/2026 — aplicación bloqueada

La [auditoría local](auditoria-retiro-c6eeb645-2026-10-20.md) confirma el retiro ya
persistido, pero documenta el cambio de preparación autorizada a otra pareja ID/hash
sin nueva autorización comunicada por el operador. No se revierte ni se repite el
retiro ni se autentica retrospectivamente su declaración vía agente.

**Aplicación y recuperación que cambien estado están deshabilitadas.** El proyecto
no tiene integrado un canal que verifique confirmación humana independiente de los
argumentos del modelo. Hermes dispone de elicitation con UI de aprobación en el
código inspeccionado; ni su disponibilidad en esta conexión ni el origen humano de
un accept están acreditados al servidor. Un esquema o statement no los demuestra.

El contrato nuevo exige preparation_id y preparation_sha256 también dentro de la
declaración y rechaza cualquier discrepancia con los parámetros exteriores. Aun con
coincidencia exacta y preparación vigente devuelve OPERATOR_CONFIRMATION_UNAVAILABLE
antes de tomar mutex, observar Docker o escribir intención/barrera/errores. Caducidad
o boot distinto devuelve PREPARATION_EXPIRED_OR_BOOT_CHANGED; otra pareja devuelve
CONFIRMATION_BINDING_MISMATCH. No se renueva ni se reanuda automáticamente.

Después de timeout, error, respuesta perdida o recarga: sólo consultar la auditoría.
accepted_request es entrada histórica del agente, no prueba de consentimiento ni
instrucción para repetir. Un resultado ya finalizado puede devolverse en lectura,
sin ejecutar otra vez el retiro. Un resultado incompleto conserva sus restricciones;
no se reactiva ni siquiera con los mismos argumentos o por recarga.

Consulta histórica opcional, sin operaciones, en una sola línea:

```text
Consulta únicamente la auditoría local del retiro administrativo de c6eeb645-17d2-4081-9afb-cecfd23af393; distingue el resultado persistido, guard activos, archivos históricos y la discrepancia entre la preparación autorizada y aplicada, sin preparar, aplicar, recuperar, reconciliar ni modificar reservas.
```

No hay un prompt operativo de aplicación habilitado en esta versión. Para una
futura habilitación se requiere un canal revisado que transporte una nueva respuesta
independiente del modelo ligada al ID/hash exactos, con rechazo por caducidad,
cancelación, error o cambio de conexión. No basta copiar los IDs, introducir otro
flag, hacer que el agente genere un token ni usar un terminal controlable por él.
Véase [revisión del protocolo y pruebas offline](retirement-confirmation-2026-10-20.md).

## Historia de implementación y procedimientos anteriores — no vigentes

Se conserva a continuación el texto del 19/10. Sus prompts de autorización y
recuperación **no deben ejecutarse**: quedan sustituidos por el bloqueo anterior.

Implementado y probado con dobles/temporales. **Ninguna preparación operativa,
consulta Docker/ROS, aplicación, liberación, arranque, reinicio ni vuelo se ejecutó
en este incremento.** El encargo sólo autoriza implementar y verificar offline.
Los prompts al final son para que Joel decida usarlos después.

## Qué resuelve y qué queda desconocido

La consulta histórica de docker events devolvió, según el operador, **salida vacía
y código 0**. Se registra como observación aportada: no se aportaron aquí argumentos
exactos ni un log terminal original y no se repitió. No prueba ausencia de actividad,
vuelo o eventos antiguos; tampoco completa el vínculo original de Docker.

Joel no puede confirmar continuidad histórica de contexto ni relojes. Esta operación
no pide hacerlo. La autorización acepta expresamente **la incertidumbre** al retirar
solamente dos restricciones locales; no fabrica una reconciliación técnicamente
verificada ni modifica los resultados del ensayo. No usa la inspección ad234044
caducada como permiso ni como estado actual del simulador.

Scope fijo:

| Archivo | Propietario | SHA-256 |
| --- | --- | --- |
| sequence.json | c6eeb645-17d2-4081-9afb-cecfd23af393 | 47385b4ebc900482d1202131e2421d55a316c7144ccce8bc135cabfaaf73505e |
| v2.json | 1b69dfc7-0707-4b68-a009-062610418fe4 | c7bcb0a629e02e9676a5b25b43a089b73686c23ce4e39e7a4368936c59b91954 |

La [propuesta original](../evaluation/operations/administrative_retirement_c6eeb645_proposal_2026_10_19.json)
se conserva byte por byte, incluido su estado documental histórico. El código fija
su SHA-256 `32eb6f31ae191174136fa6bf054beb5071f4625d2f6fbcff61209d213c76d99a`.
No se reciben otras propuestas, rutas, propietarios, hashes de política ni flag force.
Cambiar esa propuesta hace que la operación bloquee. Sus 16 versiones/ausencias
de archivos y los dos originales fijan el único caso admisible.

Se fija además el motor actual `2c4ad774-b7c7-4d26-ba0e-690fb9d0ff99` y el contenedor
`0274e4fd856ab21e888a1820ea3867f2e2ec8641e0cb39c4658d8f01f9fcd30f`, nombre
`/tfg-ardupilot-gazebo`. Una lectura nueva debe confirmar STOPPED/exited,
Running=false, Pid=0 y sin paused/restarting/dead. Docker inaccesible, identidad
diferente o estado dudoso bloquean. No se arranca nada para obtener esa evidencia.

La terminación del **entorno original**, continuidad y relojes históricos siguen
UNKNOWN/UNVERIFIED. La de este contenedor actual se comprueba sin compararla con
los tiempos antiguos del host. boot_id identifica el boot/namespace del host de
workers y vigencia local, no identidad ni reinicio del daemon Docker.

## Herramientas y dos fases

Las herramientas aparecen al cargar el servidor MCP actualizado. Si se necesita
`/reload-mcp`, esa recarga no inicia simulador ni aplica/reanuda la operación.
Las herramientas existentes, gate, executor, tolerancias y workers no se cambian.

1. `prepare_legacy_sequence_retirement`: lectura operativa del caso fijo, que guarda
   **sólo una auditoría nueva**. Toma sin espera mutex global de ejecución y registro,
   comprueba propietarios/16 versiones y procesos con capture existente, lee metadatos
   Docker acotados y repite la captura para detectar cambios. Devuelve preparation_id,
   SHA-256, rutas y AWAITING_EXPLICIT_ADMINISTRATIVE_AUTHORIZATION. No cambia reservas.
   La preparación dura 120 s monotónicos y mismo boot hasta la primera aceptación.
2. `apply_legacy_sequence_retirement`: exige ID/hash revisados y autorización tipada.
   Bajo la misma exclusión revalida versiones, identidades/procesos y entorno idéntico
   al preparado **antes de escribir intención o modificar restricciones**. Cualquier
   cambio, evidencia insuficiente o caducidad inicial bloquea.
3. `get_legacy_sequence_retirement`: consulta **de archivos solamente** por preparation_id,
   o sin ID para recuperar la intención ya aceptada/última preparación del caso.
   No consulta Docker/ROS ni crea trabajos, prepara, aplica o reanuda. Tras respuesta
   perdida se consulta primero; no inventar IDs ni inspeccionar directorios a mano.

La autorización requiere source=OPERATOR_ADMINISTRATIVE_DECISION,
accept_unverified_historical_environment=true,
accept_unknown_historical_clocks=true, local_reservations_only=true y statement
explícito no vacío. Son aceptaciones de incertidumbre/alcance, **no afirmaciones de
hechos desconocidos**. Se guardan exactamente con el ID/hash de preparación. El
esquema impide formas incorrectas, no autentica al operador ni la fidelidad de Hermes.

Un preparation_id no significa retiro autorizado. Una preparación bloqueada no
concede permiso; tampoco el último mensaje de implementar/probar offline lo concede.
Si las condiciones pasan, el resultado final separado es
**ADMINISTRATIVELY_RETIRED_UNVERIFIED**, nunca PASSED ni APPLIED de reconciliación
verificada. `original_environment_termination=UNKNOWN`, ground_contact=NOT_ASSERTED,
flight_authorized=false. Secuencia UNCONFIRMED, hijo v1 PASSED, hijo v2 ERROR y todos
sus snapshots, hashes y archivos permanecen intactos.

## Exclusión, durabilidad y estados interrumpidos

Se reutilizan `v1.execution.lock` como mutex global, `registry.lock`, la barrera
`vehicle_locks/reconciliation.json`, fsync/JSON atómico e historial de originales.
La barrera tiene kind=CASE_SPECIFIC_ADMINISTRATIVE_RETIREMENT y queda ligada a
preparation_id, hash de preparación, intención inmutable y política fija. Todas las
entradas actualizadas que usan la exclusión común —ejecuciones, admisiones y
lifecycle MCP/Python/scripts— quedan bloqueadas, incluso entre retirar v2 y sequence.
No se mantiene un mutex esperando a que termine un worker: se exige que sus procesos
pertinentes estén ausentes antes de continuar. PID reciclado también bloquea.

Orden de persistencia:

1. Intención/autorización inmutable y fsynced, antes de la barrera. Si falla aquí,
   siguen las dos reservas originales; ninguna autorización se hereda a otra preparación.
2. Barrera común durable, antes de retirar cualquier archivo.
3. **Ambos originales** publicados sin sobrescritura y fsynced en
   `vehicle_locks/history/<preparation_id>/`, antes de la primera retirada.
4. Nueva lectura del entorno tras el I/O de archivo y nueva comprobación de versiones/
   procesos. Retirar v2 y luego sequence, con revalidaciones, journal y fsync del
   directorio en cada paso. No se reconstruyen reservas ni resultados ausentes.
5. Resultado final inmutable y durable, antes de quitar la barrera. Así, sin barrera
   nunca hay una retirada parcial ordinaria sin evidencia final persistida.

Auditoría bajo `missions/generated/administrative_retirements/c6eeb645-17d2-4081-9afb-cecfd23af393/`:
`preparations/<id>/preparation.json`, `intent.json`, `journal.json`, `attempts/` y
`result.json`. Se conservan originales, errores y temporales de publicaciones
interrumpidas. No se sobrescribe evidencia canónica corrupta o distinta para arreglarla.

Si la llamada termina, se recarga MCP o muere el proceso, el estado está en disco.
La consulta muestra RECOVERY_REQUIRED, barrera, originales restantes, rutas, motivos
de integridad y `accepted_request` con los argumentos exactos aceptados. Esa consulta
**no es autorización ni reanudación**. El PID del llamador administrativo se audita;
puede ser un servidor MCP aún vivo pero inactivo. El mutex global libre demuestra que
ninguna llamada actualizada sigue en esa sección crítica; no se le confunde con un
worker de vuelo original ni se exige matarlo para recuperar.

Una **nueva llamada explícita con exactamente los mismos argumentos** puede finalizar
la transacción ya autorizada. Aunque caduque la preparación inicial o cambie el boot,
la intención durable sólo autoriza completar ese mismo retiro: se exigen nuevas
comprobaciones actuales bajo exclusión. No admite otro ID, declaración diferente,
propietarios/archivos cambiados ni otro entorno. Ninguna consulta o arranque del
servidor hace esta recuperación automáticamente. Si no llegó a persistir intención,
sigue aplicando TTL/mismo boot y puede hacer falta otra preparación de lectura.

Resultado final durable con barrera todavía presente sigue dando RECOVERY_REQUIRED:
no se declara libre el slot hasta completar limpieza explícita y revalidada. Repetir
una aplicación ya terminada devuelve historia sin nuevas observaciones/mutaciones.
Una restricción posterior de otro actor no se retira ni altera con ese replay.

Ante cambio de versiones, propietarios, procesos, entorno o integridad después de una
interrupción: **BLOCKED/ERROR**, conservar lo restante y revisar el motivo. No cambiar
la autorización, inventar preparación, editar JSON o borrar barreras para pasar. No hay
takeover genérico. Recuperabilidad cubre interrupciones en las publicaciones atómicas
bajo las garantías del filesystem local; daño de evidencia, pérdida del dispositivo
o fallo permanente de persistencia no se presentan como recuperación automática.
Si falla incluso restaurar protección, la respuesta expone protection_error y no
asegura exclusión que no haya podido confirmar. El resultado durable precede siempre
a la eliminación de la barrera y los originales ya están archivados.

El ámbito es el registro local y los clientes actualizados. No se demuestra ausencia
de otra simulación antigua/remota desconocida, ni se controlan clientes ROS/QGC/Docker
externos, versiones antiguas o ediciones manuales fuera de la exclusión. El retiro no
certifica terminación de ese entorno desconocido ni separación entre drones. No
se reanuda la secuencia fallida ni se concede permiso de hardware/otro vuelo.

## Prompts naturales para Joel — no ejecutados aquí

Primero, preparación de sólo lectura:

```text
Prepara únicamente en lectura el retiro administrativo exclusivo de las restricciones locales de la secuencia c6eeb645-17d2-4081-9afb-cecfd23af393; comprueba propietarios, hashes, versiones, procesos y el contenedor actual detenido y devuelve el identificador de preparación, SHA-256, vigencia, rutas y alcance; conserva la incertidumbre histórica, no apliques el retiro, no liberes reservas, no arranques ni reinicies y no vueles.
```

Esperado AWAITING_EXPLICIT_ADMINISTRATIVE_AUTHORIZATION, dos reservas intactas y
preparation_id/hash revisables. Ante BLOCKED/ERROR/identidad desconocida o cambio:
detenerse; no autorizar mientras no se resuelva el motivo. Si caduca sin intención
aceptada, preparar otra vez en lectura y revisar ese nuevo ID/hash.

Después de revisar una preparación vigente, autorización de **ese único retiro**:

```text
Autorizo únicamente el retiro administrativo de las dos restricciones locales fijadas de la secuencia c6eeb645-17d2-4081-9afb-cecfd23af393 usando la preparación <preparation_id> y SHA-256 <preparation_sha256>; acepto expresamente que el entorno original no está verificado y los relojes históricos son desconocidos, sin afirmar continuidad, aterrizaje ni terminación original; revalida bajo exclusión, conserva los originales y PASSED/ERROR/UNCONFIRMED, registra ADMINISTRATIVELY_RETIRED_UNVERIFIED y no arranques, reinicies ni vueles.
```

Esperado resultado administrativo persistido, ambos originales en historial y barrera
retirada de forma confirmada. No significa ensayo aprobado o entorno original terminado.
Ante timeout/respuesta perdida/interrupción, consultar sin efectos:

```text
Consulta sólo la auditoría del retiro administrativo de c6eeb645-17d2-4081-9afb-cecfd23af393 y recupera el identificador y los argumentos exactos aceptados si existen; explica el estado, barrera, archivos restantes y posibles errores sin preparar, aplicar, reanudar, liberar reservas ni iniciar simulación o vuelos.
```

Sólo tras revisar RECOVERY_REQUIRED y decidir completar **esa misma operación**:

```text
Autorizo completar únicamente el retiro administrativo ya aceptado de c6eeb645-17d2-4081-9afb-cecfd23af393 reutilizando exactamente accepted_request de su auditoría, sin cambiar identificador, hash ni declaración; vuelve a comprobar bajo exclusión las condiciones actuales y conserva el bloqueo ante cambios o dudas, sin iniciar simulación ni vuelos.
```

No repetir automáticamente. GUI/readiness y cualquier nueva secuencia se deciden y
autorizan por separado después; estos prompts no los autorizan.

## Verificación realizada offline

Pruebas afectadas finales: **112 passed in 15.31s**. Suite completa:
**601 passed in 44.11s**. Los registros están en
`simulation/ros2_gazebo/results/administrative_retirement_offline_2026_10_19/`.
Se prueban los esquemas y el dispatch realmente registrados en MCP, sin servidor
operativo, con las observaciones de entorno y procesos y el lanzamiento de workers
sustituidos por dobles. Los archivos del caso se copian a temporales.

Las regresiones cubren propietarios/versiones cambiados, PID reciclado, preparación
caducada, rechazo de otro caso/autorización, consulta tras recarga sin efectos,
interrupciones de publicación/fsync/archivo/retirada y aplicación idéntica repetida.
Barreras deterministas comprueban exclusión frente a lifecycle, admisiones de ambos
vehículos y segunda aplicación, incluso con ambos originales ya archivados/retirados
y antes del resultado final. Una barrera durable sigue bloqueando tras devolver error.
Esto prueba el contrato offline; queda pendiente el uso operativo autorizado.
