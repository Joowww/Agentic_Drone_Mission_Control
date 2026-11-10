# Rover: avance autónomo offline — 07/11/2026

Base de código: `57a0e303afb8060db667d2273ed3a8bed262265f`; rama `feature/rover-sitl-first-motion`.

## Estado y autorización

Se conserva el cambio local protegido anterior. La política `PASSIVE_SCOPE_POLICY_ENABLED` permanece en `False`. No se ejecutó precheck, START/STOP, ROS, MAVLink, SITL, Gazebo ni control de vehículo. El trabajo de Claude se leyó desde el commit fijo `9a5de915fae7851f654f791b65d12f0681533fec`; su worktree no se modificó.

## Protocolo futuro del helper separado (diseño; no implementado)

Transporte previsto: socket Unix con permisos del host y verificación del UID del servidor mediante `SO_PEERCRED`; el proceso agente no puede escribir el ledger. La solicitud `ISSUE` lleva el binding completo enumerado arriba más TTL acotado. El helper presenta ese binding al aprobador humano desde su proceso/TTY independiente y persiste `ACTIVE` solo tras confirmación. `CONSUME` recibe authorization ID y el mismo binding, valida UID de cliente, sesión/boot/expiración/estado y marca `CONSUMED` de forma atómica antes de START. `REVOKE` solo afecta a registros activos; `STATUS` es lectura. Respuestas: `APPROVED`, `DENIED`, `CONSUMED`, `REVOKED`, `EXPIRED`, `UNKNOWN`; timeout/caída da `UNKNOWN` y nunca reintenta. Campos ausentes, UID inesperado, cambio de boot, corrupción o pérdida de ledger rechazan. No hay respuesta fixture aceptable en productivo.

El protocolo no se ofrece como autenticado hasta que el helper aplique las comprobaciones con una identidad real separada y el ledger esté bajo un UID distinto. La cadena SHA-256 del backend offline solo detecta ediciones que no recalculen toda la cadena. Para resistir escritura del mismo usuario hace falta aislamiento de dueño/permisos o almacenamiento protegido por el host; no se afirma resistencia frente a root. Configurar UID, grupos, socket, permisos y servicio requiere una autorización manual futura y queda fuera de esta iteración.

### Receta de configuración manual futura (no ejecutada)

Antes de autorizarla, confirmar que systemd funciona en esta WSL y definir la identidad agente efectiva. Como root/admin, crear `rover-approver` con login humano separado y contraseña propia; verificar con `id rover-approver` que no pertenezca a `sudo` ni a grupos del agente. Instalar el binario del helper propiedad de `root:root` y no escribible por agente/aprobador; ejecutar su servicio bajo `rover-approver`. Crear `/var/lib/rover-approval` con dueño `rover-approver:rover-approver`, modo `0700`, y ledger `0600`; crear `/run/rover-approval` temporal con dueño/grupo y modo mínimos definidos por el protocolo. El socket acepta solicitudes del agente, pero solo la sesión interactiva del aprobador puede emitir aprobación; la UI enseña scope/session/vehículo/operaciones/boots/expiración antes de confirmar. Verificar después UID efectivo del helper con `SO_PEERCRED`, permisos de todos los padres, reinicio, replay y revocación. No añadir `rover-approver` a sudo, no compartir credenciales y no habilitar el gate en esta configuración inicial. Cada paso requiere autorización humana específica de configuración del host y revisión protegida posterior.


## P1 — proveedor de autorización offline

`tools/rover_local_authorization.py` implementa el contrato local de referencia y `tests/test_rover_local_authorization.py` cubre su comportamiento con identidad `TEST_FIXTURE`:

- vinculación exacta a scope SHA-256, sesión, owner, vehículo, perfil, operaciones, host/container boot y digest del entorno;
- expiración, revocación, consumo único, replay y doble consumo concurrente;
- persistencia atómica bajo `flock`, recuperación tras reinicio y rechazo de ledger ilegible/corrupto;
- rechazo explícito del backend y de credenciales fixture en modo productivo.

El ledger encadena hashes y detecta corrupción/replay accidental; **no está firmado** y no acredita identidad frente a quien comparte el UID. No hay helper, UID de aprobador, canal autenticado ni provider productivo instalado. `Principal` de `LOCAL_HELPER_PEERCRED` no se puede crear mediante el backend fixture; queda pendiente el cliente/servidor que obtenga esas credenciales del socket local y la autenticación humana fuera del proceso agente. No se usaron firmas criptográficas propias. No se modificó el host.

Prueba focalizada del proveedor, adaptador y bridge: **22 PASS**. Suite offline amplia tras todos los cambios: **2416 PASS, 4 SKIP, 0 FAIL** en 646.21 s. No equivale a promoción ni a prueba de autenticación real.

## P2/P2B — lifecycle, fases y deadline

El lifecycle vertical actual conduce diez recibos enlazados con una sola reserva/consumo de worker, captura exacta de 100 observaciones, análisis de estacionariedad, cierre y supervisor de STOP limitado a 15 s; la prueba vertical usa callbacks y estados sustituidos. La cadena demuestra contratos de orquestación y fail-closed, no proveedores de ROS/runtime.

Faltan productores/runtime acreditables para READY, MotionBinding `/2`, lecturas con procedencia de parámetros, observaciones, confirmación de cierre e inventario. Esos callbacks deben implementarse contra interfaces de solo lectura y probarse mediante inyección antes de cambiar la política. STOP representa solicitud/confirmación/UNCONFIRMED; la espera limitada no garantiza terminación física. Los tests existentes cubren retraso y pérdida de respuesta; worker bloqueado y cierre tardío siguen como casos pendientes de endurecer. No se usó kill externo.

## P4 — Claude M4c-r1

La prueba contractual está fijada al commit `9a5de915fae7851f654f791b65d12f0681533fec` y comprueba hashes de los módulos puente. Reproduce con `git show` la solicitud histórica de `multiagent/benchmark/results/m4c_r1_integrated_v1_2026-11-07_f1ec396c9/demo/result.json`. El replay conserva la propuesta condicional a POI_3 y queda `WAITING` por límites/autorización ausentes, sin coordenadas ejecutables ni comandos. No vuelve a llamar a Qwen.

El caso sintético separado, con fixtures y límites explícitos, atraviesa el adaptador hasta `READY_TO_SUBMIT`; el validador no declara `READY_TO_EXECUTE` y el executor es dry-run. El esquema local v2 conserva `authorization.bridge_scope_sha256`. Las fixtures no acreditan autorización física ni localización real.

## P5 — baseline Gazebo antiguo

En las refs locales/remotas visibles está `feature/ardupilot-ros2` (`7e8855f6a288dd5c5354b7201329b561da89f024`). `sim-v0.1-working` no aparece disponible, así que no se pudo verificar ese baseline solicitado. Son reutilizables para una revisión manual: `simulation/ros2_gazebo/launch/tfg_demo.launch.py`, el launch de dos drones, la cartografía `/ap/v1`, `/ap/v2`, `/ap/v3` y los documentos de versiones. `scripts/run_demo.sh` cambia GUIDED, arma y envía takeoff/land: **no reutilizar para la sesión pasiva**. La configuración de 3 vehículos fue histórica y costosa; no prueba compatibilidad con el contenedor/identidad actuales.

## P3/P6 — promoción y orden de trabajo

El paquete protegido se regenera desde la base `57a0e303afb8060db667d2273ed3a8bed262265f` e incorpora el backend/test offline y el replay histórico. SHA-256 actual: `551eb1fefebcaf31ee635472859d8dee3809755d635dd98a717919996eb3a594`; el manifiesto contiene los hashes antes/después de 24 archivos. El código sigue sin commit. Para promoción faltan revisión de lifecycle/procesos/reader pin, tests para carrera de STOP tardío y procesos ajenos, provider con helper real, successor del reader pin y decisión humana sobre la frontera del aprobador. La política sigue cerrada.

Siguiente trabajo prioritario:

1. terminar los tests de deadline/worker bloqueado y cierre tardío, sin backend real;
2. documentar el protocolo IPC del helper y endurecer la integridad/recovery del ledger de referencia;
3. regenerar/validar paquete y ejecutar una única suite offline amplia al final;
4. preparar el procedimiento de configuración manual del aprobador, sin tocar el host.

La prueba pasiva requerirá después promoción explícita, provider real, precheck actual SATISFIED, scope y autorización de sesión nuevos. Failsafe y el primer metro requieren ensayos y autorizaciones separados.

## Addendum: contrato hardening y gaps restantes

Este addendum supersede la fotografía de implementación anterior cuando difiera. El HEAD de desarrollo activo es ahora `2e206f1fa4c0c6db056adac4a3fcaaa0835e47f1`; el trabajo de runtime/tests descrito aquí sigue sin commit en el mismo worktree. El gate continúa desactivado.

- El backend fixture de autorización ahora rechaza consumo y revocación si no está expresamente en modo fixture y si la identidad no es `TEST_FIXTURE`. También rechaza un objeto `Principal(..., evidence_source="LOCAL_HELPER_PEERCRED")` construido por el llamador. No hay helper/provider productivo.
- Se añadieron tests offline para `KeyboardInterrupt`, observación bloqueada del worker, respuesta de STOP perdida después del efecto del backend y cierre de worker que llega después del STOP del supervisor. Usan dobles; no prueban terminación del proceso.
- Se eliminó la dependencia de timestamps de localización fijados al principio de un test Claude: cada adaptación crea o recibe un reloj y la localización usa ese mismo reloj. La frescura de 1 s ya no debería vencer por assertions previas lentas.
- El grupo focalizado de integración vertical, autorización local, adaptador payload/executor y contrato Claude fijado pasa **36 tests**. La suite Rover/lifecycle amplia pasa **2424 tests, 4 skips, 0 fallos** (602.90 s); después se añadió el caso aislado de transporte-helper desconocido y volvió a pasar el grupo focalizado.
- La referencia Claude de los tests actuales es el commit fijo `8fed7dc39770c70eb599c9e41d17c9ede7bb52e8`, con hashes de fuentes relevantes validados por test. No se siguió su HEAD móvil ni se modificó el worktree.
- Se encontró el tag anotado local `sim-v0.1-working`, cuyo target es `78d0d3c7030e55184120124890eb98a079c0f890`; la nota anterior de que no estaba disponible era incorrecta. El demo heredado arma y usa GUIDED, por lo que no sirve para una sesión pasiva.

La secuencia de diez fases sigue consumiendo callbacks inyectados: no están conectados proveedores runtime para READY, binding, procedencia de parámetros, captura, confirmación de cierre o inventario final. Los callbacks permiten comprobar contratos, no autenticar identidad ni acreditar telemetría actual. Esa conexión y el IPC del helper siguen pendientes de revisión/runtime. La política debe permanecer cerrada hasta completarlos. Failsafe y desplazamiento de un metro requieren ensayos y autorizaciones separados.
