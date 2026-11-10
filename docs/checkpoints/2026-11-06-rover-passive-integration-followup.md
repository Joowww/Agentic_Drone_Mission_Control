# Rover: cierre vertical offline de sesion pasiva - 06-07/11/2026

## Alcance y resultado

Trabajo local en `feature/rover-sitl-first-motion`, base `1514053da`. No se ejecuto precheck operativo, START, STOP operativo, SITL, Gazebo, ROS, MAVLink ni controles del vehiculo. No se cambio el worktree multiagente de Claude. No se alteraron auditorias selladas, reservas, leases ni flags del entorno. `PASSIVE_SCOPE_POLICY_ENABLED` sigue en `False`.

Se conecto una prueba sintetica al codigo de `tools/simulation_lifecycle.py`: builder y hash del scope, autoridad fixture, START protegido con dobles, fases y recibos, worker PASSIVE inyectado, captura de 100 registros sinteticos, analisis de estacionariedad, cierre del worker, STOP por la ruta protegida e inventario/precheck final simulados. La prueba no abre procesos ni transportes. El resultado positivo cierra como `CLOSED`, con las diez fases, 100 observaciones y movimiento desautorizado.

## Secuencia y controles probados

- La secuencia es `START`, `READY_ARMABLE`, `MOTION_BINDING_V2`, `PARAMETERS_READ`, `WORKER_OPEN`, `OBSERVATIONS`, `OBSERVATIONS_VALIDATED`, `WORKER_CLOSE`, `STOP`, `FINAL_INVENTORY`.
- Los recibos se guardan en el estado durable de la misma sesion/lifecycle y llevan owner, scope hash, lifecycle, host/container identity, vehiculo, hora monotona, estado, evidencia hash y hash del recibo anterior.
- START y STOP siguen pasando por `run_lifecycle`; STOP es mismo owner y no se repite tras resultado incierto.
- La reserva atomica del slot de worker precede al spawn API; el token es de un solo uso y comprueba owner, boot y container. El API de `open_passive_session` consume el token antes de crear el proceso. El gate impide START operativo mientras no se revise/promueva.
- La captura se vuelve a hashear y se exige que contenga exactamente 100 observaciones. El analizador existente vuelve a comprobar GID, edad, cobertura, estacionariedad y movimiento antes de acreditar el cierre.
- Los parametros requeridos deben aparecer en ROS y MAVLink y coincidir; el recuento de escrituras debe ser cero.
- Variantes sinteticas rechazan autorizacion revocada, vehiculo distinto, worker duplicado, fase fuera de orden, parametros incompletos, GID incorrecto, odometria caducada, deriva y captura de menos de 100.
- El supervisor usa reloj monotono del host. Solicita STOP por el lifecycle en un hilo separado antes del limite, espera como maximo `PASSIVE_STOP_CONFIRMATION_WAIT_S=15` (ajustable en pruebas), y conserva `UNCONFIRMED` si no recibe respuesta. No reintenta ni mata procesos. El timeout total de 300 s impide nuevas fases y dispara esa solicitud.

## Confianza y limites

No se encontro una identidad autenticada del operador ni un proveedor confiable de revocacion para este flujo. `operator_id` y la declaracion textual son claims, no prueba de identidad o consentimiento. `OfflineFixtureAuthority` prueba ACTIVE/REVOKED y vinculacion a vehiculo solo en el test. No esta conectado como autoridad runtime ni puede abrir la compuerta operativa. La forma de autorizacion operativa sigue pendiente de decision/revision protegida.

STOP ejecutado desde otro hilo permite al coordinador dejar de esperar un callback opaco; no garantiza que backend, proceso o simulacion terminen dentro de 15 s. Si la llamada termina tarde, su estado inicial comunicado es incierto. Un bloqueo de locks puede impedir la solicitud. La muerte del host elimina este supervisor in-process. No hay garantia de parada fisica inmediata. Ante una respuesta desconocida no se reintenta; lifecycle/lease conserva el bloqueo para diagnostico protegido.

Los tests usan dobles y datos sinteticos; no acreditan comportamiento real de ArduPilot, XRCE, MAVLink, Gazebo o rover. No hay medicion real, precheck actual, scope operativo ni autorizacion de sesion.

## SIGALRM, pins y parche de procesos

El cambio local de `tools/rover_control.py` sigue requiriendo revision: su SHA-256 activo es `5bb1238ee0f6e9b80f08e6bbdcb2f8e9484fd119d69b07cdbfd1022083cf3682`. Las pruebas de timeout son de callbacks finitos; Python no puede interrumpir con seguridad un callback nativo arbitrariamente bloqueado. No se deben cambiar los pins historicos como atajo.

El parche protegido `docs/checkpoints/2026-11-06-rover-passive-process-integration-review.patch` conserva SHA-256 `f54138c3222ccbcfbd4843ff9f5c9037c2ea35aad56454138cc961dfa13eed79` y afecta `sim_processes.py`, `start_sim_backend.sh` y `stop_sim_backend.sh`. No esta aplicado. Cualquier sucesion debe incluir seleccion historica/reader, snapshot de fuentes y pruebas de instalacion, START, STOP, rollback y compatibilidad. El pin de `rover_control.py` tambien necesita una sucesion formal coordinada. No editar los manifests sellados.

## Revision protegida necesaria

Preparar una unica revision con: diff protegido de lifecycle y sesion/worker, schema y tests; decision explicita sobre principal autenticado y revocacion; sucesion de reader/pin de `rover_control.py`; y, si el procedimiento admite su promocion, el parche de procesos con pruebas propias. Mantener `PASSIVE_SCOPE_POLICY_ENABLED=False` hasta que el mecanismo de revision registre decision y promocion. No usar commit local como sustituto de la revision.

Despues de revision/promocion, una validacion real aun necesita un precheck protegido actual SATISFIED, scope nuevo calculado desde ese estado, autorizacion humana especifica para el hash exacto, y un precheck fresco inmediatamente antes del START. Esta tarea no solicita esa autorizacion ni permite START.

## Git y validacion

Base conocida: `1514053da`; rama `feature/rover-sitl-first-motion`. Se conservaron todos los cambios locales existentes; no se hizo reset, clean, stash, push, merge ni commit. Los cambios protegidos permanecen locales para revision.

Suite offline amplia: `tests/test_rover*.py` y lifecycle/perfiles/mission-executor relacionados: 2390 passed, 4 skipped y 7 fallos iniciales en cierres ordinarios UNCONFIRMED de rover_only. El fallo fue una condicion de admision STOP que capturaba cierres con owner ordinario. Se acoto la condicion y el rerun de las suites de lifecycle/start-close y scope pasivo dio 111 passed. No se repitio toda la suite amplia despues de ese cambio acotado.

Integracion vertical: 8 passed. Manifestos `SHA256SUMS` de `evaluation/operations` y `simulation/ros2_gazebo/results`: 112840 entradas, 0 discrepancias y 0 faltantes. JSON Schema valido. `git apply --check` paso para el parche de procesos sin aplicarlo. `git diff --check` y `py_compile` de los modulos cambiados pasaron. El hash del parche protegido y el hash actual de `rover_control.py` se verificaron arriba. No modificar evidencias selladas.
