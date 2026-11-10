# Paquete del rover pendiente de revisión: análisis para su revisión formal (09/11/2026, actualizado el 10/11/2026)

Documento de trabajo para revisar el paquete del rover del 07/11/2026 que la rama de integración conserva sin
promover. No es una revisión ni una aprobación: describe su estado, las incidencias que causaba y los cambios exactos
que necesitaría una revisión formal nueva. Los registros de la revisión anterior (`docs/checkpoints/2026-11-07-rover-*`)
no se modifican.

## 1. Identidad del paquete

| Elemento | Valor |
| --- | --- |
| Base | `2e206f1fa4c0c6db056adac4a3fcaaa0835e47f1` (`feature/rover-sitl-first-motion`) |
| Archivos del paquete | 27 (código, scripts y esquemas: 14; pruebas: 13) |
| Manifiesto de revisión | `docs/checkpoints/2026-11-07-rover-protected-review-current-hashes.json` (SHA-256 `de36542f…`) |
| Parche de revisión | `docs/checkpoints/2026-11-07-rover-protected-review-current.patch` (SHA-256 `8a0d8ee5…`) |
| Conservación en la rama | commit `29220de2c`, idéntico byte a byte a la copia de seguridad previa a la integración |
| Fuera del manifiesto | `tests/test_rover_mission_payload.py` (modificado, sin hash registrado), `tests/test_stop_backend_boundary.py` y `tests/test_stop_close_modes.py` (nuevas, 10/11) |

## 2. Estado en la rama de integración

- **23 de 27** archivos coinciden con el estado registrado en el manifiesto (`worktree_sha256`).
- Las 4 diferencias:
  - `simulation/ros2_gazebo/scripts/stop_sim_backend.sh`: correcciones del 10/11 (§2.1 y §2.2); no es uno de los
    lectores fijos de `present_recovery.reader_hashes()`;
  - `tools/simulation_lifecycle.py`: modos de cierre excluyentes del 10/11 (§2.2); tampoco es un lector fijo;
  - dos pruebas adaptadas durante la integración, sin cambiar sus aserciones:
  `tests/test_rover_bridge_contract.py` (antes con otro nombre; lee el puente fijado `8fed7dc39` de este repositorio y
  restaura `sys.modules`) y `tests/test_rover_payload_executor_adapter.py` (registra los módulos fijados con
  `monkeypatch`).
- Los scripts de simulación `sim_processes.py` y `start_sim_backend.sh` están en su versión de `2e206f1fa`, como
  registra el manifiesto; `stop_sim_backend.sh` parte de esa versión con las correcciones del §2.1 y el §2.2. Las
  versiones propuestas de los tres figuran solo como `proposed_after_sha256` y el checkpoint dice que quedan sin
  aplicar hasta la revisión. Se habían aplicado el 07/11 a las 17:07, después del checkpoint; la
  rama los devolvió al estado registrado en el commit `4f042518c`. Los bytes propuestos siguen en el parche de revisión
  y en `29220de2c`.

### 2.1 STOP pasivo y estados desconocidos (10/11/2026)

La auditoría independiente del 10/11 reprodujo que un cierre pasivo ordinario llegaba al lector de procesos con un
descriptor de cierre vacío y fallaba en `json.loads("")` antes de inventariar (un fallo de cierre, sin señales
indebidas). Causa: el ciclo de vida pasa la valla de arranque y los identificadores de la sesión pasiva sin
descriptor, y con los lectores fijos actuales el START no marca los procesos de la sesión, así que su propiedad no se
puede verificar.

Corrección en `stop_sim_backend.sh`, sin tocar los lectores fijos ni reaplicar la propuesta:

- un cierre pasivo se rechaza antes de cualquier llamada a Docker (código 3, `PASSIVE_STOP_OWNERSHIP_UNVERIFIABLE`);
  el ciclo de vida lo registra como no confirmado y mantiene las restricciones;
- una valla de arranque sin descriptor se rechaza igual (`CLOSE_DESCRIPTOR_MISSING`);
- un `docker inspect` fallido o con un valor inesperado es UNKNOWN (código 1), no «contenedor parado».

Pruebas: `tests/test_stop_backend_boundary.py` ejecuta el script real con un doble de Docker que registra cada llamada
(cierre pasivo, descriptor ausente, inspección fallida, contenedor parado, STOP correcto y fallido) y comprueba en el
lector fijo que un descriptor vacío se rechaza antes de inventariar y que el STOP ordinario nunca señaliza procesos
ajenos. Seis de ellas fallaban con el script anterior.

**START pasivo.** Para `rover_only`, el START pasivo sigue sin marca de sesión y hace una parada general previa. Esa
lógica está en `start_sim_backend.sh`, lector fijo: no se ha cambiado y queda como bloqueo documentado
(`PASSIVE_SCOPE_POLICY_ENABLED=False`).

### 2.2 Modos de cierre excluyentes (10/11/2026, tras la revisión de `c41b846b8`)

**Problema detectado en la revisión independiente.** El lector fijo `sim_processes.shutdown` solo usa la selección exacta de una sesión (`select_session_owned`) cuando recibe el descriptor diagnóstico **y** su arranque. Con el descriptor solo, usa la selección general del proyecto (`select_owned`).
- **STOP sin arranque.** El ciclo de vida admitía un STOP ordinario con una sesión diagnóstica abierta y pasaba el descriptor sin arranque, porque `_backend` solo añadía el arranque para los cierres de START fallido y de ensayo en tierra. El lector elegía entonces procesos de dos sesiones distintas del proyecto.
- **Caso mixto.** El script aceptaba una marca pasiva junto con un descriptor.
- **Otro perfil.** El ciclo de vida admitía el STOP de otro perfil con una sesión pasiva abierta.

**Corrección.** No toca los lectores fijos. Cada STOP se clasifica en un único modo:

| Modo | Cuándo | Qué recibe el lector |
| --- | --- | --- |
| PASIVO | `rover_only` con el propietario de la única sesión pasiva STARTED | Nada: el script lo rechaza (código 3) aunque haya también un descriptor |
| DIAGNÓSTICO | Sesión diagnóstica abierta (no `CLOSED`) | Descriptor y arranque exactos, o nada |
| ORDINARIO | Ninguna sesión protegida abierta ni incierta | Ni descriptor, ni arranque, ni marca pasiva |

- **Diagnóstico ordinario.** Solo se admite con el perfil `two_drones_rover`. Además debe cumplir dos condiciones:
  - el registro de la sesión guarda la ejecución del contenedor (identidad, inicio y arranque), que el START diagnóstico registra ahora;
  - esa ejecución sigue siendo la actual y corresponde al descriptor.

  Una sesión abierta antes de este cambio no tiene la ejecución registrada y queda bloqueada para el cierre ordinario.
- **Cierres que se rechazan antes de crear ninguna reserva:**
  - un STOP de cualquier otro modo con una sesión pasiva abierta o incierta (OPENING, STARTED, STOPPING, UNCONFIRMED);
  - un STOP pasivo con una sesión diagnóstica abierta;
  - el cierre de un START ordinario con una sesión diagnóstica abierta.
- **Registros dudosos.** Un registro de sesión pasiva o diagnóstica que sea un enlace, del tipo incorrecto o ilegible es UNKNOWN y bloquea; nunca equivale a «no hay sesión».
- **Defensa en profundidad.** Pase lo que pase, ningún descriptor sale sin su arranque:
  - `_backend` lo impide antes de lanzar el subproceso;
  - el script lo rechaza antes de llamar a Docker (`CLOSE_BOOT_MISSING`), igual que una marca pasiva parcial.

**Pruebas.**
- `tests/test_stop_close_modes.py` (30) cubre la entrada pública y el lector fijo; 18 fallaban con `c41b846b8`.
- `tests/test_stop_backend_boundary.py` añade 6 casos del script; 5 fallaban.
- Ambas comprueban que no se llega al *backend*, al subproceso ni a Docker cuando el propietario es desconocido, ambiguo o incompatible.
- `tests/test_rover_diagnostic_selection.py` declara una ejecución `TEST_FIXTURE` y comprueba que la forma anterior (descriptor sin arranque) se rechaza.

### 2.3 Criterio central de admisión del STOP (10/11/2026, tras la revisión de `cd47f2ccc`)

**Causa.** La revisión de `cd47f2ccc` reprodujo dos estados desconocidos que se leían como ausencia de sesión:
- **Registro diagnóstico nulo.** Un registro que contenía `null` daba `None` en `json.loads`, el mismo valor que representaba «no existe».
- **Registro pasivo no enumerable.** `Path.glob()` suprime el `PermissionError` al enumerar, así que el registro pasivo devolvía una lista vacía con una sesión STARTED dentro.

En ambos casos un STOP ordinario llegaba al *backend*.

**Corrección.** No toca los lectores fijos. `protected_session_state()` en `tools/simulation_lifecycle.py` es el único punto de decisión para START, STOP y RESTART, y también para el cierre de un START fallido. Solo responde si ha leído **completas** las tres fuentes:
- el registro de sesiones pasivas, con cada registro válido;
- el registro de la sesión diagnóstica;
- el tipo de cada registro de *lock* (`lifecycle`, `reconciliation`, `sequence`, `v1`–`v3`); su contenido lo sigue validando `locks.restriction`.

Cualquier otro resultado lanza `ProtectedStateUnknown` antes del *lease* y del *backend*. Un STOP ordinario solo se admite cuando esa lectura muestra que no hay ninguna sesión protegida abierta. Un STOP dirigido necesita además el propietario y la identidad compatibles (§2.2).

| Lectura | Resultado |
| --- | --- |
| `lstat` → `FileNotFoundError` (registro o registro pasivo inexistente) | AUSENTE: legítimo |
| Objeto JSON válido con su esquema, identificador y estado conocidos | VÁLIDO: decide el modo de cierre |
| Contenido `null`, lista, texto, número, booleano, `{}`, vacío o JSON inválido | INVÁLIDO → BLOQUEADO |
| Objeto incompleto (sin descriptor o estado), estado desconocido, esquema o `session_id` distintos, descriptor que no supera su comprobación | INVÁLIDO → BLOQUEADO |
| Enlace (colgante o no), directorio, FIFO u otro tipo | INVÁLIDO → BLOQUEADO (un FIFO nunca se abre) |
| Error de permisos o de E/S al hacer `lstat`, abrir, leer o enumerar (`os.scandir`, nunca `glob`) | DESCONOCIDO → BLOQUEADO |
| Registro sustituido mientras se lee (inodo o mtime distintos) o directorio que cambia mientras se enumera | DESCONOCIDO → BLOQUEADO |
| Entrada inesperada en el registro pasivo (nombre no UUID canónico, temporal de una escritura interrumpida, archivo ajeno) | DESCONOCIDO → BLOQUEADO |
| Raíz de estado o de *locks* que es un enlace o no es un directorio | DESCONOCIDO → BLOQUEADO |
| Registro de *lock* que es un enlace (colgante o no) o no es un archivo regular | DESCONOCIDO → BLOQUEADO |

**Mismo criterio en las demás lecturas del STOP:**
- en el cierre de un START fallido (`_start_close_scope`, `completed_start_close`);
- en la exploración de procesos del anfitrión (`host_role_processes`): solo un proceso que termina mientras se lee se descarta; cualquier otro error de lectura bloquea;
- en `_read_passive_session`, que usan las fases pasivas.

**Pruebas.** `tests/test_stop_protected_state.py` (82 pruebas). Cada caso rechazado comprueba:
- resultado BLOQUEADO;
- cero llamadas al *backend* y a `subprocess`;
- cero señales (`os.kill` y `os.killpg` son dobles que fallan);
- registros protegidos sin cambios, sin *lease* ni directorio de operación creados.

Los casos legítimos comprueban que el STOP ordinario sigue funcionando sin sesiones protegidas. 21 de estas pruebas fallaban con `cd47f2ccc`, entre ellas los dos contraejemplos.

## 3. Las 74 incidencias que causaba el paquete

| Grupo | Pruebas | Causa | Estado | Tipo |
| --- | --- | --- | --- | --- |
| Sucesores de disposición (`test_rover_boot_recovery_successor`, `test_rover_consumer_successor`) y revisión de versión (`test_rover_disposition_version_review`) | 73 | `present_recovery.reader_hashes()` incluye `simulation/ros2_gazebo/scripts/sim_processes.py` y `start_sim_backend.sh`. `historical_disposition` solo admite revisar los pines `historical_disposition.py` y `simulation_profiles.py` (y el lector de recursos con una transición verificada); los lectores de procesos y del *backend* quedan fijos y cualquier cambio exige una autorización exacta nueva. Con los scripts aplicados, todo sucesor queda `BLOCKED` («Incompatible successor reader versions/pins»), que es el comportamiento de seguridad previsto | Resuelto al devolver los scripts al estado registrado; con ellos sin aplicar pasan las 106 pruebas de esos tres archivos | Revisión de contrato |
| Listas de la imagen (`test_agri_scenario_flow`) | 1 | `simulation_lifecycle.py` del paquete importa `rover_passive_scope`, `rover_passive_phases`, `rover_parameter_correlation` y `rover_stationarity`; las listas generadas de las imágenes `app` y `planner` los excluían y una imagen construida no habría podido importar el ciclo de vida | Resuelto: listas regeneradas con `python -m tools.agri_scenario_distribution dockerignore` (commit `d0e2a165f`) | Actualización legítima de un artefacto generado |

## 4. Cambios que necesita una revisión formal nueva

1. **Corregir y aplicar los scripts de simulación.** La propuesta no está lista para reaplicarse tal cual:
   - en el `start_sim_backend.sh` propuesto, la comprobación de ausencia de procesos de `rover_only` va seguida de una
     parada incondicional, y los demás perfiles recibirían dos paradas;
   - en el `sim_processes.py` propuesto, `shutdown` sigue seleccionando con `select_owned` cuando no hay descriptor
     diagnóstico, y el camino pasivo hereda el análisis del descriptor vacío;
   - el STOP pasivo debe separar el cierre diagnóstico del cierre de sesión e integrar el rechazo del §2.1.

   Antes de reaplicarla hay que probar en la frontera shell–proceso, con dobles: procesos ajenos, PID reciclado,
   sesión o arranque incorrectos, inventario incompleto, *timeout* y fallo de STOP.
   Además, `sim_processes.py` y `start_sim_backend.sh` forman parte del conjunto de lectores fijos.
   La revisión debe decidir una de estas vías y registrarla:
   - cerrar antes las disposiciones históricas pendientes, de modo que ningún sucesor necesite los lectores
     antiguos; o
   - definir una transición verificada para estos lectores, análoga a la del lector de recursos
     (`_verified_resource_reader_transition`): hashes de origen y destino, motivo y autorización exacta.
   En ambos casos, tras aplicarlos, deben volver a pasar las pruebas de sucesores con la vía elegida.
2. **Lector del 04/11.** El checkpoint registra que la revisión del lector preparada el 04/11 sigue
   `PREPARED_FOR_REVIEW_NOT_AUTHORIZED_NOT_APPLIED` y que sus pines no coinciden con el paquete para `tools/rover_control.py`.
3. **Incluir en el manifiesto de la revisión nueva:**
   - `tests/test_rover_mission_payload.py`, `tests/test_stop_backend_boundary.py`, `tests/test_stop_close_modes.py` y
     `tests/test_stop_protected_state.py`;
   - las versiones corregidas de `stop_sim_backend.sh` y `simulation_lifecycle.py`.
4. **Nomenclatura dentro del paquete.** Dos textos de archivos del paquete conservan el nombre de una herramienta de
   desarrollo. No se han cambiado porque alterarían los hashes que la revisión debe aprobar:

   | Archivo | Texto actual | Propuesta |
   | --- | --- | --- |
   | `schemas/rover-mission-execution-v2.schema.json` (línea 366, `description`) | «… binds a human receipt to both bridge and C… plans.» | «… binds a human receipt to both the bridge plan and the rover plan.» |
   | `tools/rover_payload_executor_adapter.py` (línea 3, docstring) | «C… applies the site-to-navigation transform once, …» | «The rover adapter applies the site-to-navigation transform once, …» |

   El cambio del esquema es solo de `description` y no altera la validación.
5. **Manifiesto nuevo.** Tras los cambios anteriores, un manifiesto y un parche nuevos, con su propia fecha, en lugar
   de reescribir los del 07/11.

## 5. Comprobaciones para la revisión

- Suite offline completa de la rama (con los datos locales ignorados por Git disponibles).
- Pruebas de sucesores, de revisión de versión, del ámbito pasivo y de integración vertical del paquete.
- `python -m tools.agri_scenario_distribution dockerignore --set app_image --check deploy/app/Dockerfile.dockerignore`
  y lo mismo con `planner_image`.
- La batería de traspaso contra el código del rover integrado: `python -m multiagent.demo --battery` (18/18, cero
  comandos).
