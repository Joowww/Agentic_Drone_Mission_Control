# R1: revisión offline de la sesión de identidad `1cb9d86a` — 27/10/2026

Revisión de la evidencia de Codex
`simulation/ros2_gazebo/results/rover_identity_trial_2026_10_26/1cb9d86a-659b-4aa8-b7b1-214d2202210f/`.
- Sin Docker, operaciones, inferencias ni Opik.
- Sin cambios en archivos de Codex.
- Los gates, el candidato R1 y sus hashes no cambian. Lo comprueban
  `tests/test_rover_identity_facts.py`, para entradas reales y dobles.

## Verificación

- **Manifiesto:** `4d9558a2e31b9ea2ec42eca6d8b18cc007ce2cf4049bab011fa561ad59e34faf`, el indicado.
- **Archivos:** sus 164 entradas coinciden en tamaño y SHA-256, y no hay archivos sin listar.
- **Sesión:** lifecycle `e837942d-…`, arrancada y cerrada el 26/10 entre las 21:57 y las 22:00 UTC;
  la parada pertenece a otro propietario (`4fa9de1b-…`).
- **Alcance declarado:** una sesión pasiva headless autorizada y una disposición separada. Ningún
  movimiento.

## Hechos de esta sesión

Los genera `reporting/rover_identity_facts.py`
([`identity_facts.json`](identity_facts.json)). La etiqueta de la matriz de Codex se conserva junto a
cada hecho. En **cursiva**, comprobaciones cruzadas que he hecho sobre los archivos de la propia
sesión.

| Hecho | Estado | Observado | No acredita | Ámbito |
| --- | --- | --- | --- | --- |
| Odometría → bridge | **Observado** | *El GID de las 3 muestras retenidas de `/rover1/odometry` (`010feb7d3d1c6d37…1403`) es igual al del `bridge_publisher` de la traza* (pid 7229, `/model/rover1/odometry`) | El modelo que origina la odometría; la parada física | Pulso y POI_A1 |
| Plugin → entidad | **Observado** | *La entidad 67 se llama `rover1` en el catálogo de escena de la misma sesión, posición (0, −3).* Carga `OdometryPublisher` y `ArduPilotPlugin`, con socket JSON `127.0.0.1:9022`, y hace 3 envíos FDM | La traza no registra el nombre del modelo: la unión con el catálogo es por id de entidad dentro de una sesión | Pulso y POI_A1 |
| Parámetros | **Recibidos, atribución pendiente** | SYSID con valor 3 (etiqueta de la matriz). La respuesta pública tiene el GUID del solicitante a cero y los GUID nativos son distintos | Que la respuesta proceda del mismo XRCE/SITL que publica el Status | Pulso y POI_A1 |
| Receptor FDM | **No acreditado** | *Destino de los envíos de la entidad 67: `127.0.0.1:60575`.* No se retuvo ningún inodo ni propietario de socket | Qué proceso SITL recibe el FDM | Pulso y POI_A1 |
| Odometría → modelo | **Desconocido** | `OdometryPublisher` sin `odom_topic` (vale `None`); el bridge lee `/model/rover1/odometry` | La correspondencia por defecto del plugin con ese topic | Pulso y POI_A1 |
| Marcos | **No acreditados** | Candidato numérico SE(2) descriptivo | Error, origen, reloj y fuente; `frame_transform` | **Solo POI_A1** |
| Recepción | **Cerrada, cobertura parcial** | rc 0, `reader_closed: true`; 14 de 20 muestras; 6 de 9 streams | Cobertura completa: NavSat ausente en esta ventana | Pulso y POI_A1 |
| Monitor | **Incompleto** | rc 1: «Model server exit not observed by monitor» | La captura completa del monitor (no se completa a posteriori) | Pulso y POI_A1 |
| Parada lifecycle | **`SUCCESS`** | `stop` `FINISHED`, perfil `two_drones_rover` | Nada sobre el monitor: son resultados separados | Pulso y POI_A1 |

**Sesiones que no se combinan.** La captura `/3` del 25/10 (`4ac58516`) y esta sesión tienen GID
de odometría distintos: `010feb7d3c06f84c…` frente a `010feb7d3d1c6d37…`. Ni la atribución
muestra → bridge de hoy ni el catálogo de escena se aplican a las muestras del 25/10.
[`scenario_query/scenario_report.md`](scenario_query/scenario_report.md) muestra ambos conjuntos en
secciones separadas, cada uno con su sesión. Lo mismo con:

```bash
.venv/bin/python -m tools.agri_scenario_flow query --out <dir-nuevo> --identity-trial-root simulation/ros2_gazebo/results/rover_identity_trial_2026_10_26/1cb9d86a-659b-4aa8-b7b1-214d2202210f
```

## Matriz de preparación actualizada

Sustituye a la del 26/10 en
[agri_r1_recovery_correction_2026_10_26](../agri_r1_recovery_correction_2026_10_26/README.md#5-matriz-de-preparación-del-primer-r1-en-sitl),
que se conserva.

**Columnas de ámbito:**
- **Pulso local:** un `ROVER_BOUNDED_CONTROL` en el marco del cuerpo.
- **POI_A1:** la navegación R1 (`ROVER_NAVIGATE_V1`).

El ámbito sale de las rutas del código leídas sin modificarlas (versiones en «Fuentes utilizadas»):
- `NavigationGoal` exige `IDENTITY_SAME_ACCREDITED_FRAME`;
- al navegar, `_navigation_observation` aplica el contrato de marco y procedencia y obtiene el rumbo
  con `projected_ground_heading`;
- el control acotado solo exige que la identidad de la observación (GID, procedencia y marco) sea
  estable y que el rover esté en HOLD.

| Requisito | Evidencia | Estado | Pulso local | POI_A1 |
| --- | --- | --- | --- | --- |
| Status → escritor DDS → XRCE | `native-writer-analysis.json` | Contexto de creación exacto (histórico; no identidad actual del transporte) | sí | sí |
| XRCE → peer UDP | `socket-metrics.json`, `executed-helpers/monitor.py` | **Bruto** observado `127.0.0.1:65185`. **Normalizado derivado:** `127.0.0.1:41470`, según el contrato ejecutado (`normalized_udp_peer`): el `sin_port` en orden de red se expone como entero nativo y el ELF es little-endian. Es el peer de la matriz. Ninguno de los dos atribuye paquetes ni procesos | sí | sí |
| Peer → inode/FD → proceso SITL | `sockets.jsonl` | **No observado** | sí | sí |
| SYSID efectivo | `reader-analysis.json` | 3 recibido, **atribución pendiente** | sí | sí |
| Odometría → bridge | Esta revisión | **Observado** | sí | sí |
| Plugin → entidad (67 = `rover1`) | Esta revisión | **Observado** (unión por id dentro de la sesión) | sí | sí |
| Receptor FDM | Esta revisión | **No acreditado** | sí | sí |
| Odometría → modelo | `trace.log`, `bridge-config.yaml` | **Desconocido** | sí | sí |
| Recepción | `reader/` | Cerrada con cobertura parcial | sí (Status y odometría) | sí |
| Monitor / parada lifecycle | `monitor*.json` / `stop-result.json` | Incompleto (rc 1) / `SUCCESS`, por separado | sí | sí |
| Umbrales de parada (`stopped_*`) | Captura `/3` del 25/10: residual de 0,000156 m/s (otra sesión) | Contraste; no aprobado | sí | sí |
| Política operativa, autorización y reserva | Dry-run real | Bloqueado / ausente | sí | sí |
| `frame_transform` y `target_in_rover_frame` | Candidato numérico | **No acreditado** | **no** | sí |
| Tolerancia de llegada, permanencia, progreso y timeout | Solo sintéticos | Sin datos reales | no | sí |
| Rumbo con inclinación (antes «supuesto plano») | `projected_ground_heading` en `tools/rover_control.py` `da652736…`; evidencia de Codex `rover_heading_geometry_2026_10_26/3869b253` (manifiesto `f837549d…`) | **Geometría corregida:** la muestra real del 25/10, con 0,55° de cabeceo, da un rumbo de 89,77° y deja de rechazarse. Siguen **sin acreditar** la asociación de marco (`frame_association_verified: false`) y cualquier límite operativo de pendiente (`operational_slope_approved: false`) | no | sí |
| `ROVER_NAVIGATE_V1` y política `DISARM_AFTER_OBSERVED_STOP_V1` | Recorrido conjunto sintético | Probado sin física real | no | sí |
| Interfaz física de `start_ground_trial` | — | Pendiente | no (el pulso usa su propia ruta) | sí |
| Dependencia aérea (MET) | Vista H2 | Satisfecha (histórico) | no | sí |

## Requisitos circulares y afirmaciones excesivas

1. **Cuestión abierta: posible circularidad entre odometría → modelo y el pulso.** Si la atribución
   se quisiera obtener observando el movimiento que produce un pulso, ese pulso no podría exigirla
   como condición previa. Es una cuestión **por resolver** (Codex con Joel):
   - acreditarla sin movimiento, a partir del valor por defecto del plugin instalado y la
     configuración efectiva;
   - o definir qué identidad previa necesita la admisión de un pulso.

   Que el control acotado actual solo compruebe la estabilidad de GID, procedencia y marco es una
   descripción del código. **No** autoriza ningún pulso **ni** demuestra que una identidad estable
   baste para atribuir el movimiento al vehículo ordenado.
2. **Receptor FDM y peer → proceso** se pueden acreditar con un inventario de sockets completo y
   estático, sin movimiento. No deben esperar al pulso.
3. **Transformación de marcos:** es exclusiva de POI_A1. La matriz de Codex ya dice que no la
   requiere un pulso en el marco del cuerpo, y es correcto. No es circular: el ajuste usa puntos
   aéreos y deja al rover en reposo como control.
4. **Afirmaciones que conviene matizar:**
   - **Peer UDP:** conviene escribir siempre los dos valores: **bruto** 65185 (traza) y
     **normalizado derivado** 41470 (`normalized_udp_peer`, con el orden de bytes del ELF y la fuente
     de transporte fijada). No he encontrado nada que contradiga ese contrato. He comprobado que el
     helper ejecutado coincide con el del repositorio y que el orden registrado es `little`; no he
     revisado la fuente del agente fijada por su hash.
   - **`EXACT_RUNTIME_ENTITY_CONTEXT_OBSERVED`:** es exacto para plugin, entidad y socket. No
     identifica el modelo por sí mismo, porque la traza no tiene el nombre (hace falta el catálogo), y
     no incluye el receptor del FDM.
   - **Mi matriz del 26/10:** daba la posición ≈ (0, −3) como una coincidencia con el spawn. El
     catálogo de esta sesión sitúa `rover1` en (0, −3) en el mundo de Gazebo, pero es **otra
     sesión**: no acredita la transformación del 25/10 ni ninguna otra.
5. **Monitor y parada:** son dos resultados. La parada protegida fue correcta y el monitor quedó
   incompleto. No se completa la captura a posteriori ni se infiere uno del otro.

## Fuentes utilizadas

| Fuente | SHA-256 | Nota |
| --- | --- | --- |
| Manifiesto de la sesión `1cb9d86a` | `4d9558a2e31b9ea2…` | 164 entradas verificadas |
| `tools/rover_control.py` (árbol de trabajo, no HEAD) | `da6527368b6c16d6…` | Incluye `projected_ground_heading`. La versión anterior (`86db5da740d6375c…`, instantánea de la captura `4ac58516`) aplicaba el umbral 1e-3 a las componentes |
| `tools/rover_ground_executor.py` (árbol de trabajo) | `8e94ceb8f4a75ddf…` | Rutas de `ROVER_BOUNDED_CONTROL` y `ROVER_NAVIGATE_V1` |
| `executed-helpers/monitor.py` = `tools/rover_xrce_trace/monitor.py` | `65f8273293f48243…` | `normalized_udp_peer` |
| `executed-helpers/analyze.py` = `tools/rover_xrce_trace/analyze.py` | `a627814f09a64549…` | Contrato del puerto y fuente de transporte fijada (`0d3d11252c58b65c…`) |
| Evidencia `rover_heading_geometry_2026_10_26/3869b253` | manifiesto `f837549d1e4a626d…` | Rechazo antiguo reproducido y geometría proyectada con la muestra real |

> **Corrección (27/10/2026).** La primera versión de este documento describía el control plano con el
> umbral 1e-3 y presentaba el puerto 41470 como una afirmación excesiva y la circularidad casi como
> una conclusión. Las tres afirmaciones se han corregido según las fuentes de esta tabla.

## Archivos

- [`identity_facts.json`](identity_facts.json): hechos de la sesión, generados.
- [`scenario_query/`](scenario_query/) y
  [`scenario_query.terminal.txt`](scenario_query.terminal.txt): consulta del escenario con los hechos
  medidos (25/10) y los de identidad (26/10), en secciones separadas.
