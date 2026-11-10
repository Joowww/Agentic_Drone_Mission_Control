# Traspaso al subsistema rover: carga y lectura de vuelta en SITL de los dos `.plan` derivados de Hermes (preparado el 30/10/2026; NO ejecutado)

Este documento **no autoriza** nada: ni arrancar SITL, ni conectar QGC, ni cargar o ejecutar misiones. Cada paso necesita su propia autorización de Joel. Separa dos comprobaciones distintas:
- **A. Transferencia:** cargar cada misión en su vehículo SITL y leerla de vuelta. No mueve nada.
- **B. Ejecución:** queda fuera de este traspaso. Sus condiciones se listan para que no se confundan con las de A.

En [integrated-trial-protocol.md](integrated-trial-protocol.md) estas dos comprobaciones están juntas en la etapa 3b (variante M). Aquí se separan.

## 1. Archivos (originales, solo lectura)

Paquete `evaluation/observability/hermes_finalized_package_two_drones_2026_10_30/package/`:
- **Instancia:** `instance_id` `729489664a9615d5`, destino `SITL_REHEARSAL`.
- **Estado:** `COMPLETE_OFFLINE`, `deployment_ready: false`, aprobación `ABSENT`.
- **Integridad:** `verify` INTEGRITY_VERIFIED, con `SHA256SUMS` `ca7c15ed17dcc652ef28fbf55ec8c78d103cb94179c0e2cae4943ee84ea2714f`.

| Vehículo | `.plan` | sha256 | Misión derivada (sha256) |
| --- | --- | --- | --- |
| drone_01 | `plans/drone_01.plan` | `e5815ac0a03f8f40d804d49e194d77877bbdd058ced1da5b2f0252c8ecd94095` | `missions/HERMES_drone_01.drone_01.mission.json`, `b215a38bc3322fe958d2443e559665782fcbe0985295a0b47f7a927d6aa2fe91` |
| drone_02 | `plans/drone_02.plan` | `df2e0d6681c8695fc23bc7bda18ae45214c2403c625fcd934a90e38447853740` | `missions/HERMES_drone_02.drone_02.mission.json`, `c8f7c80e4d387294f2d8ff1c2a778c8cd5547a5e41fef54207552329f6bb6c79` |

**Contenido de cada `.plan`:** perfil `QGC_PLAN_ARDUCOPTER_V2`, `MAV_FRAME_GLOBAL_RELATIVE_ALT` y 4 ítems:
1. NAV_TAKEOFF a 5 m;
2. NAV_WAYPOINT;
3. NAV_WAYPOINT;
4. NAV_LAND en la coordenada del *Planned Home*.

Sin RTL, sin *Change Speed*, sin geovalla y sin puntos de rally. `plannedHomePosition` AMSL 584 m.

## 2. Informe y procedencia

| Elemento | Referencia |
| --- | --- |
| Informe de exportación | `package/export_report.md` (`e28bd8c384a9f9b3aea2eaa9292f9c43e231e77a96f67417ee4c05292cfbfb30`): tablas de semántica por dron, bloqueos y pendientes |
| Manifiesto e instancia | `package/manifest.json` (`2c2250c4…`) y `package/instance.json` (`ea3295ac…`) |
| Ejecución de Hermes | `real-hermes-planning-container-20261028-r2` (`evaluation/observability/planning_container_real_2026_10_28_r2/`): `nous` / `poolside/laguna-s-2.1:free`, retorno 0, revisión `PLANNING_CALLS_WITHIN_ALLOWED_TOOLS` |
| Finalizaciones originales | drone_01: borrador `e31bd08d-…` y finalización `0b6af58a-…`, misión `321ad647…`. drone_02: `c244d68c-…` y `dd6055ee-…`, misión `079e25a3…`. Copias byte a byte en `package/hermes/<vehículo>/` |
| Derivación | Offsets de la misión colocados sobre TAKEOFF_A y TAKEOFF_B del emplazamiento **SINTÉTICO de ensayo** `synthetic_hermes_rehearsal_v1` (`61d47a4e…`). Hash nuevo, validación propia y aprobación no heredada. La correspondencia la comprueba aparte `correspondence.json` (CORRESPONDS) |
| Flota | `agri_demo_fleet` v2 (`9a2ffcfa…`): `sim_binding` drone_01 y drone_02 |

## 3. Importación en QGC (hecha, offline)

`evaluation/observability/qgc_import_hermes_two_drones_2026_10_30/`: QGroundControl 5.1.5 (imagen `c6a5c57a…`), sin red, sin vehículo y sin *Upload*.

| Archivo | Copia guardada (sha256) | Comparación |
| --- | --- | --- |
| drone_01 | `a9a0eda8347c6fe110634f3ceb725a525ada7228fa7d669a2e688a216abacbde` | NO_SEMANTIC_DIFFERENCES (4 PRESENTATION) |
| drone_02 | `62522bb557ca2360e1aeded852c3580b74ea62c16cda6f026c82c2d2e5208171` | NO_SEMANTIC_DIFFERENCES (4 PRESENTATION) |

- **Visible en las capturas** (`screenshots/visual_review.md`): plan drone_01 y drone_02, cada uno con «4 items»: Takeoff, Waypoint, Waypoint y Land.
- **Sin confirmar:** la versión que muestra la interfaz, AutoConnect y la ausencia de avisos.
- **Lo que no acredita:** la importación no acredita carga, lectura de vuelta ni ejecución.

## A. Comprobación de transferencia (a preparar por el subsistema rover)

**Qué se hace.** Por cada vehículo:
1. Subir su `.plan` con el protocolo de misión MAVLink: `MISSION_COUNT` y `MISSION_ITEM_INT`.
2. Leerlo de vuelta: `MISSION_REQUEST_LIST` y `MISSION_ITEM_INT`.
3. Comparar lo leído con el archivo ítem a ítem.

La herramienta de subida la elige el subsistema rover: QGC (variante M) o un cliente MAVLink dentro del entorno del simulador. Sin armar, sin cambiar de modo y sin enviar `MISSION_START`.

**Comprobaciones previstas:**

| # | Comprobación | Criterio |
| --- | --- | --- |
| 1 | Destino | La misión de drone_01 va al vehículo vinculado a drone_01 (`sim_binding`, v1) y la de drone_02 al de drone_02 (v2). La identidad del vehículo se registra antes de subir |
| 2 | Aceptación | `MISSION_ACK` `MAV_MISSION_ACCEPTED` en cada subida. Cualquier otro resultado se conserva literal |
| 3 | Número de ítems | Los 4 del archivo, más la posición 0 que ArduPilot reserva al home. Se registra lo que ArduPilot devuelve en la 0, sin compararlo con `plannedHomePosition` como si fuera el mismo dato |
| 4 | Ítems 1–4 | `command`, `frame` (3), `param1`–`param4` (con yaw NaN), `autocontinue`, y `x`/`y` en degE7 y `z` iguales al archivo. Tolerancia horizontal: la cuantización degE7 que ya declara el exportador (`max_degE7_quantization_m` 0,004539 m). Sin tolerancias nuevas |
| 5 | Diferencias | Cada diferencia se clasifica y se conserva. No se reedita la misión ni se reintenta con otra para «pasar» |
| 6 | Evidencia | Mensajes de subida y de lectura en crudo, lectura de vuelta como archivo y comparación, en un directorio nuevo con `SHA256SUMS` |

**Condiciones que sí exige la transferencia, y por qué:**
- **SITL arrancado** con drone_01 y drone_02, mediante el lifecycle existente y con autorización propia. Sin vehículo no hay a quién subir la misión.
- **Identidad del vehículo destino verificada.** Subir la misión al vehículo equivocado invalidaría la comprobación.
- **Ninguna otra operación ni misión en curso en esos vehículos,** con la exclusión y las reservas existentes. La subida **reemplaza** la misión almacenada y podría interferir con otro trabajo.
- **Conexión MAVLink del cliente que sube.** El servicio `qgc` actual no tiene red (`network_mode: none`). Usarlo para esto exigiría un cambio explícito y separado de ese servicio, y no hacerlo implícitamente.

**Lo que la transferencia NO necesita:** aprobación de vuelo, armado ni prearm, que el spawn coincida con TAKEOFF_A/B, ni haber leído los parámetros `WP_*`, `FS_*` o `FENCE_*`. Subir y leer una misión con el vehículo desarmado no lo mueve. Esas condiciones son de la ejecución (B).

## B. Ejecución (fuera de este traspaso)

Pendiente y con autorización separada. Requeriría al menos:
- **Aprobación del operador** `BOUND` a los hashes de la instancia (`approval-draft`).
- **Referencias:** observar el lanzamiento en la sesión. El home efectivo lo fija ArduPilot al armar en el spawn, y no hay ninguna transformación acreditada entre el spawn de Gazebo y el marco del emplazamiento sintético. Si TAKEOFF_A/B y el lanzamiento no coinciden, hay que reinstanciar.
- **Parámetros efectivos leídos:** `WP_RADIUS_M`, `WP_YAW_BEHAVIOR`, `WP_SPD`, `FS_*`, `FENCE_ENABLE` y `LAND_*`.
- **Secuencia:** drone_01 antes que drone_02, por el resultado observado y no por tiempo. R1 sigue `FORMAT_PENDING` y con sus compuertas.
- **Seguridad:** las holguras del emplazamiento sintético no acreditan separación operativa segura ni ausencia de conflictos en vuelo.
