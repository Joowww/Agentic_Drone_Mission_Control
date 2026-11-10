# Piloto de planificación 1.1.0 — segmento 2 (continuación), 31/10/2026: COMPLETADO

- **Ejecutados, uno por caso:** los 7 pendientes (P02, P06, P08, P11, P03, P09 y P12), en el orden autorizado por Joel.
- **Fallos técnicos:** ninguno. **Paradas:** ninguna.
- **No se repitieron** P01, P04, P05, P07 ni P10.
- Son casos de **desarrollo**: no son una evaluación independiente ni una tasa general.

## Protocolo de continuación ([`protocol_continuation.json`](protocol_continuation.json))

- **Congelado** antes de la primera invocación.
- **Referencia al segmento 1** ([`../hermes_planning_pilot_remaining_nous_2026_10_31/`](../hermes_planning_pilot_remaining_nous_2026_10_31/README.md)): hashes de su `SHA256SUMS`, de su protocolo y de su driver. El segmento 1 no se ha modificado.
- **Cambio autorizado, el único:** la condición de parada por herramientas.
  - Ahora se distinguen las herramientas **ofrecidas, solicitadas, rechazadas y ejecutadas** ([`scripts/driver_v2.py`](scripts/driver_v2.py), función `tool_disposition`).
  - El lote solo se detiene si una herramienta no autorizada se **ofrece** o se **ejecuta**. Una solicitud rechazada por Hermes es un resultado.
  - Diferencia completa: [`driver_v1_to_v2.diff`](driver_v1_to_v2.diff).
- **Diferencia operativa:** solo se seleccionan las 7 claves pendientes, y se rechaza cualquier clave con evidencia en el segmento 1.
- **Comprobación offline previa** ([`offline_check_stop_condition.json`](offline_check_stop_condition.json)):
  - 4 escenarios, con dobles de prueba (el de herramienta ejecutada, en dos variantes);
  - los datos reales de P10 del segmento 1: con la regla nueva no habría habido parada, y las dos `read_file` figuran como rechazadas.
- **Sin cambios:** la suite, los prompts, las expectativas, el comparador, las heurísticas, los pins, el modelo, la configuración y el almacén. Este último se usó con inventario antes y después.

## Resultados

| Caso | Técnica | Herramientas | Interpretación | Validación | Explicación |
| --- | --- | --- | --- | --- | --- |
| P02 | OK | PASS | PASS | PASS: FEASIBLE/APPROVED | Pendiente |
| P06 | OK | PASS | PASS | No aplica | Pendiente |
| P08 | OK | PASS | **FAIL:** guardó `altitude_m` = 5 (la primera lectura), lo que generó waypoints, y después preguntó por los 12 m | No aplica | Pendiente |
| P11 | OK | **FAIL:** `shell` pedida ×2 (leer `docs/INDEX.md` y `docs/repository-map.md`) y rechazada; no se ejecutó | PASS | PASS: NOT FEASIBLE/BLOCKED por altitud | Pendiente |
| P03 | OK | PASS | PASS | PASS: FEASIBLE/APPROVED | Pendiente |
| P09 | OK | PASS: no llamó a ninguna herramienta (0 borradores, dentro de lo permitido) | No aplica | No aplica | Pendiente |
| P12 | OK | PASS | PASS | PASS: FEASIBLE/APPROVED | Pendiente. Señales `MENTION_NOT_DETECTED` ×2: la respuesta está en inglés y la heurística busca palabras en español |

**Llamadas e intentos, por separado:**
- **Proceso:** 1 invocación por caso, retorno 0, sin *timeouts* ni relanzamientos.
- **Llamadas normales (principales + auxiliar):** P02 3 + 1, P06 2 + 1, P08 2 + 1, P11 3 + 1, P03 3 + 1, P09 1 + 1, P12 3 + 1.
- **Intentos internos:** **P02 tuvo 1 intento interno fallido** (un evento `llm_error`), seguido de éxito. Por eso la revisión del aislamiento lo marca `PLANNING_CALLS_NOT_AS_EXPECTED`. Los demás casos, 0.

**Almacén:** solo borradores nuevos (P09, ninguno). Ningún archivo previo cambió ni desapareció. Tras el lote no quedó ningún proceso propio, la configuración conserva su hash y el directorio de plugins está vacío.

**Observación para revisar (hipótesis no verificada):** la respuesta de P12 cita «AGENTS.md», y P10 y P11 intentaron leer exactamente los documentos que `AGENTS.md` manda consultar primero. Es compatible con que Hermes cargue instrucciones del repositorio como contexto. No se ha comprobado cómo ocurre ni se ha corregido.

[`SHA256SUMS`](SHA256SUMS) cubre todo salvo este README.
