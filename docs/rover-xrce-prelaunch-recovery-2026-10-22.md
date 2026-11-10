# Corrección del bootstrap y recuperación preparada — 2026-10-22

Estado: implementación y pruebas offline. **No se ha aplicado reconciliación ni repetido el ensayo.** Identidad completa y movimiento siguen BLOCKED.

## Hechos y causa

Ensayo original: [5d541497-25cb-4b23-af81-07808ade6eab](../simulation/ros2_gazebo/results/rover_xrce_trial_2026_10_22/5d541497-25cb-4b23-af81-07808ade6eab/README.md). Sus 75 entradas se verificaron por tamaño y SHA-256 sin modificarlas. SHA-256 del manifiesto: `be201cdc09f608abe2bb890c079e3a293ea1c84ef33e32c512d23c273c7be6f8`.

El backend copió `selection.py` como `/tmp/tfg_diagnostic_agent.py`. `descriptor()` intentó leer un hermano `/tmp/selection.py` que no existía. El traceback y el backend síncrono conservados sitúan el fallo de `prepare` antes de limpieza, creación del overlay y lanzamiento. El retorno 1 por sí solo no demuestra esa relación: la sustenta la revisión del código exacto y de los registros fijados por el manifiesto.

`selection.HELPERS` define juntos nombres lógicos y destinos de bootstrap. `helper_sources()` resuelve el selector mediante su propio `__file__`, aunque esté renombrado. El backend obtiene de esa definición los pares fuente/destino y la entrada. Comprueba la existencia del conjunto antes de copiar; `prepare` comprueba los hashes de ambos helpers y los artefactos antes de crear el overlay. El overlay conserva `selection.py` junto a `monitor.py`, como requiere su importación. El supervisor continúa importando el bootstrap como `tfg_diagnostic_agent`.

La regresión despliega esos nombres en un directorio temporal y ejecuta `__main__` con `prepare`. Se doblan ELF/readelf, descubrimiento de procesos y raíz temporal; no se ejecuta ningún ELF ni ROS. La misma regresión ejecuta la fuente original archivada: falla por `selection.py` ausente. También comprueba la importación del monitor desde el overlay resultante.

## Restricción y parada

Guarda **activa**, no copia archivada:
`missions/generated/vehicle_locks/lifecycle.json`, propietario `39fb9601-6691-4fd8-8987-21a81d4a34ee`, estado `UNCONFIRMED`, SHA-256 `cb2376ec12dcc9f2361a1aa6ad4ff44ae66626a12300f7a5da85a4757d265e32`.

El registro `missions/generated/simulation_lifecycle/39fb9601-6691-4fd8-8987-21a81d4a34ee/operation.json` conserva UNCONFIRMED. `missions/generated/diagnostic_agent_session.json` conserva el destino diagnóstico incierto. Sus originales archivados están en `runtime_copies/` del ensayo y su índice es `runtime_copy_index.json`.

`run_lifecycle()` comprueba `locks.restriction()` bajo los mutex de ejecución y registro antes de cualquier acción: por eso `stop` devolvió BLOCKED sin actuar. El PID registrado 352116 ya no tenía entrada `/proc` al revisar; esto no demuestra cierre, aterrizaje ni ausencia actual de procesos en el contenedor. La instantánea de cero procesos de las 17:28:54 UTC es histórica. En esta corrección no se han vuelto a recoger procesos ni identidad Docker del contenedor.

La reconciliación general de `tools/execution_reconciliation.py` requiere, para un entorno activo, telemetría y confirmación de suelo de v1/v2. No contempla cerrar el destino diagnóstico asociado ni prueba por sí sola la topología rover. No debe utilizarse para liberar únicamente esta guarda dejando ese destino UNCONFIRMED. La vía administrativa legacy existente pertenece exclusivamente a otro caso y tampoco se reutiliza.

## Recuperación limitada implementada, NO aplicada

[prelaunch_recovery.py](../tools/rover_xrce_trace/prelaunch_recovery.py) ofrece una API local separada, sin herramienta MCP, arranque, parada ni reanudación. Está fijada a este ensayo, propietario y manifiesto revisado. **No reconoce otros errores, propietarios o supuestos fallos anteriores al lanzamiento.** No generaliza una búsqueda de texto de traceback a cualquier operación.

`prepare()` vuelve a verificar todos los bytes de la evidencia, guarda/operación/log/destino/referencia originales y ausencia de otras reservas. Exige el mismo boot del host original y PID original ausente (un PID reciclado bloquea), ausencia de workers/coordinadores/executores/lifecycle host y lectura actual de la identidad completa del entorno, incluida su encarnación. Un entorno detenido, sustituido o desconocido bloquea esta vía.

La lectura acotada del contenedor ejecuta únicamente definiciones de inventario stdlib del supervisor archivado y lee `/proc` y rutas de estado. No importa ROS ni llama a `start`/`shutdown`. Exige ausencia de procesos propios, auxiliares ambiguos, SITL/agente/monitor/colector/worker, archivos de sesión y directorios de overlay/worker de este propietario. Un error de lectura o permisos bloquea. La ausencia de procesos es un requisito adicional a la prueba fijada de que este backend no llegó al lanzamiento, nunca su sustituto.

La preparación tiene TTL de 120 segundos de reloj monotónico y está ligada al boot del host. `apply()` exige ID, hash y declaración exactos, revalida bajo ambos mutex y archiva durablemente TODOS los originales antes de la primera transición. Un marcador de reconciliación impide admisiones durante la escritura. Cierra únicamente el destino diagnóstico, retira la guarda de este propietario y guarda un informe separado. **No reescribe la operación UNCONFIRMED, su log ni resultados históricos; no afirma aterrizaje, éxito del arranque ni terminación histórica del contenedor.**

La autorización es una declaración local explícita, no autenticación humana. No se expone por MCP ni debe delegarse a Hermes para reconstruir o sustituir IDs. Joel debe revisar la salida y ejecutar por separado la aplicación local si la autoriza. No se prepara de nuevo ni se aplica automáticamente ante caducidad o error.

Un fallo parcial conserva/restablece el marcador y bloquea las admisiones. Repetir una aplicación terminada sólo consulta su informe. Una aplicación incompleta **no se reanuda**: requiere revisar el archivo `application.json`, `originals/`, marcador y versiones; no hay comando de force-unlock ni borrado manual admitido. Esta versión prepara el cierre normal y falla cerrada ante una interrupción; no automatiza la recuperación de una escritura parcial.

## Procedimiento revisado — 2026-10-23

Sustituye el procedimiento del 22/10 que generaba una preparación con TTL antes de la revisión humana. La interfaz local `inspect` ahora escribe únicamente una **inspección informativa sin TTL**, sin preparación ni elegibilidad de aplicación:

```bash
.venv/bin/python -m tools.rover_xrce_trace.prelaunch_recovery inspect
```

Inspección ejecutada el 23/10 a las 10:42 CEST (08:42 UTC):

- ID: `5c6b3d29-9709-4a38-bad8-651b1bf7e2f5`.
- SHA-256: `df79ae2c64254f971ca488b3e250c786b0cdae31839a2734bbfec3babb079021`.
- Resultado: `REVIEWABLE_NOT_AUTHORIZED`, sin motivos de bloqueo, `preparation_created=false`, `application_eligible=false`, `reservations_changed=false`.
- [Copia exacta y auditoría de las lecturas](../simulation/ros2_gazebo/results/rover_xrce_recovery_review_2026_10_23/5c6b3d29-9709-4a38-bad8-651b1bf7e2f5/inspection.json).
- Motor `2c4ad774-b7c7-4d26-ba0e-690fb9d0ff99`; contenedor `0274e4fd856ab21e888a1820ea3867f2e2ec8641e0cb39c4658d8f01f9fcd30f`; imagen `sha256:5d5de3c69e2af0a4d565e74e4637b26880f574c7db5d8f3f8b90f479983e3d66`. Misma encarnación activa, `StartedAt=2026-10-21T08:24:48.062034411Z`, PID del contenedor 36004.
- Mismo boot del host original, PID del propietario ausente y sin workers/coordinadores/executores/lifecycle host pertinentes. Inventario del contenedor sin procesos propios/ambiguos detectados, sin overlay/worker de este propietario y sin archivos de estado. Esto es observación actual acotada, no prueba de suelo ni de continuidad criptográfica.

`scope.transitions` muestra los JSON exactos propuestos: archivar los cinco originales, cerrar únicamente `diagnostic_agent_session.json` con la base de fallo previo a lanzamiento, retirar únicamente `vehicle_locks/lifecycle.json` de este propietario y quitar el marcador transitorio sólo tras el commit confirmado. `operation.json` queda UNCONFIRMED e intacto; no hay arranque, parada, recepción ni movimiento.

**Comando pendiente de autorización de Joel, NO ejecutado:**

```bash
.venv/bin/python -m tools.rover_xrce_trace.prelaunch_recovery apply-reviewed --inspection-id 5c6b3d29-9709-4a38-bad8-651b1bf7e2f5 --inspection-sha256 df79ae2c64254f971ca488b3e250c786b0cdae31839a2734bbfec3babb079021 --authorization 'AUTHORIZE_PRELAUNCH_SCOPE 39fb9601-6691-4fd8-8987-21a81d4a34ee 5c6b3d29-9709-4a38-bad8-651b1bf7e2f5 df79ae2c64254f971ca488b3e250c786b0cdae31839a2734bbfec3babb079021'
```

Este comando autoriza el **alcance inspeccionado**: una preparación fresca y una aplicación consecutiva dentro de los 120 s existentes. No afirma autenticar al humano. El comando comprueba ID/hash del informe y estado REVIEWABLE, consume durablemente esa autorización una sola vez, vuelve a comparar bajo exclusión versiones, entorno, procesos, código de recuperación y transiciones, genera una preparación ligada al informe y llama a la aplicación exacta. Esta revalida de nuevo bajo exclusión antes de archivar/modificar. El informe informativo no caduca como si fuera telemetría; su estado no se reutiliza como prueba fresca ni evita esas nuevas lecturas.

Cambios desde la inspección, un código diferente, propietario/PID reciclado, otro boot, entorno incierto, procesos o artefactos de sesión inesperados, caducidad, I/O parcial o respuesta perdida obligan a detenerse. No hay renovación, nueva preparación, sustitución de IDs ni repetición automática. La autorización consumida no puede volver a preparar tras una recarga/error; revisar `authorization-consumed.json`, `fresh-preparation.json` si existe, y la auditoría de aplicación. Un fallo parcial mantiene las restricciones; no hay reanudación automática.

Esperado tras una aplicación autorizada: `APPLIED`, originales archivados con hashes, destino CLOSED con base `REVIEWED_PRELAUNCH_FAILURE_NO_LAUNCH`, operación histórica todavía UNCONFIRMED y ausencia de guarda activa/marcador pendiente. En este turno **no se llamó a prepare/apply sobre el caso real**.

### Artefactos y siguiente ensayo, todavía NO autorizado

Lectura del 23/10 a las 10:44 CEST: [artifacts.json](../simulation/ros2_gazebo/results/rover_xrce_recovery_review_2026_10_23/5c6b3d29-9709-4a38-bad8-651b1bf7e2f5/artifacts.json) confirma wrapper, biblioteca y colector regulares, sin sustitución de rutas ni hashes y con `readelf -d` correcto. No se ejecutaron binarios ni fue necesario reconstruirlos.

| Artefacto | SHA-256 observado y fijado |
|---|---|
| Wrapper | `b1330420c764240c971263d5ec7abea3da82a46555bf677a2f21a1d78694325c` |
| Biblioteca nativa | `5bae08d754e8113b99c1d418154f907754168b1217b5be18c0969738def55703` |
| Colector preparado, distinto del histórico 43d5… | `94c0a9dd4a454c41561b0355803a7232ae001cf842336124341163ff5cf90d93` |
| Selector corregido en host | `0f1b45bff01911e12a7cc3494979824ea5d7388109597053cc4ef71ce5fbc411` |
| Monitor en host | `9b211988c9941cce36033499ce9076f29efa00096cb423bc398b3a199a54e312` |

La disponibilidad no valida su comportamiento operativo. El bootstrap anterior no se ha reparado dentro del contenedor: un próximo arranque autorizado copiará los helpers corregidos mediante el backend, con sus hashes verificados antes del lanzamiento.

Después de una recuperación confirmada, exigir nuevo prechequeo actual/revalidación atómica y **otra autorización independiente** para el ensayo. Seguir la receta existente de [rover_xrce_trace/README.md](../tools/rover_xrce_trace/README.md#next-single-trial--proposed-not-authorized-or-executed): una apertura protegida con selector diagnóstico, traza desde el arranque, agente único/bibliotecas/monitor coherentes, confirmación visual real de Joel, una recepción con máximo 20 muestras/120 s y `--reserve-streams`, y una parada protegida. Sin readiness/prearm ni servicios de vehículos. Si falla arranque o visualización, no iniciar colector. No reiniciar ni repetir.

Conservar en un directorio privado nuevo las identidades y fuentes efectivas, traza cruda, diario/recibo/retorno y cierre. Analizar sólo datos de la misma sesión, exigiendo GID/RMW exacto por muestra Status, conversión nativa, generación/intento/cliente/sesión/objeto, creación XRCE confirmada y topic/tipo/dominio coherentes. Rechazar mezclas, contradicciones o falta de registros. Cierre de infraestructura, cobertura y correlación son resultados separados. Incluso con el enlace DDS→XRCE observado, identidad completa y movimiento siguen BLOCKED: faltan los enlaces posteriores hacia SYSID/SITL y bridge/modelo.

## Comprobaciones offline realizadas

La tanda de selección/traza, lifecycle, exclusión entre hijos, reconciliación y perfiles pasó **172 tests** (114,29 s). Tras añadir regresiones específicas de recuperación y la comprobación del boot original, la tanda final de selección desplegada y recuperación se volvió a ejecutar: **66 tests pasados**. Son dobles y archivos temporales, no validación operativa de recuperación. También se comprueban sintaxis Python/Bash, whitespace de los archivos nuevos y conservación del manifiesto original.

Límites: los mutex coordinan las entradas del proyecto, no clientes ROS/Docker externos. No se autentica criptográficamente al operador ni al entorno histórico. La prueba de etapa es una revisión fijada de este caso concreto, no un protocolo general de checkpoints: cualquier cambio de prueba o estado bloquea. Una avería total del almacenamiento puede impedir incluso escribir un marcador; una excepción de persistencia nunca debe interpretarse como cierre confirmado.

### Verificación del 23/10

Tests afectados ejecutados una vez sobre el código actual: **72 passed in 4.30s**, `tests/test_rover_prelaunch_recovery.py` y `tests/test_rover_diagnostic_selection.py`. Incluyen disposición desplegada/original fallido, inspección sin TTL ni aplicación, alcance cambiado, autorización incorrecta/consumida, caducidad, exclusión y persistencia parcial. No se ha repetido la tanda amplia histórica de 172 tests. La inspección y los hashes de artefactos sí son lecturas reales del entorno actual; los tests de transición usan exclusivamente runtime temporal y dobles.
