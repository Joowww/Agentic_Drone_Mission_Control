# Rover: integración offline de scope pasivo con lifecycle — 06/11/2026

## Resultado y límites

Se preparó un parche offline que conecta un scope pasivo versionado con el consumidor oficial `tools.simulation_lifecycle.run_lifecycle`. No se ejecutó START, STOP, SITL, Gazebo, worker, MotionBinding, MAVLink ni controles. No se activó la compuerta de política. No hubo cambios en reservas, auditoría o flags; el worktree de Claude no se tocó.

La integración **no está promovida ni permite todavía validar el rover**: `PASSIVE_SCOPE_POLICY_ENABLED` sigue siendo `False`. El cambio de `simulation_lifecycle.py` es protegido. Requiere revisión/promoción por el mecanismo del repositorio antes de que el START rover_only pueda admitirlo. El precheck `SATISFIED` observado previamente a las 20:27:31 UTC es temporal, ya venció para preparar cualquier scope o sesión y no se reutiliza aquí. La auditoría histórica continúa `DISPOSED_DIAGNOSTICALLY_INCOMPLETE`; esta integración no la modifica.

## Contrato preparado

`tools/rover_passive_scope.py` construye `tfg.rover.passive-session-scope/1`, calcula SHA-256 de JSON canónico, fija `rover_only`, rover `rover_01/v3`, host boot, identidad/boot del contenedor, recursos, condiciones del precheck, protocolo MotionBinding `/2`, parámetros read-only, worker PASSIVE de 100 observaciones, condiciones de aborto/cierre y operaciones prohibidas. El schema está en `schemas/rover-passive-session-v1.schema.json`.

El consumidor START, bajo los locks `v1.execution.lock` y `registry.lock`, vuelve a ejecutar el precheck protegido y contrasta frescura, condiciones, boot, identidad de contenedor, perfil, vehículo, recursos, operaciones exactas, hash y declaración. Una declaración de formato exacto no equivale a identidad autenticada: el contrato lo marca `OPERATOR_DECLARED_NOT_AUTHENTICATED`. El mecanismo vigente no aporta firma, identidad fuerte del operador ni consulta de revocación. Por eso la compuerta permanece cerrada para revisión.

El claim se crea con `O_CREAT|O_EXCL`, se escribe y sincroniza antes de efectos del backend. Una colisión, persistencia incompleta o respuesta incierta bloquea el replay. El START asigna el UUID del scope al owner del lifecycle y registra scope/claim en estado OPENING, STARTED o UNCONFIRMED. No se admite `restart`. STOP exige el único owner activo exacto, estado STARTED, misma identidad de ejecución y boot; el backend limita cierre a procesos con marca de sesión y conserva bloqueos cuando hay procesos extranjeros/ambiguos. Después comprueba inventario y precheck final. El gate estático impide la ruta productiva hasta revisión.

## Límite funcional pendiente

El scope describe las fases posteriores, pero todavía no existe consumidor que haga cumplir su secuencia para MotionBinding, lectura de parámetros y worker PASSIVE/100 ni que vincule sus recibos al estado de sesión STARTED. Tampoco se implementó un límite de duración de sesión ejecutado en runtime. La integración de lifecycle no ejecuta esos pasos y sus tests usan dobles. No debe afirmarse que el scope completo ya habilita o instrumenta la captura real. El cierre protegido y el estado UNCONFIRMED sí están conectados al mismo owner.

La cadena de autorización actual es una declaración textual comparable con el hash, sin autenticación o revocación independiente. Antes de promover se debe revisar si el contrato protegido acepta explícitamente esa forma de autorización; si no, debe conectarse el mecanismo autenticado existente o mantenerse el gate cerrado. No se debe resolver activando el booleano por conveniencia.

## Cambios y pruebas

Archivos activos del borrador: `tools/rover_passive_scope.py` y `tools/simulation_lifecycle.py`, además del schema y tests sintéticos. El cambio preparado en `sim_processes.py` y los scripts de backend está separado en [el parche de revisión](2026-11-06-rover-passive-process-integration-review.patch), porque modificar esos fuentes altera los reader pins históricos. Se añadieron pruebas de builder/hash, scope alterado, precheck fresco/BLOCKED/caducado, identidad/boot, operación de movimiento, claim de uso único, fallo de persistencia, concurrencia, START incierto, STOP con owner equivocado e inventario final incompleto. El parche de procesos aún requiere tests unitarios propios al revisarse/promoverse.

La suite offline amplia final (`tests/test_rover_*.py` y pruebas lifecycle/perfiles/mission executor) pasó: **2317 passed, 4 skipped** en 555,44 s. Los cuatro skips documentan el cierre protegido tras START fallido. La suite amplia ejecutada antes de restaurar los fuentes pinned falló **45 tests y 28 setups** por hashes incompatibles en `sim_processes.py` y `start_sim_backend.sh`, además de la prueba de revisión de pins; esos cambios se retiraron del árbol activo y se conservaron en el parche de revisión. Los 178 tests se volvieron a ejecutar con los pins restaurados y todos pasaron. Falta ejecutar el validador estructural del schema recién añadido; la suite Python amplia, compilación Python y parseo JSON/shell ya están comprobados. La corrección SIGALRM conserva la suite previa de `tests/test_rover_*.py`: 2211 passed, 4 skipped, 0 warnings, antes de esta integración.

Los resultados de `tools/rover_stationarity.py` y la correlación MAVLink siguen siendo analizadores de evidencia. Umbrales actuales: 100 muestras mínimas, cobertura ≥30 s, frescura ≤1 s, huecos ≤2 s, desplazamiento ≤5 cm, deriva ≤10 cm, velocidades ≤0,03, cambio de orientación/yaw ≤0,02 y cero comandos. `PARAM_VALUE` no incluye ID de solicitud: la correlación ROS/MAVLink se puede acreditar solo con las demás identidades/procedencias y no como respuesta inequívoca por request. No se abrió transporte real.

## Revisión protegida necesaria

1. Revisar el diff de `simulation_lifecycle.py`, su nuevo schema, claims, estado de sesión y el backend de proceso. Confirmar el punto de política que permite el scope de infraestructura y la forma aceptada de identidad/autorización del operador.
2. Resolver autenticación y revocación; definir cómo se aplica el máximo de 300 s y cómo se vinculan recibos del binding, parámetros y worker al mismo owner.
3. Mantener `PASSIVE_SCOPE_POLICY_ENABLED=False` hasta que la revisión protegida promueva expresamente el contrato. No cambiar el pin ni sustituir hashes históricos sin sucesión/versionado.
4. Después de la promoción, ejecutar una suite offline final y verificar schema/pins. Solo entonces se puede generar un scope nuevo desde un precheck actual y presentarlo para autorización humana separada. La promoción no autoriza START.
5. Con autorización específica posterior, exigir un precheck protegido fresco inmediatamente antes de START y detenerse ante cualquier diferencia o incertidumbre. Nunca reutilizar scope o autorización vencidos.

## Estado Git al preparar este checkpoint

Rama `feature/rover-sitl-first-motion`, HEAD base `b6d07388a`; el trabajo de SIGALRM y el parche de scope siguen locales y sin commit. No se hizo push ni merge.