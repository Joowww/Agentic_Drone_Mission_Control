# Rover: seguimiento offline de SIGALRM y validación — 06/11/2026

## Alcance

Esta continuación fue offline. No se inició START, SITL ni Gazebo; no se abrió MAVLink, no se enviaron controles, no se modificaron parámetros, reservas, políticas ni flags. No se modificó el worktree de Claude. El precheck y cualquier resultado histórico de otra hora no se trataron como autorización de START.

Rama `feature/rover-sitl-first-motion`; base observada `b6d07388a`. La integración de un scope pasivo ordinario sigue bloqueada para cambios en el sistema productivo: `simulation_lifecycle start` crea un lease `SIMULATION_INFRASTRUCTURE_ONLY` y no consume scope/hash/autorización externa de sesión; `rover_ground_executor` admite actualmente contratos operativos de movimiento/control, no una sesión PASSIVE. El generador separado sería una autorización paralela y no se creó. No se produjo scope ni hash, ni se ejecutó precheck nuevo en esta continuación. La futura extensión debe diseñarse y revisarse en la ruta oficial protegida antes de usarse.

## SIGALRM

La suite anterior produjo `PytestUnraisableExceptionWarning`: `SIGALRM` lanzó `TimeoutError` mientras corría el callback débil `weakref.WeakSet._remove`. Python convirtió esa excepción del callback en una excepción no capturada. Esto podía consumir la señal sin entregarla al ámbito del deadline. Las pruebas del `NativeRos2Session._exchange` también verifican cancelación local del future; ese mecanismo de limpieza debe seguir ejecutándose.

Se cambió `tools/rover_control.py::synchronous_deadline`: cuando el frame interrumpido pertenece a un callback weakref (identificado por una referencia weakref entre sus locales), el handler difiere la excepción hasta salir del ámbito `with`; en los demás frames sigue interrumpiendo con `TimeoutError` de inmediato. Se conserva el timer anterior y el rechazo de un timer no administrado. Una regresión crea un callback weakref que permanece ocupado al expirar el timer y comprueba que el error llega al llamador sin invocar `sys.unraisablehook`.

El diseño cooperativo inicial (solo marcar el vencimiento hasta el retorno de cualquier llamada) se descartó: permitió que algunas llamadas ROS y cierres simulados excedieran su presupuesto. La versión final retiene la interrupción inmediata para esos casos. Una operación que bloquee dentro de un callback weakref no puede interrumpirse sin volver a lanzar dentro del callback; el timeout se propaga al salir de ese callback. El backend debe conservar sus límites nativos y el cierre se mantiene fail-closed si no queda confirmado.

La edición de `rover_control.py` cambia un pin fuente incluido en el lector XRCE histórico. No se modificó el manifiesto ni sus evidencias selladas. El dry run del lector detecta el digest fuente distinto y bloquea la selección. Se ajustó el test local para comparar todos los `source_hashes` del lector preparado, de modo que un lector antiguo no se trate como vigente después de cambiar una fuente.

## Validación

- Casos dirigidos de weakref, cancelación, llamada bloqueada, cierre con deadline, timeout de pipe y dry-run de fuentes: **11 passed**.
- Módulos de control, adaptador ROS, executor, lifecycle e inventario: **168 passed**.
- Suite completa `tests/test_rover_*.py`: **2211 passed, 4 skipped, 0 warnings**, 457,75 s.
- Los 4 skips siguen siendo los casos documentados de fallo de cierre protegido.
- No hubo validación real ni prueba de rover; los resultados anteriores son offline/sintéticos.

## Contrato de Claude

El bridge consultado fue el commit `fd8f3999b` del worktree separado; en el momento de la lectura ese worktree mostraba cambios locales sin commit, que no se consultaron ni modificaron. El bridge expresa `task_id`, `proposal_sha256`, `target.point_id`, `NavigationPlan`, scope de autorización y estado; el payload Codex `/1` exige identidad/digest de misión, plataforma, objetivo en coordenadas, localización acreditada con procedencia, ventana de validez, executor y condiciones de parada. El bridge no aporta por sí solo toda la localización/procedencia que requiere el payload Codex. `tools/rover_mission_payload.py` nunca envía comandos, las tareas condicionales quedan `WAITING`, y el adapter JetRacer mantiene `REFUSED_DRY_RUN_ONLY`. No se cambió el worktree multiagente ni se generó autorización.

## Pendiente

1. Preparar la extensión de la ruta oficial lifecycle/executor para aceptar un scope pasivo exacto, de uso único y vinculado al precheck actual; someter ese cambio a revisión protegida antes de aplicarlo. Hasta entonces no generar un supuesto scope oficial ni abrir sesión.
2. Alinear el contrato Claude/Codex en un adaptador/schema revisable que conserve procedencia de localización, frescura y autorización humana; ningún resultado del agente debe convertirse en comando.
3. Mantener la instrumentación actual de estacionariedad y MAVLink en modo solo lectura/inyección. `PARAM_VALUE` no lleva request ID, por lo que la correlación se informa como evidencia cruzada limitada, nunca como relación perfecta.
4. Mantener los analizadores de failsafe y primer metro como herramientas offline; ninguna fixture acredita frenado o movimiento real.
5. Tras resolver el scope oficial, ejecutar un precheck fresco, volver a verificar exclusividad/identidades/recursos y pedir autorización separada antes de START.
