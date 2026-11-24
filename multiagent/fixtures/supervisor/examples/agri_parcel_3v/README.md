# Ejemplo reproducible: parcela con dos ArduCopter y un ArduRover (SINTÉTICO)

Generado el 24/11/2026 con la CLI del supervisor sobre `agri_parcel_3v.scenario.json`, que es un escenario sintético. **No hay ninguna ejecución SITL**: los resultados son planificación, peticiones preparadas sin enviar y el doble de pruebas, marcado como sintético.

- `plans/`: `drone_1.plan`, `drone_2.plan` y `rover.plan`. La generación es determinista; con el mismo escenario se obtienen los mismos SHA-256.
- `manifest.json`, `decisions.json`, `request.json`: manifiesto, decisiones del supervisor y petición.
- `results/global_result_after_planning.json`: `PLANNED_PENDING_APPROVAL`.
- `results/global_result_real_executors_prepared.json`: `EXECUTION_BLOCKED`. Los drones quedan en `READY_TO_REQUEST_EXECUTION` con la petición H2 preparada (`drone_h2_request.json`). El rover queda `BLOCKED` con la petición en el contrato del controlador (`rover_plan_execution_request.json`, admisión `FORMALLY_VALID_PENDING_LIVE_EVIDENCE`).
- `results/global_result_test_double_partial.json`: `PARTIAL`, con el doble de pruebas. Hay un `result.json` SafeFlight sintético (`drone_01.result.synthetic.json`).

Reproducir:

```bash
cd /home/joelm/TFG/Agentic_Drone_Mission_Control_supervisor && PYTHONPATH=$PWD /home/joelm/TFG/Agentic_Drone_Mission_Control/.venv/bin/python -m multiagent.supervisor plan --scenario multiagent/fixtures/supervisor/agri_parcel_3v.scenario.json --out ~/tfg-supervisor-runs/out --text "Planifica la inspección de una parcela agrícola utilizando dos drones y un rover. Divide el terreno en dos sectores aéreos y asigna tres puntos terrestres al rover. Todos deben regresar a su punto de origen."
```
