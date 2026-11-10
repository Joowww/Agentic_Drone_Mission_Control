# Emplazamiento, flota, instanciación y exportación `.plan`

Estado a 27/10/2026. Todo lo descrito funciona **offline**:
- No se ha cargado ninguna misión, ni se ha importado en QGroundControl, ni se ha ejecutado nada.
- No se ha usado Docker, la simulación, inferencias ni Opik.
- La arquitectura no cambia (ArduPilot, ROS 2, AP_DDS, Gazebo y los modelos del repositorio).
- Los archivos del subsistema rover (rover, transporte, identidad, lifecycle) no se han modificado.

## 1. Qué existía y quién es la autoridad de cada dato

| Dato | Representación existente | Autoridad tras este cambio |
| --- | --- | --- |
| Misión, ruta, home declarado | `models/mission_definition.py` | La misma. Las misiones instanciadas son `MissionDefinition` |
| Conversión local ↔ geográfica | Modelo lineal 111 320 m/° (`planning/relative_routes.py`, `tools/simulation_mission_mapper.py`) | `planning/site_geometry.py` **reutiliza** esa constante, la función inversa del mapeador y los límites (1000 m, \|lat\| ≤ 75) |
| Vehículo lógico → interfaz SITL | `tools/simulation_profiles.py` | La misma. `fleet.json` solo la referencia (`sim_binding`) y se comprueba contra ella |
| Tipo y autopiloto de una misión | `VehicleDefinition` | `fleet.json`. La misión instanciada se construye desde la flota |
| Validación determinista | `tools/hermes_mission_validation.validate_mission` | La misma: `execution_status == APPROVED` es el criterio de «artefacto aprobado» para exportar |
| Exportación `.plan` | `inputs/qgroundcontrol_exporter.py` (sesión interactiva, Hermes) | `inputs/qgc_plan_export.py`, compartido por todas las entradas encontradas en el repositorio; la antigua delega en él desde el 27/10 (§8.1) |
| Lectura `.plan` | `inputs/qgroundcontrol_adapter.py` | La misma. Se reutiliza como **lectura de vuelta** independiente |
| Geofence, obstáculos, área | No existían | `site.json` (`models/site.py`) |
| Dependencias del escenario | Texto en `reporting/agri_scenario_summary.GROUND_TASK` y coordinador R1 | Plantilla de escenario más manifiesto. El coordinador R1 y sus compuertas no cambian |

**Límites entre las piezas:**
- **Emplazamiento** (`site.json`): dónde están las cosas.
- **Flota** (`fleet.json`): qué vehículos lógicos existen y cómo puede exportarse cada uno.
- **Plantilla de escenario**: qué tareas hay, sobre qué puntos con nombre y con qué dependencias. No contiene coordenadas.
- **Instancia**: la plantilla resuelta sobre un emplazamiento y una flota concretos. Lleva hashes, derivación y validaciones.
- **Paquete**: la exportación de una instancia, con su manifiesto y un `.plan` por dron compatible.

## 2. Artefacto de emplazamiento (`tfg.site/1`)

Lo describe `models/site.py`. Contiene:
- **Identificación:** `site_id`, `version`, `name`.
- **`status`:** uno de `SYNTHETIC`, `TEMPLATE_PENDING_MEASUREMENT`, `MEASURED_UNVERIFIED` o `VERIFIED_DECLARED`.
- **`provenance`:** tipo, fuente, quién midió, fecha y método.
- **Unidades:** fijadas a m y grados.
- **Marco local:** `local_frame`.
- **Referencias:** `geo_reference` (WGS84 del origen) y `vertical_reference` (AMSL del suelo en el origen, datum, terreno `DECLARED_FLAT` o `UNKNOWN`).
- **`vertical_limits`:** altura máxima sobre el suelo del origen.
- **Geometría:** perímetro, exclusiones (`applies_to` air/ground), zonas de despegue y aterrizaje, zonas de inicio del rover, área transitable del rover y puntos con nombre.

Cada zona y cada punto llevan `verification` y `uncertainty_m`.

**Geometría admitida:**
- Polígonos simples, como anillo abierto `[[x, y], …]` en metros, sin agujeros.
- `holes`, `radius_m`, círculos y similares se rechazan con `UNSUPPORTED_GEOMETRY`. Un hueco se describe como una exclusión aparte.
- Los polígonos autointersectados, degenerados o con vértices repetidos son errores de validación.
- Las exclusiones son de **altura completa**: el sobrevuelo de un obstáculo no se modela.

**Un dato `null` es un dato pendiente.** La plantilla se puede leer y el validador lista lo que falta, pero:
- ningún valor se rellena por defecto;
- sin referencias geográficas y verticales completas no hay exportación geográfica;
- solo `VERIFIED_DECLARED` con referencias y orientación también `VERIFIED_DECLARED` habilita el destino `field`.

`VERIFIED_DECLARED` es una declaración escrita en el archivo, no una autenticación.

## 3. Referencias y marco

**Marco `ENU_ROTATED`:**
- Metros, dextrógiro, +z arriba.
- +y apunta al rumbo `y_axis_bearing_deg` (horario desde el norte **verdadero**); +x queda 90° a su derecha.
- Con 0° es ENU (x este, y norte).
- La conversión es `E = x·cosβ + y·sinβ`, `N = −x·sinβ + y·cosβ`, seguida del modelo lineal existente.
- Está probada en ida y vuelta y con la misma salida que `relative_routes` para β = 0.
- Es una aproximación plana para emplazamientos pequeños, no una transformación geodésica.
- La orientación del marco no es el rumbo de ningún vehículo.

| Referencia | Dónde vive | Equivale a otra |
| --- | --- | --- |
| Punto de referencia del emplazamiento | Punto `reference` en (0, 0) de `site.json` | No |
| Posición de despegue planificada | Punto `planned_takeoff` dentro de una zona de despegue | No: es el `plannedHomePosition` del `.plan` |
| Posición inicial observada | Observación de una sesión (p. ej. `launch_position` de H2) | No |
| Home efectivo | Lo fija ArduPilot **al armar**. Las alturas del `.plan` son relativas a él | No. Nunca se registra offline |
| Origen del estimador | Estado de ArduPilot en ejecución | No observado |
| Spawn de Gazebo | Lanzador (`tfg_demo.launch.py`, x/y/z/yaw) | No: no hay transformación acreditada spawn ↔ marco del emplazamiento |
| Inicio del rover | Punto `rover_start` dentro de una zona de inicio | No |

El registro H2 lo ilustra: el origen del mundo Gazebo está a 584,0 m y la posición de lanzamiento observada de drone_01 está a 584,19 m (float32), unos 2,8 m al oeste. El manifiesto del paquete (a) guarda ambas por separado.

**Alturas:**
- La misión usa altura relativa al home efectivo.
- El límite del emplazamiento es sobre el suelo del origen.
- Solo se comparan si el terreno está declarado plano. En otro caso, la comprobación queda `NOT_CHECKABLE`.
- `plannedHomePosition` exige un AMSL real (del emplazamiento o de una observación) y nunca se escribe un 0 de relleno.

## 4. Instanciación (`planning/scenario_instance.py`)

**Cómo se resuelve:**
- La plantilla nombra puntos del emplazamiento; la instancia los resuelve.
- La derivación de cada coordenada queda registrada: punto, xy local, marco, método, lat/lon.
- El `instance_id` es el hash de plantilla, emplazamiento, flota y hashes de las misiones generadas. Si cambia cualquiera de ellos, cambian la instancia, las misiones y la validación.
- Una aprobación de otra instancia aparece como `STALE` y no se traslada.

**Aprobación:**
- `approval-draft` genera un borrador con los hashes que debe vincular y `approved_by` vacío.
- Una aprobación `BOUND` significa que los hashes coinciden; no autentica a nadie.
- Las demostraciones usan una aprobación etiquetada `SYNTHETIC_TEST_FIXTURE`, nunca una revisión de Joel.

**Misiones históricas:**
- **No se resuelven contra ningún `site.json`.**
- `historical_h2_instance` comprueba `SHA256SUMS` y toma las dos instantáneas ejecutadas en H2 (`321ad647…`, `079e25a3…`).
- Las vuelve a expresar sobre la posición de lanzamiento registrada, con la propia función de mapeo del ejecutor (`map_mission_route_to_simulation`), y conserva home declarado, lanzamiento observado, origen Gazebo y spawn.
- La comprobación cruzada con H2 reproduce el error horizontal registrado de cada waypoint, con una diferencia máxima de 1 mm (0,389 frente a 0,388 m en un caso): el rebase coincide con los objetivos que el ejecutor usó.
- Ese lanzamiento es de una **sesión pasada**: en una sesión SITL nueva hay que volver a observarlo y, si difiere, reinstanciar.

No hay cobertura agrícola, rutas entre árboles ni detección: solo POI explícitos.

## 5. Validación espacial (`planning/site_validation.py`)

**Qué comprueba:**
- coordenadas finitas;
- polígonos simples y no degenerados;
- ids únicos y referencias existentes;
- despegue y arranque del rover estrictamente dentro de sus zonas;
- POI dentro del perímetro;
- zonas de despegue dentro del perímetro y sin solapar exclusiones aéreas;
- cada tramo (despegue → POI → … → regreso a la coordenada de despegue) dentro del perímetro y sin cortar ni tocar exclusiones aéreas, también cuando ambos extremos son válidos;
- holgura frente al margen declarado;
- límite vertical cuando las referencias son comparables.

**Rover:**
- Se usan su área transitable y las exclusiones `ground`; nunca el perímetro aéreo.
- Si la recta sale del área o cruza una exclusión, el resultado es `REQUIRES_PLANNING` (no existe planificador).

**Margen:**
- `planning_margin_m` es un margen **declarado**.
- Si faltan la geometría del vehículo o las incertidumbres, queda `NOT_ACCREDITED`.
- Con todos los valores, solo se compara con valores declarados (`COVERS/BELOW_DECLARED_VALUES`).

**Regreso:** el `.plan` v2 no usa RTL (§8): vuelve a la coordenada planificada a la altura de la misión, la misma línea que se valida aquí.

Superar estas comprobaciones no demuestra contención física, ausencia de obstáculos desconocidos ni prevención de colisiones: se refieren a la **línea planificada**.

## 6. Flota (`tfg.fleet/1`, `missions/fleets/agri_demo_fleet.json`)

| Vehículo | Categoría | Perfil | Compatibilidad |
| --- | --- | --- | --- |
| drone_01, drone_02 | `sitl_multirotor` (ArduCopter SITL, IRIS) | `QGC_PLAN_ARDUCOPTER` (familia; el exportador declara la versión de perfil, hoy V2) | `DOCUMENTED_SITL` |
| large_drone_01 | `large_drone` (referencia de disponibilidad) | `NONE` | `UNRESOLVED_COMPATIBILITY` |
| mini_drone_01 | `mini_drone` (marcador) | `NONE` (obligatorio) | `UNRESOLVED_COMPATIBILITY` (obligatorio) |
| rover_01 | `rover` (ArduRover SITL) | `NONE` (obligatorio: no se presupone `.plan`) | `NOT_APPLICABLE` |

- `physical_identity` es siempre `NOT_ESTABLISHED`: `drone_01` no acredita ningún aparato físico.
- No hay números de serie ni SYSID reales.
- El hardware descrito por Joan figura solo como referencia de disponibilidad, sin firmware ni estación presupuestos.

## 7. Paquete (`tools/scenario_package.py`)

**Contenido:**
- `plans/<vehículo>.plan`: uno por dron compatible, nunca mezclados.
- `missions/*.mission.json`.
- `instance.json`.
- Copias de `site.json`, `fleet.json` y `template.json`.
- `approval.json`, si se aporta.
- `export_report.md`.
- `manifest.json` y `SHA256SUMS`.

**Qué vincula el manifiesto:**
- instancia, entradas con hashes y emplazamiento;
- vehículos y artefactos con estado, motivos, hashes, perfil y verificación;
- tareas terrestres (`FORMAT_PENDING`, transformación `NOT_ACCREDITED`);
- coordinación, separación conjunta y referencias;
- aprobación, procedencia y limitaciones.

**Estados de artefacto:**
- `GENERATED`
- `BLOCKED_MISSING_DATA`
- `BLOCKED_VALIDATION_FAILED`
- `COMPATIBILITY_PENDING`
- `UNSUPPORTED_FORMAT`

**Estado del paquete:**
- Es `COMPLETE_OFFLINE` o `PARTIAL`.
- `deployment_ready` es **siempre** `false`.
- `lifecycle` distingue: exportado / comprobación de archivo (`FILE_MATCHES_EXPECTATIONS` y lectura con nuestro importador, hoy `REDUCED`) / importado en QGC / subido / leído de vuelta del vehículo / ejecutado. Los cuatro últimos son `NOT_DONE`.
- `pending_conditions` lista margen (`NOT_ACCREDITED`), elementos condicionados, parámetros del autopiloto no leídos y versión de QGC desconocida. Aparece en `summary` y en `export_report.md`, no solo en el JSON.
- `layers` separa: declaración del operador (`status` del emplazamiento), procedencia de las medidas, validación geométrica y aprobación de despliegue (§15).

**Escritura:**
- Es atómica (directorio temporal más `rename`).
- Un directorio existente se rechaza.
- La misma entrada produce los mismos bytes (comprobado en tests).

## 8. Exportación `.plan` (`inputs/qgc_plan_export.py`)

Destino único: **`QGC_PLAN_ARDUCOPTER_V2`** (27/10/2026). Sustituye a V1, que terminaba en RTL.

**Fuentes, por tipo:**

| Tipo | Fuente | Qué acredita |
| --- | --- | --- |
| Versión ejecutada acreditada | Registros del SITL: `ArduCopter V4.8.0-dev (755258db)` en `results/gui_control_two_drones_2026_10_25`, `rover_identity_trial_2026_10_26` y otros del 20–26/10. Imagen `sha256:5d5de3c6…` el 25 y 26/10 | Firmware de **esas** sesiones. El registro H2 (24/10) no guarda versión ni imagen: la de H2 no está acreditada |
| Fuente de la misma versión | Árbol local limpio `~/TFG/ardupilot_ros2_ws/src/ardupilot` en `755258dbb452`: `ArduCopter/mode_auto.cpp`, `libraries/AP_Mission/AP_Mission.cpp` | Semántica de los comandos en esa versión. No acredita que el binario de la imagen se compilara sin cambios |
| Documentación consultada | [QGC plan format](https://docs.qgroundcontrol.com/master/en/qgc-dev-guide/file_formats/plan.html), [Copter mission commands](https://ardupilot.org/copter/docs/mission-command-list.html), [MAV_CMD](https://ardupilot.org/copter/docs/common-mavlink-mission-command-messages-mav_cmd.html) (rama *master*, 27/10) | Formato y comandos según la documentación actual, no según una versión concreta |
| QGroundControl | No se ha encontrado ninguna instalación | Versión **desconocida**: compatibilidad no comprobada |
| Equipos físicos | — | Desconocidos |

### 8.1 Entradas de exportación revisadas

**Alcance de la revisión (27/10/2026):** búsqueda en el repositorio de las llamadas a `export_qgroundcontrol_plan`, `build_qgroundcontrol_plan`, `export_validated_mission_plan` y `validate_mission_file(..., export_qgc=True)`.
- Las entradas encontradas son las de la tabla, y todas comparten `build_plan`.
- No cubre scripts externos ni copias del código fuera del repositorio.
- Que compartan exportador significa que todas producen lo mismo y lo rechazan igual. **No** demuestra que el archivo sea compatible con QGroundControl o con un vehículo: eso sigue pendiente (§8.3, §8.4).

| Entrada | Antes del 27/10 | Ahora |
| --- | --- | --- |
| Menú 1–4 (sesión interactiva) | Exportador propio: acciones → waypoint, home 0 m como AMSL, sin velocidades, RTL | Delegan en `build_plan`. Sin AMSL del home: **`REFUSED`** con motivos, sin archivo |
| Hermes: finalización, revisión, `validate_and_export_qgc`, CLI `--export-qgc` | Igual que el menú | Igual que el menú. `qgc_plan_path` = null y `qgc_export` = `REFUSED` con motivos |
| `tools.scenario_package` | Estricto V1 | Estricto V2, con AMSL del emplazamiento o del lanzamiento observado |

- Las misiones de la sesión, Hermes y las importadas de QGC solo tienen alturas relativas al home y ninguna fuente AMSL. Por eso hoy **ninguna** de esas entradas genera un `.plan`.
- La exportación geográfica se hace por `scenario_package`.
- Los `.plan` que existieran de antes no se borran: se listan como `earlier_files_not_from_this_operation`.
- Las finalizaciones históricas (H1…) conservan sus `.plan` antiguos y su verificación de hash: tienen la semántica V1 antigua y **no** se regeneran.
- Comprobación con el código de HEAD (`83a147d`) sobre `precision_agriculture_demo.json`: `survey` y `take_photo` salían como `NAV_WAYPOINT`, `plannedHomePosition` = `[41.275, 1.987, 0.0]`, sin `DO_CHANGE_SPEED` y con RTL al final. Está en la evidencia del 27/10 (`agri_export_semantics_2026_10_27`).
- La descripción de la herramienta MCP `validate_and_export_qgc` explica desde el 27/10 que solo escribe archivo si están los datos necesarios y que puede devolver `REFUSED`. Firma, permisos y lista de herramientas sin cambios.
- La descripción de `finalize_mission_draft` explica desde el 27/10 que finaliza y valida el borrador, intenta la exportación estricta y puede devolver `REFUSED` por datos ausentes. Firma, permisos y comportamiento sin cambios.

### 8.2 Correspondencia con la misión (tabla `semantics` en el informe)

H2 (ejecutor, GUIDED) hace esta secuencia:
1. Despega hasta la altura del primer waypoint.
2. Envía cada waypoint por separado y lo acepta a ≤ 1,0 m horizontal y ≤ 0,75 m vertical.
3. Si `return_to_home`, va a la **coordenada** de lanzamiento observada a la altura del último waypoint.
4. Ordena **siempre** `LAND`.

No aplica `speed_kmh` ni yaw.

**Qué significa cada etiqueta (`label_scope` en el informe):**
- **EXACT:** el elemento **concreto** que nombra la fila coincide con el de la misión, o con el del registro H2 cuando se dice. No significa equivalencia dinámica con H2, compatibilidad con QGC o con el vehículo, ni ninguna garantía de vuelo.
- **CONDITIONED:** el elemento está en el archivo, pero su efecto depende de algo externo (parámetros del autopiloto, posición de armado).
- **NOT_IN_PLAN:** el elemento no está expresado en el archivo.

| Elemento | `.plan` V2 | Estado |
| --- | --- | --- |
| Despegue | `NAV_TAKEOFF` (22), frame 3, altura del primer waypoint. lat/lon no usados por Copter (`do_takeoff`) | CONDITIONED: relativo al home **efectivo** (armado) |
| Valores de coordenadas | `NAV_WAYPOINT` (16), frame 3, lat/lon con 8 decimales | EXACT: valores iguales a los de la misión (cuantización degE7 ≤ 5,6 mm); nada sobre la trayectoria volada |
| Aceptación | param2 = 0. Copter usa `WP_RADIUS_M` y, con espera 0 y otro ítem de navegación detrás, **no se detiene** (`set_next_wp`) | CONDITIONED |
| Parámetro de espera | param1 = 0 (el modelo no tiene espera) | EXACT: el parámetro, no la permanencia del vehículo |
| Yaw | param4 = NaN → `WP_YAW_BEHAVIOR` | CONDITIONED (tampoco lo fijaba el ejecutor) |
| Velocidad | `DO_CHANGE_SPEED` (178): tipo 1, m/s, param3 = 0 («sin cambio» en `AP_Mission` 755258db) | CONDITIONED: solicitada, no validada; H2 no la aplicaba. Sin velocidad: NOT_IN_PLAN (`WP_SPD`) |
| Coordenada de regreso | `NAV_LAND` (21) con la **coordenada** planificada: Copter vuela allí a la altura actual y aterriza (`do_land`). Sin regreso: `NAV_LAND` en el último waypoint | EXACT en el paquete histórico: la coordenada coincide con el lanzamiento registrado por H2. El movimiento difiere: H2 enviaba un objetivo GUIDED y esperaba a 1,0 m antes de `LAND`. CONDITIONED en el resto |
| Orden de aterrizaje | `NAV_LAND` explícito; no depende de `RTL_ALT_FINAL_M` | EXACT: la orden existe, como en H2. Descenso y contacto dependen de `LAND_*` |
| Failsafe | Parámetros `FS_*` del autopiloto | NOT_IN_PLAN |
| Home | `plannedHomePosition` = lat, lon, **AMSL real** | No es el home efectivo |
| Geofence | Vacío | El perímetro no se exporta como valla |

**Se rechazan** (`ExportRefused`), sin omitirlas en silencio:
- acciones distintas de `navigate`;
- altura 0 (en Copter significa «mantener la actual»);
- lat/lon 0,0 (significa «posición actual»);
- home con altura distinta de 0 (referencia ambigua);
- autopilotos o tipos no ArduPilot multirrotor;
- un AMSL ausente.

### 8.3 Comprobación independiente

`verify_plan` da tres resultados separados:

1. **Expectativas MAVLink** (`MAVLINK_EXPECTATIONS`, escritas desde las fuentes y no desde el constructor): comando, frame, parámetros fijos, NaN solo en param4, posición explícita y altura > 0.
2. **Correspondencia con la misión:** secuencia de comandos, coordenadas, alturas y velocidades esperadas, derivadas de la misión.

   Si 1 y 2 se cumplen, el estado es `FILE_MATCHES_EXPECTATIONS`. Los tests también fijan valores literales escritos a mano.
3. **Lectura con nuestro importador:** hoy `REDUCED`. Descarta `TAKEOFF` y convierte `LAND` en un waypoint más, así que las pérdidas se listan y no quedan ocultas bajo «verificado». Comparte supuestos con el exportador y **no** es QGroundControl.

`compatibility` = `NOT_ESTABLISHED` mientras no se importe en QGC, se suba y se lea de vuelta del vehículo. El procedimiento está en [qgc-first-import-procedure.md](qgc-first-import-procedure.md).

Estado a 27/10/2026: hecho el primer paso para un único archivo. `drone_01.plan` del paquete V2 sintético (`692c8075…`) se importó y se guardó en QGroundControl 5.1.5 sin diferencias semánticas (`evaluation/observability/qgc_first_import_2026_10_27/`). Siguen pendientes la subida, la lectura de vuelta desde el vehículo y la ejecución, así que `compatibility` sigue siendo `NOT_ESTABLISHED`. Los `lifecycle` y `pending_conditions` de los paquetes ya generados conservan `NOT_DONE` y «versión de QGC desconocida» porque describen el momento de su exportación; no se han regenerado.

El acuerdo de 1 mm del paquete histórico solo comprueba la reconstrucción geométrica: no demuestra importación, carga ni ejecución.

### 8.4 Comparación con el archivo guardado por QGroundControl

`python -m tools.qgc_plan_compare ORIGINAL.plan GUARDADO.plan --out DIRECTORIO_NUEVO`

**Qué escribe:**
- copias byte a byte de ambos archivos;
- `text.diff` (diff textual);
- `comparison.json` y `comparison.md`;
- `SHA256SUMS`.

**Categorías:**
- `PRESENTATION`: mismo valor, distinto texto.
- `QGC_METADATA`: campos que QGC escribe para sí: `groundStation`, versiones de formato, `cruiseSpeed`/`hoverSpeed`, `AMSLAltAboveTerrain`, `Altitude`/`AltitudeMode` ausentes en ítems sin altura, y `doJumpId` renumerado si no hay `DO_JUMP`.
- `SEMANTIC_CHANGE`: comando, frame, parámetro, coordenada, altura, cabecera o home.
- `ADDED` / `REMOVED`: ítems o elementos de un solo lado.
- `UNDETERMINED`:
  - campos desconocidos;
  - constantes `NaN`/`Infinity` (no son JSON estándar);
  - cambios de tipo (`true` frente a `1`);
  - cambios de `AltitudeMode`;
  - un `Altitude` que no coincide con param7;
  - ítems que no son `SimpleItem`;
  - una deriva de coma flotante que cae en el mismo entero degE7.

**Reglas de `null`, NaN y 0** (QGC master `98ee79c1`, `MissionItem::load` y `JsonParsing::possibleNaNJsonValue`; ArduPilot `755258db`, `sanity_check_params`):
- QGC lee `null` como NaN.
- `null` frente a 0 es **siempre** un cambio.
- Un `null` donde ArduPilot no admite NaN se marca como tal.

**Archivos no interpretables** (JSON inválido, claves duplicadas, no UTF-8, sin `mission.items`): dan `UNREADABLE_SAVED` o `UNREADABLE_ORIGINAL`, sin normalizar ni reparar. El diff y las copias se conservan igualmente.

El resultado se limita a comparar los dos archivos, nunca es un veredicto de compatibilidad. Pruebas en `tests/test_qgc_plan_compare.py`: cambios sintéticos de comando, altura, frame, yaw, velocidad, coordenada, home, firmware y pérdida o adición de ítems.

**Corrección (27/10/2026):** las expresiones «semántica cerrada» y «una sola ruta» del README de `agri_export_semantics_2026_10_27` (que no se modifica), así como la afirmación de la entrega de que ninguna entrada podía producir un `.plan` semánticamente incorrecto, exceden lo comprobado. Lo comprobado es:
- todas las entradas encontradas en el repositorio comparten el exportador;
- ese exportador rechaza lo que no puede expresar;
- su salida cumple unas expectativas MAVLink escritas desde las fuentes citadas.

La compatibilidad con una versión de QGroundControl y con el vehículo sigue pendiente.

**Paquetes V1** (evidencia `agri_site_fleet_export_2026_10_27`): `verify` comprueba su integridad e informa `PROFILE_SUPERSEDED`. No se regeneran.

**Ejecución GUIDED frente a misión importada:** H2 se ejecutó en **GUIDED**, con órdenes por AP_DDS. Un `.plan` se ejecutaría en **AUTO**. Son caminos distintos, y el éxito de H2 no se traslada al `.plan`.

## 9. Coordinación

- Los `.plan` no coordinan nada.
- El orden (`SEQUENTIAL`) y las dependencias (`COMPLETED`, `POI_REACHED` + punto) viven en la plantilla, en el manifiesto y en el coordinador.
- No hay esperas temporales.

**Qué se comprueba:**
- tareas y vehículos únicos;
- dominio (aéreo o terrestre) coherente con la categoría;
- vehículos presentes en la flota y en `simulation_profiles`;
- dependencias existentes y con su punto en la secuencia;
- ausencia de ciclos;
- un orden de ejecución compatible.

**La validación conjunta** da la separación mínima horizontal entre rutas planificadas: 5,54 m entre las rutas históricas de H2 y 8,0 m en el huerto sintético. La simultaneidad queda siempre `NOT_CLEARED` porque no hay deconflicción temporal.

Validación individual, validación conjunta y autorización de ejecución son tres cosas distintas, y ninguna de las dos primeras autoriza nada.

## 10. Comandos

Desde la raíz del repositorio, con el venv del proyecto. Cada `--out` debe ser un directorio nuevo.

```bash
python -m tools.scenario_package validate-site missions/sites/synthetic_orchard_v1.site.json
python -m tools.scenario_package validate-site missions/sites/dronelab.template.site.json
python -m tools.scenario_package validate-fleet missions/fleets/agri_demo_fleet.json
python -m tools.scenario_package instantiate --template missions/templates/agri_poi_visit_v1.json --site missions/sites/synthetic_orchard_v1.site.json --fleet missions/fleets/agri_demo_fleet.json
python -m tools.scenario_package package --template missions/templates/agri_poi_visit_v1.json --site missions/sites/synthetic_orchard_v1.site.json --fleet missions/fleets/agri_demo_fleet.json --target sitl --out /tmp/pkg_b
python -m tools.scenario_package package-historical --fleet missions/fleets/agri_demo_fleet.json --out /tmp/pkg_a
python -m tools.scenario_package package-finalized --store evaluation/observability/planning_container_real_2026_10_28_r2/store --hermes-evidence evaluation/observability/planning_container_real_2026_10_28_r2 --scenario-binding evaluation/observability/agri_planning_h1_nous_2026_10_24/h1_binding.json --assign drone_01=e31bd08d-19ed-440e-b815-94f8b9c062d5/0b6af58a-943c-4f06-a631-1a55d4a66d6d@TAKEOFF_A --assign drone_02=c244d68c-819e-4324-b99a-7d299b97081d/dd6055ee-5090-40c9-98b9-d0b8cb85e93a@TAKEOFF_B --rover rover_01@ROVER_START --site missions/sites/synthetic_orchard_v1.site.json --fleet missions/fleets/agri_demo_fleet.json --target sitl --out /tmp/pkg_h
python -m tools.scenario_package approval-draft --package /tmp/pkg_b --out /tmp/approval_b.json
python -m tools.scenario_package verify /tmp/pkg_b
python -m tools.scenario_package summary /tmp/pkg_b
```

También es accesible desde el menú: `python main.py` → 5 → 3 (acción `f` para las misiones finalizadas por Hermes, §17).

Las salidas de las demostraciones a–f están en `evaluation/observability/agri_site_fleet_export_2026_10_27/` (perfil V1, sustituido). El paquete SITL V2 y el inventario nuevo están en `evaluation/observability/agri_export_semantics_2026_10_27/`.

## 11. Cómo rellenar la plantilla DroneLab desde VS Code

1. Copia `missions/sites/dronelab.template.site.json` a `missions/sites/dronelab_v1.site.json`. No edites la plantilla.
2. Cambia `status` a `MEASURED_UNVERIFIED`.
3. En `provenance`, pon `kind` `MEASURED` y rellena `source`, `measured_by`, `measured_on` (AAAA-MM-DD) y `method` (p. ej. «cinta métrica 30 m + GNSS de móvil», con modelo si se conoce).
4. Elige un **origen** físico marcado y que se pueda volver a encontrar (una esquina, una estaca). Ese es `ORIGIN` = (0, 0).
5. Elige la dirección de +y (p. ej. a lo largo de una pared). Mide su rumbo respecto al norte **verdadero** (`y_axis_bearing_deg`) e indica cómo lo obtuviste (`orientation_source`). Si solo tienes rumbo magnético, anótalo como tal: hay que corregir la declinación.
6. Para cada polígono, mide **cada vértice** (x, y) en metros desde el origen, recorriendo el contorno en orden.
   - **No basta con largo y ancho** si el área no es un rectángulo alineado con tus ejes, si hay esquinas achaflanadas, columnas, redes, árboles o mobiliario, o si las zonas permitidas no ocupan todo el recinto.
   - Mide por separado:
     - perímetro de operación;
     - cada obstáculo o zona prohibida, como polígono propio con `applies_to`;
     - zonas de despegue y aterrizaje;
     - zona de inicio del rover;
     - área transitable del rover.
7. Puntos: despegues planificados, inicio del rover y POI, cada uno con su `zone_id` cuando corresponda.
8. Anota `uncertainty_m` de cada elemento (p. ej. 0,05 m con cinta, 3–5 m con GNSS de móvil).
9. Para exportación geográfica: lat/lon WGS84 del origen con su fuente e incertidumbre, `origin_ground_amsl_m` con su datum, y `terrain` (`DECLARED_FLAT` solo si lo has comprobado). Lo que exige esta ruta se explica en §16; GNSS es solo una forma de cumplirlo.
10. Si el recinto tiene techo o redes, pon la altura máxima en `vertical_limits.max_altitude_m` con su fuente.
11. Valida: `python -m tools.scenario_package validate-site missions/sites/dronelab_v1.site.json`.

El esquema JSON se puede ver en `models/site.py`: VS Code resalta las claves y los errores aparecen en el validador, con la ruta del campo.

## 12. Datos que Joel debe aportar

- **Mediciones del DroneLab** (§11), con fuente, fecha e incertidumbres. Sin ellas, `c` sigue bloqueado.
- **Si habrá vuelo en el DroneLab:**
  - si el espacio es interior o exterior;
  - qué fuente de posición usará cada vehículo (GNSS, sistema externo de captura de movimiento, visión…);
  - si el autopiloto tendrá un origen global coherente con el del emplazamiento (§16).
- **Datos del dron grande:** firmware y versión, estación de tierra y versión, tipo de bastidor. Sin ellos sigue `UNRESOLVED_COMPATIBILITY`.
- **Minidrones:** plataforma, autopiloto y formato de misión cuando se conozcan.
- **Para SITL:** la versión de QGroundControl que se usará. ArduPilot ya consta como 4.8.0-dev (755258db) en los registros del 20–26/10, pero no en el de H2. Para la sesión del ensayo: guardar la línea de versión y el id de imagen.
- **Aprobaciones:** quién aprueba, para qué alcance (ensayo SITL o campo) y sobre qué hashes.

## 13. Preparación offline frente a validación pendiente

| Hecho offline (verificado) | Pendiente en SITL | Pendiente en hardware |
| --- | --- | --- |
| Modelos, validadores y conversión probados | Importar el `.plan` en QGC (versión fijada) | Todo lo de SITL, más el emplazamiento medido y verificado |
| `.plan` generado; expectativas MAVLink cumplidas; nuestro importador lo lee con pérdidas declaradas | Subirlo y leerlo de vuelta **del vehículo** | Identidad física de cada vehículo |
| Rebase H2 coincide con los objetivos ejecutados | Ejecutar en AUTO; comparar con GUIDED | Compatibilidad de firmware y estación |
| Dependencias y aprobación vinculadas por hash | Parámetros `WP_RADIUS_M`, `WP_YAW_BEHAVIOR`, `WP_SPD`, `FS_*` efectivos | Márgenes acreditados con geometría e incertidumbre reales |
| Rover: línea planificada comprobada en el área | Transformación marco emplazamiento → odometría del rover (subsistema rover) | — |

## 14. Contrato mínimo pendiente con el subsistema rover (rover)

No se ha modificado ninguna interfaz suya. Para que una tarea terrestre de un paquete pueda pasar al coordinador R1 haría falta, como mínimo:
1. Un objetivo expresado en un marco del emplazamiento (`site_id`, `version`, sha256, `frame_id`, x/y).
2. Una transformación **acreditada** de ese marco al marco de navegación del rover (fuente, error y sesión), que hoy es `NOT_ACCREDITED`.
3. Que la orden y su resultado lleven el `instance_id` y el hash del manifiesto para poder vincularlos.

Las compuertas actuales de R1 (identidad, autorización, transformación del objetivo) no cambian.

## 15. Cuatro capas que no se implican entre sí

| Capa | Dónde | Qué significa | Qué no significa |
| --- | --- | --- | --- |
| Declaración del operador | `status` y `verification` en `site.json` | Lo que alguien escribió | Que sea cierto. Editar `VERIFIED_DECLARED` no lo verifica |
| Procedencia de las medidas | `provenance` (`kind`, `source`, `measured_by`, `measured_on`, `method`) | Quién dice haber medido, cuándo y cómo | Que la medición sea correcta |
| Validación geométrica | `validate_site` y comprobaciones de ruta | Las líneas planificadas respetan la geometría **declarada** | Contención física ni ausencia de obstáculos |
| Aprobación de despliegue | `approval.json` `BOUND` a los hashes de la instancia | Un nombre declarado queda vinculado a archivos exactos | Autenticación de la persona, ni que se hayan hecho la importación, carga o ejecución |

**Qué está probado:**
- Una plantilla DroneLab con todos sus indicadores cambiados a `VERIFIED_DECLARED` sigue `BLOCKED_MISSING_DATA`: procedencia `TEMPLATE`, sin geometría y validación `INVALID`.
- Un emplazamiento completo y declarado verificado genera archivos para `field`, pero la aprobación sigue `ABSENT` y `deployment_ready` sigue `false`.
- La herramienta no puede saber si unos datos tecleados son inventados: esa garantía es humana y queda fuera del sistema.

## 16. Localización y referencia global que requiere esta ruta

Un `.plan` V2 expresa los ítems en `MAV_FRAME_GLOBAL_RELATIVE_ALT` (lat/lon WGS84 y altura sobre el home efectivo). Según la documentación de ArduPilot, Copter no admite marcos locales en comandos de misión. Para que el archivo tenga sentido en un vehículo hacen falta **dos** cosas:

1. **Referencia del emplazamiento:** lat/lon del origen del `site.json`, con su orientación (§3).
2. **Localización del vehículo en ese mismo marco global:** el estimador del autopiloto debe tener un origen global y una posición coherentes con esa referencia.
   - Con GNSS esto ocurre de forma natural.
   - Sin GNSS, ArduPilot puede usar otras fuentes (por ejemplo, un sistema externo de posición con un origen del estimador fijado). En ese caso, la lat/lon del `site.json` debe ser **la misma** que la fijada como origen, aunque no sea una medición topográfica.

**Qué hace nuestro sistema:**
- Comprueba (1) en lo declarado.
- **No** comprueba (2) en ningún caso: no fija ni lee el origen del estimador ni la fuente de posición.
- Solo implementa esta ruta global para ArduCopter.
- Otras plataformas (los minidrones, aún desconocidos) pueden usar interfaces en marco local u otros formatos: quedan `UNRESOLVED_COMPATIBILITY` y esta limitación no se generaliza a ellas.

## 17. Misiones finalizadas por Hermes → paquete (`package-finalized`, 28/10/2026)

Conecta las misiones que Hermes guarda y finaliza (`update_mission_draft` + `finalize_mission_draft`) con este empaquetador. No hay otro modelo de misión, exportador ni orquestador: el paquete sale de `build_package` y del exportador estricto V2, y se comprueba con `verify`.

**Qué recibe de Hermes:** cada finalización del almacén de planificación (`drafts/<draft_id>/<finalization_id>/`).
- **Integridad:** se verifica con `load_finalization`: identidad, hash de la misión, borrador y estado de origen, y que la revisión finalizada coincide con la del estado de origen.
- **Almacén reubicado:** un almacén copiado o montado en otra ruta, como el del contenedor leído desde el anfitrión, se acepta si las rutas registradas nombran esa misma instantánea. Queda anotado en `relocated_from`.
- **Con `--hermes-evidence`:** se exige además que todo el directorio de la ejecución coincida con su `SHA256SUMS` y que los archivos de la finalización figuren en él. Se registran `run_id`, retorno, proveedor y modelo, el veredicto de revisión y si la respuesta final de Hermes cita esa finalización.
- **Copias en el paquete:** la misión original, `finalization.json`, el borrador y su estado se copian a `hermes/<vehículo>/` sin modificarlos.

**Qué asociación exige al operador**, toda explícita:
- `--assign VEHÍCULO=DRAFT_ID/FINALIZATION_ID@PUNTO_DE_DESPEGUE` por cada misión;
- `--site` y `--fleet`;
- opcionalmente, `--rover VEHÍCULO@PUNTO_ROVER_START` y `--scenario-binding`, que nombra los puntos del escenario. Para agri_demo_001 es el binding de H1, que liga POI_A1 al WP1 de drone_01 solo si el hash de la misión coincide.

**Rechazos y bloqueos:**
- **Se rechaza** (código 2, sin escribir nada):
  - una finalización alterada o con evidencia que no coincide;
  - una finalización cuyo vehículo no es el asignado;
  - la misma finalización o el mismo vehículo asignados dos veces.
- **Se bloquea** (el artefacto queda en el paquete):
  - con un emplazamiento sin referencia geográfica o vertical, `BLOCKED_MISSING_DATA` con la lista exacta de lo que falta. No se deriva ninguna misión;
  - con un punto que no es `planned_takeoff` o una ruta que no pasa las comprobaciones del emplazamiento, `BLOCKED_VALIDATION_FAILED` con cada motivo.

**Cómo se asocia al emplazamiento:**
1. Se toman los desplazamientos norte/este de cada waypoint respecto al home **declarado en la misión finalizada**, con la misma función que usa el ejecutor (`_calculate_local_offset_metres`). Se comprueba que coinciden con los offsets de su `geometry_intent`.
2. Se colocan sobre el punto de despegue elegido en el marco del emplazamiento (§3) y se convierten a lat/lon con su referencia.

El resultado es una **misión derivada**:
- **Identidad nueva:** id `…_on_<sitio>_v<versión>_<despegue>`, hash nuevo y validación determinista propia.
- **Comprobaciones:** las del emplazamiento sobre la línea planificada, mediante `validate_aerial_local_route`, que es el mismo núcleo que `validate_aerial_route`.
- **AMSL:** el AMSL del `plannedHomePosition` es el del emplazamiento.
- **Aprobación:** la aprobación de la misión original **no se hereda** (`approval_inherited: false`).
- **Altitudes y velocidades:** iguales a las de la original. Las altitudes siguen siendo relativas al home efectivo.

**Coordinación:**
- Se conserva la secuencia de agri_demo_001, la misma que la del histórico H2: drone_01 → drone_02 → R1, con R1 tras `POI_REACHED POI_A1` de drone_01. Se comprueba con `coordination_checks`.
- La tarea del rover queda `FORMAT_PENDING`, con su línea validada en el área transitable.
- `deployment_ready` es siempre `false`.

**Demostración** (`evaluation/observability/hermes_finalized_package_2026_10_28/`): las dos misiones de la ejecución real r2 sobre `synthetic_orchard_v1`, destino SITL.
- **drone_01** sobre TAKEOFF_A: **GENERATED**, `.plan` `FILE_MATCHES_EXPECTATIONS`.
- **drone_02** sobre TAKEOFF_B: **BLOCKED_VALIDATION_FAILED**. Los offsets de su misión (sector B, 8 y 16 m al norte y 4 m al este) llevan el WP2 al borde de la exclusión TREE_ROW_1. Desde TAKEOFF_A tampoco cabe. No se ha modificado el emplazamiento para forzarlo.
- **Paquete:** `PARTIAL`, con aprobación `ABSENT`.

**Caso positivo con los dos drones (30/10/2026, `evaluation/observability/hermes_finalized_package_two_drones_2026_10_30/`):**
- **Emplazamiento:** `missions/sites/synthetic_hermes_rehearsal_v1.site.json`, un ensayo SINTÉTICO diseñado para estos offsets. No es DroneLab ni un campo. Despegues en (−6,−6) y (6,−6), un seto central y una fila norte.
- **Resultado:** las dos misiones salen GENERATED, con dos `.plan`. El paquete es `COMPLETE_OFFLINE`, R1 queda `FORMAT_PENDING`, la aprobación `ABSENT` y `deployment_ready: false`.
- **Correspondencia:** la verifica de forma independiente `correspondence.json` (vehículo, despegue, offsets, AMSL y originales intactos). Los `.plan` no se han importado en QGC.
- **Caso negativo:** el caso sobre `synthetic_orchard_v1` se conserva como resultado distinto.

**Qué significa `coordination` PASS:**
- **Es solo estructura de dependencias:** tareas, vehículos, orden y ciclos.
- **No indica:**
  - que los artefactos estén disponibles (`package_status` y el estado de cada artefacto);
  - que estén aprobados (`approval`);
  - que estén listos para ejecutar (`deployment_ready`, `deployment_blockers`).
- **Desde el 30/10:** `deployment_blockers` enumera cada tarea no GENERATED y cada tarea `FORMAT_PENDING`, y el resumen y el informe lo dicen expresamente.
