# Demo de precisión offline: los 17 escenarios con `safety/3` y `safety/4` (06/11/2026, `62032d378`)

Es evidencia **nueva**. No sustituye ni modifica `precision_demo_offline_2026-11-06_792d93936/`.

**Por qué 17 y no 16.** La evidencia anterior se selló con 16 escenarios. Después se añadió `supervisor_refuses` a raíz del piloto M4, que ejecutaba agentes después de un rechazo. Joel lo llama «supervisor_rejection»; su nombre en el código es `supervisor_refuses`. Aquí están los 17 actuales, ejecutados después de los cambios del supervisor (`interpret_brief/3`, `safety/4`).

```bash
python -m multiagent.demo --all-scenarios --safety-policy safety/3 --out <dir>/safety3
python -m multiagent.demo --all-scenarios --safety-policy safety/4 --out <dir>/safety4
```

**Resultado.** Los 17 terminan como se esperaba con ambas políticas, con la misma clasificación en las dos y 0 comandos. Grupos (`manifest.json`):

| Grupo | Escenarios |
| --- | --- |
| Planificación completada, ejecución pendiente de autorización (4) | `red_target`, `yellow_target`, `duplicate_observation`, `unassigned_objective` (con el objetivo térmico sin asignar) |
| Planificado, ejecución bloqueada (2) | `missing_localization`, `unauthorized_execution` |
| Planificación bloqueada o en espera (10) | `no_target`, `disallowed_color`, `ambiguous_detection`, `missing_depth`, `missing_camera_pose`, `wrong_frame`, `stale_observation`, `impossible_dependency`, `mission_cancelled`, `tool_error` |
| No planificado por el supervisor (1) | `supervisor_refuses` |

**Procedencia.** Los agentes son dobles programados (`DETERMINISTIC_AGENT`), no Qwen. La imagen es `SYNTHETIC_TEST`, la cámara `DECLARED_VIRTUAL` y los eventos `TEST_FIXTURE`. No hay SITL, sensor ni vehículo.

**Límite.** Los dobles nunca marcan nada como inseguro y nunca piden desactivar validadores, así que en estos 17 escenarios `safety/4` no puede diferenciarse de `safety/3`. La diferencia entre las dos políticas se mide en la batería adversarial (`tests/test_multiagent_supervisor_v3.py`).
