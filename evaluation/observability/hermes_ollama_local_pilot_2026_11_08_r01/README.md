# Hermes + Ollama local planning pilot r01 (08/11/2026) — FALLIDO

**Tipo: FALLIDO (REAL).** Primer piloto registrado del caso `local-planning-demo`: Hermes Agent `d923a5eb`
con el perfil aislado `tfg-demo-local`, modelo local `qwen3-4b-instruct-64k` (Qwen3 4B Instruct 2507
Q4_K_M, contexto 65 536) servido por Ollama 0.34.2 en `127.0.0.1:11435` (instancia propia con
`OLLAMA_FLASH_ATTENTION=1` y `OLLAMA_KV_CACHE_TYPE=q4_0`, 100 % GPU) y el servidor MCP de solo
planificación `tfg-demo-planning` (código del commit `1048fd00c`). Sin red externa, sin simulador, sin vehículos.

## Qué ocurrió

| Turno | Llamadas al LLM | Herramienta | Resultado |
| --- | --- | --- | --- |
| 1 (faltan los tres límites de seguridad) | 2 (7,4 s y 1,0 s) | `update_mission_draft` → `tool_error` (21 ms) | El modelo puso el viento actual (0 km/h) en `maximum_wind_speed_kmh` e inventó `draft_id: "draft-001"`; el esquema rechazó `maximum_wind_speed_kmh = 0` (debe ser > 0) y no se guardó nada. La respuesta al operador atribuye mal el error («el viento debe ser mayor que 0») |
| 2 (aporta los límites y pide finalizar) | 2 (2,0 s y 2,1 s) | `update_mission_draft` → `ok` para Hermes, `ERROR` del proyecto (71 ms) | Reutilizó `draft-001`; el backend lo rechazó por no ser un UUID. Sin borrador, sin finalización |

- Herramientas ofrecidas en las 4 peticiones: solo `mcp__tfg_demo_planning__update_mission_draft` y
  `…finalize_mission_draft`. No se ofreció ni se ejecutó ninguna otra.
- `finalize_mission_draft` no se llamó. No existe `mission.json` ni `finalization.json` de este piloto.
- Veredicto de la revisión: `PLANNING_CALLS_NOT_AS_EXPECTED`.

## Diagnóstico

Fallo de **interpretación del modelo**, no de memoria (100 % GPU, 5,6 GB), latencia (11–16 s por turno),
formato de llamadas (las dos llamadas son JSON válido con `finish_reason: tool_calls`) ni configuración (21
comprobaciones del perfil superadas). Factores que contribuyen:

- `MissionPlanDraft` no describe sus campos: el modelo solo ve nombres como `wind_speed_kmh` y
  `maximum_wind_speed_kmh`;
- `draft_id` es un texto opcional sin descripción;
- según el código de Hermes `d923a5eb`, las `instructions` del servidor MCP no se añaden al prompt
  (inferido: no se usan tras el *handshake*; el prompt de sistema no se guarda en la sesión).

La validación determinista hizo su trabajo: el dato inventado no se guardó.

## Consecuencia

Con autorización de Joel, el servidor de demo añade una guía explícita a las descripciones de sus dos
herramientas (mismo esquema de argumentos, mismo backend) y se ejecuta un segundo piloto, r02, con los
mismos dos prompts registrados.

## Contenido

`capture/` (eventos, ofertas de herramientas y procedencia del plugin), `capture_summary.json`,
`outcome.json`, `planning_result.json` (vacío: no hubo borradores), `turn-1.json`, `turn-2.json`,
`answer-turn-*.txt` (respuesta final de Hermes, con `~` en lugar del directorio personal),
`native-usage-turn-*.json`, `opik_dry_run.json` (proyecto `tfg-hermes-local-demo`, workspace
`local-dry-run`: 2 trazas y 4 spans, **no enviado**) y `view.html` (vista estática local). Manifiesto:
`SHA256SUMS`. Registro sellado: no se modifica ni se regenera.
