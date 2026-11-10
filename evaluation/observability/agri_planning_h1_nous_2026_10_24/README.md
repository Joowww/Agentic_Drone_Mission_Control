# H1 de agri_demo_001: planificación real con Hermes — 24/10/2026

**Resultado: `BOUND`.** Hermes (perfil por defecto, proveedor `nous`, modelo
`poolside/laguna-s-2.1:free`) construyó y finalizó las dos misiones en **una sola invocación**
(12:26:36–12:27:32 UTC; rc 0, sin timeout ni reintento). `bind-h1` las vinculó al escenario frente
a H0. **No autoriza ningún vuelo:** `flight_authorization: NOT_GRANTED`. H1 no autoriza H2.

## Aislamiento

- Caso `agri-planning-h1` de `observability/hermes_capture_run.py`. Solo se registraron
  `update_mission_draft` y `finalize_mission_draft`, con Tool Search en `"off"`.
- `review`: `PLANNING_CALLS_WITHIN_ALLOWED_TOOLS`. Las 3 peticiones al modelo ofrecieron solo esas
  dos herramientas y no hubo errores del modelo.
- Se ejecutaron 4 herramientas, sin errores: dos `update_mission_draft` en la primera respuesta y
  dos `finalize_mission_draft` en la segunda. La tercera respuesta fue el texto final, que no se usa
  como prueba.
- El config se restauró (sha256 `c99d1a88…`) y el plugin se retiró. No quedaron procesos de Hermes
  ni del servidor MCP.

## Artefactos vinculados

Están en `h1_binding.json`: rutas relativas, SHA-256 de cada archivo de la finalización, asociación
POI→waypoint y validación.

| Dron | `mission.json` | SHA-256 | Asociación | Validación |
| --- | --- | --- | --- | --- |
| drone_01 | `missions/generated/drafts/8658f6f2-…/a4f7db20-…/mission.json` | `321ad647ab9c2af536905d541675580df20e0e7a5e9be129841c8f894166b30d` | POI_A1→WP1, POI_A2→WP2 | FEASIBLE / APPROVED |
| drone_02 | `missions/generated/drafts/4707cbd6-…/f505f7ad-…/mission.json` | `079e25a302423996f168b65c8b2e03157fda0c9ad9b743fb64e8ea7b8c955472` | POI_B1→WP1, POI_B2→WP2 | FEASIBLE / APPROVED |

**Diferencias con H0.** La geometría no cambia: mismos desplazamientos N/E respecto al lanzamiento
de cada vehículo, misma altura de 5 m y regreso al lanzamiento. Solo cambian campos de identidad y
metadatos:
- `mission_id` y `name`;
- `objective.description` es nulo;
- los waypoints se llaman `WP1`/`WP2`;
- la velocidad por waypoint es nula, frente a 10 km/h en H0;
- `source` es `natural_language`;
- `distance_km` y `bearing_deg` aparecen como nulos.

**Primer intento de vinculación: `NOT_BOUND`.** El motivo fue un defecto de lectura, no un problema
de los artefactos. Hermes entrega la salida MCP como `{"result": "<JSON>"}` y `finalized_artifacts`
no la desenvolvía. Se corrigió reutilizando `_result_document`, con una regresión, y se volvió a
vincular **la misma sesión** en modo de solo lectura, sin invocar de nuevo a Hermes.

## Archivos

- `capture/`, `capture_summary.json`, `run.json` y `native_usage_review*.json`: los genera
  `review`, sin prompts del modelo, argumentos ni resultados.
- `h1_binding.json`: no contiene `session_id` ni rutas absolutas.
- `SHA256SUMS` cubre todo salvo este README.
- Las finalizaciones se conservan intactas en `missions/generated/drafts/` para su futura
  aprobación. **No se ha simulado ni volado.**
