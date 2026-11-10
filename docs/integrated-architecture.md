# Arquitectura integrada del TFG (rama de integración, 09/11/2026, revisada el 10/11/2026)

Estado de la versión unificada que reúne en un solo repositorio la planificación con Hermes y MCP, la validación
determinista con LangGraph, el sistema multiagente, el subsistema rover, la simulación y la observabilidad. Cada
elemento se clasifica por lo que está **probado**, no por lo que está implementado.

Nada de este documento autoriza vuelos, movimiento del rover ni arranques del simulador. Las pruebas offline acreditan
el comportamiento del código con dobles y datos de prueba; **no son una validación operativa**. Los resultados
históricos describen su fecha y no sustituyen una comprobación actual.

## 1. Cadenas de la integración

No hay una cadena automática que vaya de Hermes a un vehículo. Son cuatro cadenas que comparten contratos y datos, y
cada paso entre ellas lo inicia una persona o una orden explícita:

```text
A. Planificación conversacional (Hermes)
   intención del operador -> Hermes Agent + LLM (Ollama local o remoto) -> herramientas MCP de planificación
   (tools/hermes_mcp_server.py; perfil de demo: tools/hermes_demo_planning_server.py)
   -> MissionPlanDraft -> MissionDefinition -> validación determinista (LangGraph waypoint_mission_graph)
   -> finalización y exportación QGC estricta.                       Termina en un archivo, sin vuelo.

B. Supervisión multiagente (LangGraph, multiagent/orchestrator.py)
   entrada (escenario, .plan de QGC importado o misión estructurada)
   -> interpret -> screen -> decompose -> drone_agent / rover_agent -> assemble -> finalize
   -> propuesta PROPOSED_PENDING_AUTHORIZATION.                       No llama a Hermes ni a ningún vehículo.
   La demo de dos drones valida cada misión con el código determinista de Hermes (sin LLM) y se detiene en una
   petición H2 sin efectos.

C. Traspaso al rover (multiagent/rover_handoff.py, código del rover importado del propio repositorio)
   petición de ejecución -> contrato v2 (tools/rover_mission_payload.py, tools/rover_agent_adapter.py)
   -> adaptador final payload -> ejecutor (tools/rover_payload_executor_adapter.py), propietario único de la
      conversión de coordenadas -> admisión del ejecutor (tools/rover_ground_executor.py), política desactivada.
                                                                      Termina BLOCKED, cero comandos.

D. Ciclo de vida de la simulación (tools/simulation_lifecycle.py, simulation/ros2_gazebo/)
   Solo con autorización explícita y por su propia entrada. Ninguna de las cadenas A-C lo invoca.

Observabilidad local y exportación Opik en dry-run (observability/*, multiagent/tracing.py) a lo largo de A-C.
```

## 2. Matriz de alcance (10/11/2026)

### 2.1 Integrado y probado offline

| Conexión | Cómo se prueba | Resultado |
| --- | --- | --- |
| Cadena A: Hermes -> MCP -> MissionDefinition -> LangGraph -> finalización y QGC | Pruebas de `tools/hermes_*`, `planning/*` y del servidor de demo | Superadas. Un piloto real con Ollama local del 08/11 (`evaluation/observability/hermes_ollama_local_pilot_2026_11_08_r02`) es un caso histórico, no una tasa de fiabilidad |
| Entrada `.plan` de QGroundControl | `multiagent.demo --input-plan`, importador Hermes, `tools.qgc_plan_compare`, `tools.scenario_package` | Superadas; una tarea condicional del rover no se deduce de un `.plan` |
| Cadena B con agentes de drones y rover | Pruebas `test_multiagent_*` (escenarios, enjambre, coordinador, agenda, separación) | Superadas; agentes deterministas o respuestas grabadas de Qwen |
| **Cadena C por el adaptador final** (`ROVER_ADAPTER`) | `tests/test_rover_final_adapter_handoff.py` (24 pruebas) y `python -m multiagent.demo --scenario red_target --rover-handoff` | El adaptador final recibe el payload v2 exacto que produce el adaptador del rover, aplica la conversión una sola vez y construye la petición con los límites del plan aprobado; la admisión queda `BLOCKED` (`OPERATIONAL_ROVER_POLICY_DISABLED`), cero comandos |
| Cadena C por la ruta de prueba offline (`MULTIAGENT_FRAMES2D`) | `python -m multiagent.demo --battery` | 18/18 misiones como se esperaba, cero comandos. Esta ruta se rechaza en modo operativo |
| Inmutabilidad de los límites del operador | Pruebas del adaptador final y de la ruta offline | Ningún parámetro del ejecutor puede cambiar velocidad, duración, *timeout* ni destino del plan; los contradictorios, incompletos o malformados se rechazan antes de la petición |
| Observabilidad local y Opik | Pruebas de captura, `capture_summary`, `opik_export` (dry-run), trazas multiagente | Superadas; ningún envío |
| Integridad de evidencias | 238 manifiestos `SHA256SUMS` y comparación con las ramas de origen | Sin cambios |

Las correcciones de la auditoría del 10/11, también probadas offline:

- Modos de cierre excluyentes del STOP y estados desconocidos (§2.4).
- Métricas de simulación ligadas a la ejecución y al ciclo de vida exactos.
- Comprobación previa de pilotos que falla en cerrado (§2.5).

### 2.2 Funciones de simulación disponibles pero no verificadas en esta rama

- **Perfiles del ciclo de vida.**
  - Los perfiles `two_drones`, `two_drones_rover` y `rover_only` existen en `tools/simulation_profiles.py`, con sus *launch* (`tfg_demo.launch.py`, `tfg_demo_2drones.launch.py`, `tfg_rover_only.launch.py`) y las entradas START, CHECK y STOP.
  - En esta rama solo se han probado con dobles y comprobaciones estáticas de sintaxis. No se ha arrancado Gazebo, SITL ni XRCE.
- **Evidencias históricas de simulación.** Las de `simulation/ros2_gazebo/results/` (dos drones con GUI el 25/10, rover solo el 03/11, capturas autorizadas del rover del 28/10 y el 30/10) acreditan sesiones de esas fechas y configuraciones. No validan este HEAD.
- **Procedimiento SITL de dos drones.** Está preparado y **no se ha ejecutado** ([two-drone-sitl-procedure-2026-11-07.md](two-drone-sitl-procedure-2026-11-07.md)).
- **Escenario unificado** (dos drones y rover en el mismo SITL). No se ha ejecutado nunca.
- **Rama `feature/ardupilot-ros2`.** No es antecesora de esta rama. Sus *launch* y scripts tienen sucesores con ciclo de vida y guardas, pero eso es conservación funcional estática, no equivalencia operativa.

### 2.3 Pendiente de probar con Gazebo, SITL, drones y rover

- **Arranque y parada de cada perfil.** Por `simulation_lifecycle` con autorización, comprobando el inventario de procesos antes y después.
- **Dos drones en SITL.** Ejecución de misiones validadas por Hermes, con la agenda y la separación de la cadena B.
- **Rover en SITL.**
  - Petición del adaptador final contra el ejecutor real.
  - Proveedor de localización con evidencia actual (no `TEST_FIXTURE`).
  - Cadencia medida con las métricas ligadas a la ejecución.
  - Cierre con efectos inciertos.
- **Sesión pasiva del rover.** START y STOP con propiedad verificable de los procesos (§2.4).
- **Escenario unificado.** Dependencias aire -> tierra con eventos reales.
- **Cada prueba se hace en una sesión autorizada aparte**, con su propia evidencia en un directorio nuevo.

### 2.4 Políticas operativas cerradas

| Política | Archivo | Valor | Qué impide |
| --- | --- | --- | --- |
| `PASSIVE_SCOPE_POLICY_ENABLED` | `tools/simulation_lifecycle.py` | `False` | Sesiones pasivas del rover por el ciclo de vida |
| `SITL_TRIAL_POLICY_ENABLED` | `tools/rover_sitl_trial_policy.py` | `False` | Ensayos del rover en SITL |
| `OPERATIONAL_ROVER_ENABLED` | `tools/rover_ground_executor.py` | `False` | Admisión de cualquier petición del rover |

Además, la ruta de traspaso local rechaza:
- habilitar cualquiera de esas políticas;
- una declaración `sitl_trial`;
- el modo `OPERATIONAL` del adaptador final.

Habilitarlas exige una revisión separada.

**Cierres de la simulación (estado tras las correcciones del 10/11).**
- **Criterio central.** `protected_session_state()` lee completas todas las fuentes de sesiones protegidas antes de cualquier *lease*. Un registro ausente solo cuenta como ausente cuando `lstat` lo demuestra. Un contenido nulo o inválido, un enlace, un tipo inesperado, un error de lectura o de enumeración, o un cambio durante la lectura bloquean (matriz completa en [rover-package-review-2026-11-09.md](rover-package-review-2026-11-09.md) §2.3).
- **Tres modos excluyentes.** Cada STOP es PASIVO, DIAGNÓSTICO u ORDINARIO, y el ciclo de vida rechaza antes de crear ninguna reserva cualquier STOP cuyo propietario sea desconocido, ambiguo o incompatible:
  - de otro perfil o de otro propietario con una sesión pasiva abierta o incierta;
  - pasivo con una sesión diagnóstica abierta;
  - diagnóstico sin el perfil de la sesión o sin su ejecución registrada y actual.
- **STOP pasivo.**
  - Con los lectores fijos actuales, el START no marca los procesos de una sesión pasiva, así que su propiedad no se puede verificar.
  - `stop_sim_backend.sh` rechaza cualquier marca pasiva antes de inspeccionar o señalizar nada (código 3, `PASSIVE_STOP_OWNERSHIP_UNVERIFIABLE`), aunque llegue con un descriptor diagnóstico. El ciclo de vida lo registra como no confirmado y mantiene las restricciones.
- **STOP diagnóstico.**
  - Siempre lleva el descriptor y el arranque exactos, de modo que el lector fijo selecciona solo esa sesión.
  - Un descriptor sin arranque, o un arranque sin descriptor, se rechaza en `_backend` y en el script, antes de Docker.
- **Estado ilegible.**
  - Si el estado del contenedor o la ejecución no se pueden leer, el resultado es UNKNOWN y no «parado».
  - Un registro de sesión que sea un enlace o esté dañado bloquea.
- **START.**
  - Para `rover_only`, el START pasivo sigue sin marca de sesión y hace una parada general previa.
  - Esa limitación está en el lector fijo `start_sim_backend.sh`. Su corrección requiere la revisión formal descrita en [rover-package-review-2026-11-09.md](rover-package-review-2026-11-09.md); la política sigue desactivada.

### 2.5 Limitaciones que impiden hoy una ejecución física segura

- **Sin proveedores operativos.** No hay proveedor operativo de localización, dependencias, autorización humana autenticada ni telemetría. Límites, autorización, transformación, localización, identidad de ejecución y estado de parada son `TEST_FIXTURE`. El proveedor local de autorización es un *backend* de prueba y rechaza el uso de producción.
- **Sin adaptador físico.** No existe adaptador físico del ejecutor; el *dry-run* lo rechaza.
- **Sesión pasiva sin aislamiento.** El aislamiento de una sesión pasiva no está demostrado (§2.4).
- **Finalización de Hermes sin autorización de turno.** El servidor de demo de Hermes envía la finalización al *backend* sin una autorización de turno verificable. La finalización guiada no forma parte de la promesa de seguridad: la suite no acredita esa garantía conversacional.
- **Garantía de exclusión de los pilotos.**
  - Desde el 10/11, un proceso o contenedor que no se puede inspeccionar es UNKNOWN y bloquea.
  - Las reservas se leen de todos los *worktrees* del repositorio. Cada raíz de *locks* se comprueba componente a componente sin seguir enlaces: un enlace (colgante o no), un tipo inesperado, un error de lectura, un componente versionado ausente o un cambio entre la verificación y la lectura dan UNKNOWN; solo la ausencia de `generated` o `vehicle_locks`, que se crean al usarse, es una ausencia legítima.
  - Sin embargo, la comprobación es pasiva y se hace en un instante concreto: no reserva recursos.
- **Fiabilidad del modelo sin medir.** Un único piloto real de Hermes con modelo local; las pruebas en verde no miden la fiabilidad del modelo.
- **Ni hardware ni percepción real.** No hay integración con sensores, posicionamiento, percepción real ni vehículos físicos. La exportación QGC exige la altitud AMSL real del punto de inicio.

## 3. Prototipos offline

- **Percepción agrícola.** Detector sintético y comparación con OpenCV; no hay cámara real.
- **Agentes con LLM real.** Pilotos grabados (M1–M4c-r1); la demo los reproduce sin llamar al modelo.
- **Demo de dos drones.** Planificación, validación Hermes, petición H2 y traspaso al rover, sin efectos; la observación de cámara es sintética.

## 4. Pendiente de conectar o de revisar

| Elemento | Qué falta |
| --- | --- |
| Paquete del rover del 07/11 (autorización local, ámbito pasivo, adaptador payload->ejecutor) | Revisión humana. Análisis y cambios: [rover-package-review-2026-11-09.md](rover-package-review-2026-11-09.md). El adaptador final ya se usa en la cadena C con la política cerrada; sus archivos no se han modificado |
| Ejecución del rover | Las políticas del §2.4 y los proveedores del §2.5 |
| Hermes en contenedor con Ollama local | La imagen `deploy/planner` sigue configurada para el proveedor remoto y requiere el paquete Hermes fijado |
| Perfil local de Hermes | `~/.hermes/profiles/tfg-demo-local` se regenera con `observability.local_planning_demo prepare-profile` desde el *checkout*; la instalación desde un HOME vacío no tiene todavía un procedimiento verificado |

## 5. Ruta local del rover frente a reproducción histórica

**Uso normal: código local.** El traspaso multiagente -> rover importa en proceso el código del rover de este mismo repositorio (`rover_handoff.rover_contract()` sin argumentos). No usa ningún snapshot.

**Reproducción histórica: snapshots.** Los snapshots solo sirven para reproducir las evidencias selladas generadas contra revisiones fijadas. Funciones y revisiones:
- `ensure_snapshot`;
- revisión `committed` = `57a0e303a`;
- revisión `reviewed` = `2e206f1fa` + parche `551eb1fe`.

En esas revisiones la ruta `ROVER_ADAPTER` termina en `V2_READY_AWAITING_ROVER_ADAPTER`, como registran sus evidencias. Necesitan los objetos Git de esas revisiones. Los identificadores que solo existen en ellas están en `multiagent/historical_identifiers.py`.

### 5.1 Historial de desarrollo y revisiones fijadas

`main` consolida la integración en un único commit. El historial de desarrollo completo, sin reescribir, se conserva
en la etiqueta anotada local `archive/integration-history-2026-11-10` (no publicada) y en el bundle posterior a la
consolidación (`/home/joelm/TFG/backups/`).

**Revisiones fijadas.** Son accesibles a través de esa etiqueta:

| Revisión | Para qué se usa |
| --- | --- |
| `57a0e303a` | Snapshot `committed` |
| `2e206f1fa` | Snapshot `reviewed` y su parche |
| `1514053da` | Contrato v2 |
| `f2fd78ae1` | Contrato v1 |
| `8fed7dc39` | Puente fijado |
| `ac92b087f` | Registro del manifiesto del piloto M4c-r1 |

**Qué necesita la etiqueta.**
- **Funciones:**
  - snapshots históricos del rover (`--rover-snapshot`, `--rover-reviewed`, `integration_battery --snapshot`);
  - `demo --replay` de M4c-r1 y la regeneración de su registro;
  - pruebas de contrato contra las revisiones fijadas;
  - reproducción exacta de evidencias selladas.
- **Sin la etiqueta** (un clon solo de `main`):
  - esas funciones se rechazan de forma explícita: `REFUSED_UNVERIFIED`, o error de Git por objeto ausente;
  - sus pruebas se omiten con el motivo (`tests/history_requirements.py`);
  - el resto funciona igual.
- **Para recuperarla en otro clon:** obtener la referencia de archivo del repositorio local o restaurarla desde el
  bundle.

## 6. Pruebas de la integración

Suite offline completa: `.venv/bin/python -m pytest -q -p no:cacheprovider -m "not llm"`.
- Se ejecuta desde la raíz del *checkout*.
- Usa los datos locales ignorados por Git descritos en §6.1.

| Estado | Aprobadas | Fallidas | Errores | Omitidas |
| --- | --- | --- | --- | --- |
| Rover + paquete del 07/11 (línea base) | 3 929 | 46 | 51 | 4 |
| Tras el merge multiagente | 4 988 | 48 | 51 | 6 |
| Tras resolver las incidencias heredadas (09/11, noche, `8f2e47783`) | 5 095 | 0 | 0 | 6 |
| Tras las correcciones de la auditoría (10/11, `71597183c`) | 5 185 | 0 | 0 | 6 |

Las 97 incidencias heredadas se resolvieron por causa:
- **Scripts de simulación:** los tres vuelven al estado que registra la revisión del rover (73 pruebas de sucesores y de revisión de versión).
- **Listas de imagen:** las de las imágenes se regeneraron (1).
- **Recuperación de pre-lanzamiento:** deriva sus rutas del registro sellado y funciona desde cualquier ruta (23).

### 6.1 Insumos de la suite: suite portable frente a suite histórica

Varias pruebas del rover leen evidencias y estado local que Git ignora y que no vienen en un clon limpio:
- `evaluation/operations/`;
- parte de `simulation/ros2_gazebo/results/`;
- `missions/generated/`;
- `work/`.

En el equipo de desarrollo existen y hay una copia en el respaldo previo a la integración.

**Inventario.** Está en [suite-local-inputs-2026-11-10.json](suite-local-inputs-2026-11-10.json): 95 rutas y unos 122 000 archivos. Incluye también el paquete Hermes fijado de `deploy/planner/vendor/`. Para cada ruta registra el número de archivos y una huella SHA-256 calculada sobre la lista ordenada de `ruta  sha256` de sus archivos. Se genera y se comprueba con:

```bash
python -m tools.suite_local_inputs --write docs/suite-local-inputs-<fecha>.json
python -m tools.suite_local_inputs --check docs/suite-local-inputs-2026-11-10.json
```

La comprobación es de solo lectura y termina con error si falta, sobra o cambia alguna ruta.

- **Suite portable.** Lo que pasa en un clon limpio de la rama, sin esos datos (`git clone --no-local --single-branch`, con el mismo entorno virtual).
- **Suite histórica.** El resto: pruebas que verifican evidencias selladas, recuperaciones históricas y snapshots fijados. Necesitan los datos locales y los objetos Git de las revisiones fijadas.

| Ejecución del 10/11/2026 | Aprobadas | Fallidas | Errores | Omitidas |
| --- | --- | --- | --- | --- |
| Suite completa en el *checkout* con los datos locales | 5 185 | 0 | 0 | 6 |
| Suite en un clon limpio, sin datos locales | 4 425 | 163 | 582 | 17 |

**Las 745 pruebas no aprobadas del clon limpio.**
- **Datos ignorados (744):**
  - 729 son `FileNotFoundError` sobre los datos ignorados: `simulation/ros2_gazebo/results`, `evaluation/operations` y `missions/generated/drafts`;
  - 15 dependen de esos mismos datos de forma indirecta: demo offline, vista REAL del escenario agrícola, capturas pasivas históricas y manifiestos de cierre.
- **Referencia `main` (1):** la prueba necesita la referencia local `main`, que un clon de una sola rama no tiene.

Ninguna depende del código: con los datos presentes, la misma revisión aprueba todo. Las 11 omisiones adicionales son condicionales a esos datos. Se recogen 4 casos menos porque su parametrización se construye a partir de los datos.

El clon limpio sacó a la luz un defecto de portabilidad, corregido en `71597183c`. El registro del hito usaba la abreviatura automática de Git, cuya longitud depende del número de objetos del repositorio.

**Entorno de la ejecución.**
- **Sistema y versiones:**
  - Linux 6.18 (WSL2) y Python 3.12.3;
  - pytest 9.1.1, langgraph 1.2.12, langchain-core 1.7.0 y pydantic 2.13.5;
  - 65 paquetes, según `pip freeze`.
- **Datos locales:** el inventario de §6.1, comprobado sin cambios después de las ejecuciones.
- **Advertencia registrada:** solo la informativa de LangSmith.

**Ejecución que cruzó una suspensión.** Una primera ejecución sobre `99a0ee378` cruzó una suspensión del equipo. Registró 3 vencimientos de plazo de reloj en `test_rover_pulse_integration.py`, que pasan aislados y en las dos ejecuciones siguientes.

## 7. Nomenclatura y referencias que se conservan

El código y la documentación vigentes usan nombres técnicos que describen la función: subsistema rover, sistema multiagente, `rover_v2_bridge`, `ROVER_ADAPTER`, `--rover-snapshot`...

Se conservan sin cambiar, a propósito:

- **Evidencias selladas, checkpoints y el registro del hito M4c-r1**, con sus nombres de directorio y su contenido. Para reproducir una evidencia exactamente se usa el commit que figura en su nombre y en su README.
- **`multiagent/historical_identifiers.py`.** Contiene:
  - los pocos identificadores de revisiones fijadas que el código vigente necesita en tiempo de ejecución: la procedencia escrita por los snapshots históricos del rover, y el commit y los nombres de archivo del puente fijado;
  - la tabla de correspondencia entre nombres anteriores y actuales.
- **Valores del contrato del rover** emitidos por `tools/rover_agent_adapter.py`:
  - la procedencia, ahora en la constante `PROVENANCE_SOURCE`;
  - el motivo de alcance no vinculado;
  - el contenido de los archivos de código, scripts y esquemas del paquete del rover pendiente de revisión.

  Cambiarlos es una modificación de contrato que corresponde a esa revisión, porque su manifiesto registra sus SHA-256. Dos textos de ese paquete conservan el nombre de una herramienta de desarrollo; la propuesta de cambio está en el documento de revisión.
- **Nombres de terceros** (un módulo de transporte de Hermes Agent) y la rama existente de candidata de integración.
