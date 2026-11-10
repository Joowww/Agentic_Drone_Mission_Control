# Hito: primera misión integrada con Qwen real en los tres agentes (M4c-r1)

Este registro es **aparte** de la evidencia sellada. Esa evidencia está en `multiagent/benchmark/results/m4c_r1_integrated_v1_2026-11-07_f1ec396c9/` y no se ha modificado. `milestone.json` lo genera, solo leyendo, `python -m multiagent.benchmark.milestone`, y contiene los 20 puntos completos (*prompts* y respuestas literales incluidos).

## Verificación

Hecha sin llamar al modelo:
- todos los `SHA256SUMS` de la ejecución, de la demo y del análisis cuadran;
- el manifiesto es idéntico byte a byte al registrado en `ac92b087f` (sha256 `c500cb89…`) y al *digest* del resumen;
- los *prompts* y respuestas de las 4 llamadas cuadran con sus sha256.

## Los 20 puntos (resumen; el detalle está en `milestone.json`)

| # | Punto | Valor |
| --- | --- | --- |
| 1 | Fecha (UTC) | 06/11/2026, 23:05:17–23:06:39 (07/11 a las 00:05 en hora local) |
| 2 | Commit | Ejecución en `f1ec396c9`; manifiesto `m4c_r1_integrated_v1` |
| 3–4 | Modelo y digest | `ollama:qwen3:4b`, `359d7dd4…74fae7` (Q4_K_M, local) |
| 5 | *Prompts* | `interpret_brief/4`, `agent_drone_single/3` y `agent_rover_single/3` (×2): textos completos con su sha256 |
| 6 | Configuración | Temperatura 0, seed 7, `num_ctx` 8192, `think` falso; `safety/4`; 6 llamadas como máximo, 2 por rol; `resource_isolation/1` |
| 7 | Escenario | Dos zonas aéreas (POI_1 rgb, POI_3 multispectral) y una tarea del rover condicionada a una cartulina validada. Imagen `SYNTHETIC_TEST`, eventos `TEST_FIXTURE` |
| 8 | Respuestas originales | Las 4, literales |
| 9–10 | Herramientas y resultados | Dron: `drone_capabilities`, `validate_route` ×2 (FEASIBLE) y `check_separation` (conflictos). Rover B: `rover_capabilities` y `validate_ground_target` (PASS). Rover A: pidió `check_dependency(ROVER_START)`, pero su resultado **no quedó registrado**; está repetido y etiquetado en `analysis/replay.json` |
| 11 | Validadores deterministas | Procedencia `VALID` sin correcciones; `safety/4` sin señales; compuerta del dron aceptó (`DECONFLICTED_BY_START_DELAY`); `rover_gate` aceptó en A y en B; compuerta de percepción `ACCEPTED` (POI_3, σ 0,12 m); coordinador en `AUTHORIZATION_REQUESTED` |
| 12–13 | Primera propuesta y revisiones | Primera ronda en los tres roles; 0 revisiones |
| 14 | Plan final | drone_02→POI_3 (sale a los 0 s) y drone_01→POI_1 (sale a los 45 s); rover_01→POI_3 después de que drone_02 alcance POI_3 y drone_01 termine |
| 15–16 | Tokens y latencias | 1423+331 / 39,8 s (carga en frío); 1331+206 / 18,9 s; 1047+110 / 11,2 s; 1095+123 / 10,3 s |
| 17 | Errores | Ninguno de *parsing*; `finish_reason: stop` en las 4 |
| 18 | Fallbacks | Ninguno; los 3 roles `MODEL_SUCCESS_FIRST_ROUND` |
| 19 | Estado de ejecución | `PLANNING_COMPLETED_EXECUTION_PENDING_AUTHORIZATION`. Solicitud en `AWAITING_HUMAN_AUTHORIZATION`, no ejecutable porque ningún humano ha fijado velocidad ni tiempo máximo |
| 20 | Cero comandos | `commands_sent` 0 en el resultado, en el resumen y en las fases A y B; `vehicles_contacted` 0; `ros2_commands_sent` 0; `physical_effect` falso |

## Calidad del plan (`plan_quality`, 11 comprobaciones, todas superadas)

- **El conflicto está registrado.** Hay 16 conflictos iniciales; por ejemplo, los ascensos desde los despegues pasan a 8,0 m, y se exigen 8,5.
- **El conflicto lo resolvió el validador determinista, no Qwen.** El modelo propuso **solo la asignación** (drone_01→A1, drone_02→A2), que es la que se mantiene en el plan final. La agenda la calculó la desconflictación: probó las salidas en una rejilla declarada de 5 s y eligió **el menor retraso que elimina todos los conflictos**: 45 s para drone_01.
- **La minimalidad está verificada por repetición determinista**, sin modelo. Las rutas reconstruidas son idénticas a las selladas, la agenda se reproduce, y cada retraso menor deja conflictos: 0 s → 16, 5 → 16, 10 → 14, 15 → 8, 20 → 6, 25 → 4, 30 → 4, 35 → 1, 40 → 1.
- **Plan completo y sin límites inventados.** No falta ningún objetivo, las dependencias se mantienen y la velocidad y el tiempo máximo siguen sin fijar hasta que lo haga un humano.
- **El supervisor conservó la información del operador**, sin inventar drones ni batería.
- **El traspaso al Rover Agent es correcto.** El objetivo validado es POI_3; la tarea terrestre va a POI_3 después de que la tarea aérea llegue a POI_3, y coincide con el agente determinista.

## Qué no afirma

- No es una estadística, sino una ejecución a temperatura 0.
- No hubo percepción real: la imagen y los eventos son sintéticos.
- No hubo SITL, ni vehículo, ni movimiento.
- El *prompt* `/4` se escribió después de ver M4b.
