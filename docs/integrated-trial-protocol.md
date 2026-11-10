# Protocolo del ensayo integrado (propuesta, NO ejecutado)

Recorrido: Hermes → validación → drones → dependencia → rover → informes → observabilidad.

Estado a 27/10/2026: preparado offline. No se ha ejecutado ningún paso. El prerrequisito de 3b, la primera importación en QGC, está hecho para `drone_01.plan` del paquete V2 sintético con QGroundControl 5.1.5: `NO_SEMANTIC_DIFFERENCES` (`evaluation/observability/qgc_first_import_2026_10_27/`). La subida, la lectura de vuelta y la ejecución de 3b siguen pendientes. No hay inferencias, envíos a Opik, simulación ni cargas autorizadas por este documento: cada etapa que actúa necesita su propia autorización explícita de Joel.

## 0. Variantes y alcance

**Variantes:**
- **G (GUIDED), la misma vía que H2:** el ejecutor del repositorio manda GUIDED, armado, despegue, waypoints, regreso y aterrizaje por AP_DDS, a partir de la `MissionDefinition` validada.
- **M (misión importada):** el `.plan` del paquete se importa en QGroundControl, se sube al vehículo, se lee de vuelta y se ejecuta en AUTO. Es otra vía: el éxito de G no acredita M ni al revés.

Cada ejecución declara su variante, y los resultados nunca se mezclan en una tasa común.

**Alcance:**
- Solo SITL (perfil `two_drones_rover`).
- El rover solo si sus compuertas R1 lo permiten. Hoy **no** lo permiten: R1 queda `BLOCKED_PENDING`, y el protocolo lo registra así en lugar de forzarlo.

## 1. Fijado antes de empezar (registro previo)

| Elemento | Valor que debe registrarse |
| --- | --- |
| Commit y estado del árbol | `git rev-parse HEAD`, lista de modificados (sin staging) |
| Emplazamiento | `site_id`, versión y sha256. Para SITL: el huerto sintético v1 (`0db007e8…`) o el registro histórico H2 |
| Plantilla y flota | sha256 (`62dd9c06…`, `9a2ffcfa…`, flota v2) |
| Paquete | Directorio, `instance_id`, `manifest.json` sha256, `verify` = `VERIFIED` |
| Misiones | sha256 de cada misión del manifiesto: el mismo que recibirá el ejecutor (G) o el que generó el `.plan` (M) |
| Versiones | Línea `ArduCopter V…` del log y id de imagen **de esta sesión** (el registro H2 no las guardó), versión de QGroundControl (M), perfil de simulación, perfil de exportación (`QGC_PLAN_ARDUCOPTER_V2`) |
| Parámetros relevantes (leídos, no supuestos) | `WP_RADIUS_M`, `WP_YAW_BEHAVIOR`, `WP_SPD`, `FS_*`, `FENCE_ENABLE` de cada vehículo (el `.plan` V2 no usa RTL) |
| Autorizaciones | Texto de Joel por etapa (§2), con fecha. Texto ≠ autenticación |

## 2. Flota, asignaciones y autorizaciones

| Tarea | Vehículo | Interfaz SITL | Dependencia | Autorización necesaria |
| --- | --- | --- | --- | --- |
| A1 | drone_01 | v1 | — | Inicio de la secuencia aérea (G o M) |
| A2 | drone_02 | v2 | A1 `COMPLETED` | Incluida en la secuencia, sin espera temporal |
| R1 | rover_01 | v3 | A1 `POI_REACHED` y A2 `COMPLETED` | Propia, separada. Hoy imposible: compuertas R1 abiertas |

Aprobación del paquete:
- `approval.json` `BOUND` a la instancia exacta, alcance `SITL_REHEARSAL`.
- Si sale `STALE` o `ABSENT`, el ensayo no empieza.

## 3. Etapas y criterios

| # | Etapa | Entrada | Criterio de paso | Evidencia |
| --- | --- | --- | --- | --- |
| 1 | Hermes (opcional) | Especificación completa, como en H1 | Misión finalizada y `BOUND` al escenario. Caso cerrado en `hermes_capture_run` | Captura del caso (local) |
| 2 | Validación | Misiones del paquete o de Hermes | `execution_status APPROVED`. Validación espacial `PASS` sin `FAIL`. Coordinación `PASS`. Aprobación `BOUND` | `instance.json`, `manifest.json` |
| 3a | Drones, G | Misiones por hash | Secuencia `PASSED`. Cada POI `REACHED` por hash vinculado, `return_home CONFIRMED`, aterrizaje confirmado | Registro de secuencia (copias conservadas) |
| 3b | Drones, M | `.plan` por hash | Primera importación según [qgc-first-import-procedure.md](qgc-first-import-procedure.md) sin diferencias semánticas. Subido. **Leído de vuelta del vehículo** e igual al archivo (ítems, frames, coordenadas degE7, alturas). Ejecución AUTO con los criterios de 3a, salvo la aceptación: `WP_RADIUS_M` y paso sin detención en lugar de 1,0 m | Archivo leído de vuelta y su comparación |
| 4 | Dependencia | Resultados de 3 | `POI_A1`/`POI_1` `REACHED` y secuencia `COMPLETED`, por evidencia, no por tiempo | Vista del escenario |
| 5 | Rover | R1 | Solo si las compuertas R1 están cerradas. Si no, se registra `BLOCKED_PENDING` con sus motivos | Registro del coordinador |
| 6 | Informes | Registros | `agri_scenario_flow query` / informe determinista coherente con 3–5 | Informe local |
| 7 | Observabilidad | Metadatos | Payload revisado (§7) antes de cualquier envío | Cuerpo y respuesta del envío, si se autoriza |

## 4. Datos medidos

Por dron:
- posición de lanzamiento observada (no es el home efectivo);
- home efectivo, si el vehículo lo informa;
- error horizontal y vertical por waypoint;
- tiempo de cada tramo;
- velocidad observada frente a la solicitada (la solicitada no es una validación);
- en M: punto y altura del regreso (`NAV_LAND` con coordenada) y si el vehículo se detuvo en cada waypoint.

Rover: solo lo que su sesión registre. Nunca se combina con muestras de otra sesión.

## 5. Tratamiento de fallos

- **Un fallo en una etapa detiene las siguientes que dependen de ella.** No hay reintento automático: un reintento es una nueva ejecución con su propia autorización.
- **Hijo fallido en la secuencia:** el segundo dron no se ejecuta, porque la dependencia no se cumple.
- **Lectura de vuelta distinta del archivo (M):** no se ejecuta. Se conserva la diferencia.
- **Datos contradictorios o ausentes:** quedan `UNKNOWN`, nunca se rellenan con un valor favorable.
- **Evidencia alterada** (hash distinto): se rechaza y se conserva el original.
- **Parada de emergencia y recuperación:** las de la infraestructura existente (lifecycle del subsistema rover), sin cambios.

## 6. Verificación final de coherencia

1. `scenario_package verify` del paquete usado: `VERIFIED`.
2. El hash de misión ejecutada (o del `.plan` leído de vuelta) coincide con el del manifiesto.
3. Las dependencias se cumplieron en el orden registrado.
4. Los manifiestos y `SHA256SUMS` de las nuevas evidencias se verifican.
5. El informe no afirma nada que no esté en la evidencia. Revisarlo con la lista de afirmaciones excesivas de `docs/agri-demo-defense.md`.

## 7. Opik: qué se enviaría y qué queda local

**Se enviaría (solo metadatos, tras revisión y autorización):**
- `instance_id`, sha256 del manifiesto, procedencia (`SITL_*`) y variante (G/M);
- estado por etapa (`PASSED`, `BLOCKED_PENDING`…) y criterios cumplidos o no;
- número de POI alcanzados, aceptación del caso Hermes y versiones fijadas.

**Queda local:**
- misiones, `.plan`, coordenadas, emplazamiento y flota;
- registros de secuencia, capturas, journals y diarios;
- textos de autorización y cualquier ruta del sistema de archivos.

El cuerpo exacto se genera offline con `observability/opik_export.py` y se guarda junto a su hash antes de cualquier envío. El envío solo ocurre con autorización.

## 8. Documentos generados por el ensayo

- Registro previo (§1).
- Paquete y su `verify`.
- Registros de secuencia o de la misión importada.
- Vista y informe del escenario.
- Payload de Opik (si se autoriza).
- README con `SHA256SUMS`.

Nada se sobrescribe: cada ejecución tiene su directorio nuevo.
