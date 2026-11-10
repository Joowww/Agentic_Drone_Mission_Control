# Batería de integración offline: 18 misiones (07/11/2026, `4311c7481`)

**Cómo se genera:** `python -m multiagent.integration_battery --snapshot <dir> --out <dir>`.

**Qué recorre cada misión.** Los módulos reales de punta a punta:
1. supervisor, Drone Agent y Rover Agent **programados** (`DETERMINISTIC_AGENT`: **no son Qwen**; la ejecución con Qwen real es M4c-r1, y `python -m multiagent.demo --replay` la reproduce);
2. `safety/4` y validadores;
3. imagen `SYNTHETIC_TEST` y detector;
4. geometría y compuerta de percepción;
5. coordinador;
6. solicitud de ejecución y marcos sitio → `odom`;
7. código real de Codex (adaptador y validador v2, y admisión de su executor), desde un *snapshot* de `57a0e303a`;
8. adaptador dry-run;
9. vuelta al mismo coordinador con el resultado estructurado del traspaso.

**Resultado.** Las 18 misiones salen como se esperaba (`summary.json`) y ninguna emite un comando.
- Con objetivo válido y todo acreditado en el *fixture*, el resultado es `READY_TO_SUBMIT_EXECUTOR_POLICY_BLOCKED`, y el coordinador queda en `EXECUTION_BLOCKED`, nunca en ejecución.
- Sin localización, sin transformación válida, sin autorización o con el plan caducado, el traspaso sale bloqueado antes de enviarse.
- Un STOP incierto deja la misión en `UNKNOWN`.

**Procedencia.** Todos los datos son `TEST_FIXTURE` o `SYNTHETIC_TEST`. Los límites humanos y la autorización son de *fixture*: no hubo ninguna aprobación humana, y no hubo SITL ni vehículo.
