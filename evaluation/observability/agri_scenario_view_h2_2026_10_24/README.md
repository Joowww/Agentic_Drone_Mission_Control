# Vista determinista del escenario agri_demo_001 sobre la ejecución real de H2 — 24/10/2026

`scenario_view.json` es la salida **real** de
`reporting.agri_scenario_summary.get_scenario_view("agri_demo_001", request_key="agri-demo-001-h2-r01")`,
generada offline:
- sin Hermes, sin proveedor y sin simulación;
- leyendo el registro local de la secuencia `6628bc51-e232-45f5-901e-f5fdeb05c6f4`;
- con el registro de vinculación de H1.

Es la misma función que expone la herramienta MCP de solo lectura `get_scenario_view` (esquema
`tfg.agri-scenario-view/1`).

## Qué contiene y de dónde sale

| Bloque | Fuente | Valor en esta ejecución |
| --- | --- | --- |
| Artefactos vinculados | `h1_binding.json` (con `bind_scenario`) y hashes de los snapshots | `321ad647…` y `079e25a3…`; el registro, por ruta relativa y SHA-256 |
| Secuencia | `get_preflight_sequence` (plan y operación verificados) | `FINISHED / PASSED`, `plan_sha256` igual al de la evidencia de H2 |
| Orden | horas de ejecución, no de admisión | `ACCREDITED_BY_EXECUTION_TIMESTAMPS`: ventanas del ejecutor disjuntas, despacho del hijo 2 posterior al resultado del hijo 1, y orden `land` de drone_01 (12:54:22) anterior al `arm` de drone_02 (12:56:14) |
| Cronología de cada ejecución | informe y operación del coordinador | admisión del job (12:51:18 en **ambos**: no prueba el orden), despacho, inicio del ejecutor, inicio de cada orden (`guided`, `arm`, `takeoff`, `return_home`, `land`), fin del ejecutor y aceptación del resultado. Reloj de pared UTC, no tiempo simulado. |
| POI, regreso y aterrizaje | `summarize_scenario` | 4 POI `REACHED`; `CONFIRMED`; `MISSION_LANDING_CONFIRMED` |
| `R1` | resumen | `BLOCKED_PENDING`, dependencia `MET`, `commands_sent: false`, `movement_authorized: false`, con el significado explícito de `MET` |
| Autorización registrada | plan de la secuencia | `OPERATOR_DECLARED_VIA_AGENT`, su alcance y el SHA-256 de la declaración. No incluye el texto. `authenticated: false` |
| Limitaciones | fijas en el código | sin percepción; velocidad no comandada ni medida; marco común no validado; datos del ejecutor por AP_DDS; sin vuelo simultáneo |
| Alcance temporal | — | `record: historical`, `as_of` 12:59:51 UTC; disponibilidad y restricciones actuales `NOT_CHECKED`; `operational_authorization: false` |

Los hashes de los informes y del plan coinciden con
[la evidencia de H2](../../../simulation/ros2_gazebo/results/agri_demo_h2_2026_10_24/README.md). Un test
lo comprueba.

**No contiene** rutas absolutas, la clave de petición, identidades de proceso ni el texto de la
autorización.

**No es** una consulta de seguridad actual ni un permiso. Tampoco garantiza que un modelo la
interprete bien: su efecto en las respuestas de Hermes está pendiente de evaluar (H3b).

`SHA256SUMS` cubre todo salvo este README.
