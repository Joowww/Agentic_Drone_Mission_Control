# Primera importación de un `.plan` en QGroundControl (procedimiento; ejecutado una vez el 27/10/2026)

**Resultado del 27/10/2026.** QGroundControl 5.1.5 contenedorizado, sin red ni vehículos, abrió `drone_01.plan` del paquete V2 sintético y guardó una copia (`256f5a52…`). La comparación con el original (`692c8075…`) dio `NO_SEMANTIC_DIFFERENCES`, con 4 PRESENTATION y 3 QGC_METADATA. Evidencia y detalle de las siete diferencias: `evaluation/observability/qgc_first_import_2026_10_27/`. La revisión visual de Joel está registrada aparte, con 12 capturas: versión v5.1.5 de 64 bits, 5 ítems, Takeoff a 5 m Rel, Change Speed Ground Speed 2,778 m/s, dos Waypoints a 5 m Rel, Land sin RTL, sin geovallas y 0 puntos de rally. No se confirmaron AutoConnect, la ausencia de avisos ni las coordenadas en pantalla.

**Segunda aplicación, 30/10/2026:** los dos `.plan` derivados de Hermes del paquete `hermes_finalized_package_two_drones_2026_10_30`, con `QGC_PLAN_DIR` apuntando a su `plans/`.
- **Resultado:** NO_SEMANTIC_DIFFERENCES por separado en cada archivo, con 4 PRESENTATION y 0 QGC_METADATA.
- **Evidencia:** `evaluation/observability/qgc_import_hermes_two_drones_2026_10_30/`.
- **Visualización:** antes hubo que relanzar el cliente RDP de WSLg (`diagnostics_wslg/`).

Queda acreditado: **importación y guardado sin cambios semánticos de este archivo con esta versión de QGC**. Siguen pendientes la carga en SITL, la lectura de vuelta desde el autopiloto, la ejecución en SITL y el hardware. Otras versiones de QGC u otros archivos no quedan cubiertos.

**Objetivo:** comprobar si una versión concreta de QGroundControl abre el archivo exportado y muestra los mismos ítems MAVLink que espera nuestro verificador.

**Qué no hace este paso:**
- no conecta ningún vehículo;
- no sube ni ejecuta nada;
- no acredita compatibilidad con el autopiloto.

Cargar, leer de vuelta y ejecutar son pasos posteriores, cada uno con su propia autorización (ver [integrated-trial-protocol.md](integrated-trial-protocol.md)).

QGC se ejecuta en el servicio `qgc` de [deploy/compose.yaml](../deploy/compose.yaml) (QGroundControl 5.1.5, imagen `tfg/qgroundcontrol:5.1.5`). No se instala en Windows. Requisitos del anfitrión y construcción de la imagen: [student-environment.md](student-environment.md).

## 0. Preparación (offline, en el repositorio)

1. Archivo de ensayo: el `.plan` del dron 1 del paquete sellado V2 sintético.

   | | |
   | --- | --- |
   | Paquete | `evaluation/observability/agri_export_semantics_2026_10_27/packages/b_synthetic_orchard_v1_sitl_v2` (`instance_id` `b9cff3e6b6950110`) |
   | Archivo | `plans/drone_01.plan` |
   | sha256 | `692c8075133ef62bdb4a051892387ce62213fb2c8ae3a905904d2f157d142c8d` |
   | Informe esperado | tabla «Semántica A1» de `export_report.md` del mismo paquete |

   ```bash
   P=evaluation/observability/agri_export_semantics_2026_10_27/packages/b_synthetic_orchard_v1_sitl_v2
   (cd $P && sha256sum -c SHA256SUMS)
   python -m tools.scenario_package verify $P
   ```

   Si se regenera el paquete con `python -m tools.scenario_package package … --target sitl`, los `.plan` salen byte a byte iguales a los de este paquete. `export_report.md` y `manifest.json` no son idénticos: después se añadió `label_scope` y se renombraron etiquetas. Comprobado el 27/10/2026.
2. El servicio monta el directorio `plans/` del paquete **en solo lectura**. QGC no puede reescribir el original, así que no hace falta copiarlo.
3. Crea el directorio de evidencia **nuevo** y, dentro, el único directorio escribible para QGC:

   ```bash
   E=evaluation/observability/qgc_first_import_AAAA_MM_DD
   mkdir -p $E/qgc_saved
   ```

## 1. Registro previo

| Dato | Cómo obtenerlo |
| --- | --- |
| Versión exacta de QGroundControl | La que muestra la aplicación (al pie del menú del icono «Q» o en *Application Settings*). Anótala literal. La imagen declara 5.1.5 (`docker image inspect tfg/qgroundcontrol:5.1.5`) |
| Imagen | ID de la imagen: `docker image inspect --format '{{.Id}}' tfg/qgroundcontrol:5.1.5` |
| Sistema anfitrión | Windows con su versión, WSL2 con WSLg y Docker Desktop, con sus versiones (`wsl --version` en Windows, `docker version`) |
| Estado de conexión | El servicio no tiene red (`network_mode: none`) ni dispositivos. Todas las autoconexiones arrancan desactivadas. Compruébalo en *Application Settings → Comm Links*, sección AutoConnect, y haz una captura |
| Archivo | `/data/plan/drone_01.plan` dentro de QGC. Su sha256 es el del paso 0 |

## 2. Importación sin vehículo

1. Arranca QGC (ventana de WSLg):

   ```bash
   QGC_SAVE_DIR=$PWD/$E/qgc_saved docker compose -f deploy/compose.yaml run --rm --name tfg-qgc-import qgc
   ```

2. Ve a la vista **Plan**. Abre *File → Open* y selecciona `/data/plan/drone_01.plan`.
3. **Captura de pantalla** de la lista de ítems y del mapa. Sin red, el mapa no carga teselas: el fondo vacío es esperado y no es un fallo.

## 3. Qué comprobar y anotar (frente a `export_report.md`)

| # | Comprobación | Esperado (dron 1 del huerto sintético) |
| --- | --- | --- |
| 1 | Mensajes o avisos al abrir | Ninguno. Si aparece alguno, cópialo literal: es un resultado, no un fallo del procedimiento |
| 2 | Firmware y vehículo que asume QGC | ArduPilot, multirrotor. Si QGC lo cambia, anótalo |
| 3 | Posición planificada (*Planned Home*) | lat −35,3633159; lon 149,16519294; altitud 584 m AMSL |
| 4 | Ítem 1 | *Takeoff*, 5 m, altura relativa (*Rel*) |
| 5 | Ítem 2 | *Change Speed* 2,778 m/s (10 km/h), tipo velocidad sobre el suelo |
| 6 | Ítems 3–4 | *Waypoint* sobre POI_1 y POI_2, 5 m *Rel*, sin espera (*Hold* 0), yaw vacío |
| 7 | Ítem 5 | *Land* en las coordenadas del despegue planificado. **No** debe aparecer *Return To Launch* |
| 8 | Modo de altura de la misión | Relativa al home |
| 9 | Geovalla y puntos de rally | Vacíos |
| 10 | Número de ítems | 5 (más el home que QGC muestra como ítem 0) |

## 4. Guardar una copia desde QGC (sin sobrescribir)

1. *File → Save As…* en `/data/saved/drone_01.qgc_resaved.plan`. Es el único directorio escribible, y en el anfitrión es `$E/qgc_saved/`. Cualquier otra carpeta de QGC, como la predeterminada `~/Documents/QGroundControl`, vive en memoria y **se pierde al cerrar**.
2. Cierra QGC. La ventana se cierra y el contenedor se elimina; los archivos de `$E/qgc_saved/` se conservan. Si la ventana no responde: `docker stop tfg-qgc-import`. Este comando solo afecta a ese contenedor, no al simulador.
3. Compara offline, desde el repositorio, con un directorio de salida nuevo:

   ```bash
   python -m tools.qgc_plan_compare $P/plans/drone_01.plan $E/qgc_saved/drone_01.qgc_resaved.plan --out $E/comparison
   ```

3. El comparador:
   - copia ambos archivos sin tocarlos;
   - guarda el diff textual (`text.diff`);
   - clasifica cada diferencia en `comparison.md`:

| Categoría | Qué hacer |
| --- | --- |
| `PRESENTATION` | Nada: mismo valor, distinto texto |
| `QGC_METADATA` | Anotar. No cambia un ítem MAVLink según las reglas documentadas, pero sigue siendo un cambio |
| `SEMANTIC_CHANGE`, `ADDED`, `REMOVED` | Invalida la compatibilidad de esta versión: anotar cada fila |
| `UNDETERMINED` | No dar por equivalente. Anotar y resolverlo con la fuente de QGC de **esa** versión antes de concluir |

   Estado global y código de salida:
   - `IDENTICAL_BYTES` o `NO_SEMANTIC_DIFFERENCES`: salida 0;
   - `UNDETERMINED` o `SEMANTIC_DIFFERENCES`: salida 1;
   - `UNREADABLE_*`: salida 2. QGC guardó algo que no se puede interpretar. No se repara.

## 5. Registro del resultado

En el mismo directorio nuevo de evidencia, junto a `comparison/`, guarda:
- la versión de QGC;
- las capturas;
- los avisos;
- la tabla del paso 3 rellenada (OK / diferencia);
- un `SHA256SUMS` final.

El resultado se describe así:
- **«Importado en QGroundControl X.Y.Z; comparación NO_SEMANTIC_DIFFERENCES»**, con las filas de metadatos listadas, o
- **«Importado con diferencias o indeterminaciones: …»**.

Ninguno de los dos significa «compatible con el vehículo». Sigue pendiente **subirlo y leerlo de vuelta del autopiloto** (SITL), con su propia autorización.

## 6. Qué no hacer en este paso

- No conectar QGC a SITL ni a un vehículo. No quitar `network_mode: none` ni añadir dispositivos al servicio.
- No pulsar *Upload*.
- No editar ítems en QGC antes de guardar la copia del paso 4.
- No sobrescribir el `.plan` del paquete. El montaje en solo lectura lo impide; no lo cambies a escritura.
