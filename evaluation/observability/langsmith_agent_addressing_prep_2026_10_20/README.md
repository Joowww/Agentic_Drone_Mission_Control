# Preparación del envío por agente/entorno (20/10/2026) — NADA ENVIADO

Preparación offline para la siguiente prueba sintética contra el agente `tfg-synthetic`, entorno
`local`, región EU. No se ha enviado ningún run, no se ha creado ninguna clave y no se ha
ejecutado Hermes, ningún modelo ni la simulación.

## Por qué

El primer envío ([langsmith_first_synthetic_send_2026_10_20](../langsmith_first_synthetic_send_2026_10_20/))
usó `project_name="tfg-synthetic"` (campo `session_name`), es decir, un proyecto de trazas y no el
agente. Según la documentación oficial, una traza va a un agente o a un proyecto, nunca a ambos.
El agente `tfg-synthetic` aparece vacío en Local y Production. Dónde aparece en la interfaz
basada en agentes una traza dirigida a un proyecto no está documentado ni verificado.

## Dependencias

- La documentación oficial (*Log traces to an agent*) exige `langsmith>=0.14.9`. La versión
  instalada era 0.14.1. Que su código tuviera parámetros experimentales `agent_id`/`agent_environment`
  no la convertía en una versión soportada para esta función.
- `pip install --dry-run` sólo resolvía `langsmith 0.14.11` (`pip_dry_run_resolution.json`).
  Actualizado en la `.venv` a **0.14.11**: `pip_freeze.diff` muestra que sólo cambia `langsmith`
  y `pip check` no encuentra dependencias rotas.
- `requirements-observability.txt` pasa a `langsmith>=0.14.9,<0.15`.

## Comportamiento comprobado en 0.14.11

- Un agente se direcciona con un `AgentAddress` `{"kind": "AGENT", "id", "environment"}` que viaja
  como `address: "lrn:agents/<id>/environments/<entorno>"`, sin `session_name`/`session_id`.
  `project_name` y `address` en la misma llamada se rechazan.
- Si el destino sale del entorno y es inválido, `create_run` descarta el run sin error. El
  exportador siempre pasa el destino explícito en código, así que esa ruta no se usa.
- Siguen igual: 409 ignorado en `POST /runs`, `now()` cuando falta `start_time`, el guard de
  `omit_traced_runtime_info` y `Retry(total=3)` por defecto, que el exportador sustituye por `total=0`.

## Archivos

- `dry_run_agent_local.json` y `dry_run_agent_local_summary.txt`: plan para
  `lrn:agents/tfg-synthetic/environments/local`. Son 6 eventos, 1 traza con 4 runs y 1 evento
  puntual, todos `SYNTHETIC`, y 2 trazas sin intervalo retenidas. Los ids son nuevos, distintos de
  los del primer envío, porque el destino forma parte de la clave.
- `offline_payload_preview_agent_local.json`: **vista previa offline, no una captura HTTP.** Es el
  `Client` real de 0.14.11 sobre una sesión HTTP falsa, sin red. Cada uno de los 4 `POST /runs`
  lleva sólo `address: lrn:agents/tfg-synthetic/environments/local`, y no contiene la clave.
- `offline_reconstruction_first_send_sdk_0.14.1.txt`: **reconstrucción offline** del payload del
  primer envío, hecha después con 0.14.1. No es la petición histórica, que no se registró.
- Dependencias: `pip_freeze_before.txt`, `pip_freeze_after.txt`, `pip_freeze.diff`,
  `pip_dry_run_resolution.json`, `pip_check.txt` y `langsmith_version.txt`.

`manifest.json` lista el SHA-256 de todo salvo él mismo.
