# H4 de agri_demo_001: vista previa de Opik, NO enviada — 24/10/2026

**Estado: solo dry-run.** No se ha enviado nada, no se ha leído ninguna clave y no se ha contactado
con Opik. Los archivos de esta carpeta son las vistas previas que generó
`observability.hermes_capture_run opik-dry-run`, ejecutado sobre **copias temporales** de las
evidencias. Las evidencias de H1 y H3 no se han modificado: sus `SHA256SUMS` siguen verificando.
El CLI `observability.opik_export` sin `--send` reproduce los mismos hashes de body directamente
desde las capturas originales.

## Destino detectado

Es el ya documentado y usado en los envíos del 21/10 y el 22/10 (`docs/opik-export.md`):
- workspace `joowww`, que viaja en la cabecera `Comet-Workspace` y no en el body;
- proyecto `tfg-opik-hermes-real-20261021`;
- endpoint `https://www.comet.com/opik/api`;
- `--provenance captured`, con el registro de procedencia del plugin verificado.

## Qué se enviaría

| Captura | Traza | Spans (`llm_call`) | Eventos puntuales | Body de trazas (SHA-256) | Body de spans (SHA-256) |
| --- | --- | --- | --- | --- | --- |
| H1 `agri_planning_h1_nous_2026_10_24` | `01a16de0-bd58-73f0-bf2f-bd45f0b557fc` `hermes_turn`, 12:26:47–12:27:31 UTC | 3 | 4 `tool_call` (2 `update_mission_draft` y 2 `finalize_mission_draft`) | `bb8019dd4ba4e3255e8cf535b8aa57141d19a98c73d43a0a30d23cf6e7951ce8` | `174290900f77c2f21893fc01c2186b78b248f7bd4b22454fb546b84d931a867e` |
| H3 `agri_scenario_h3_nous_2026_10_24` | `01a16e0d-eb87-71c9-a8b6-626d08ba0e23` `hermes_turn`, 13:16:08–13:16:38 UTC | 2 | 2 `tool_call` (`get_mission_state`) | `38d0af127d10bf3c5d3d49d8cfd772a7ff3897e0c96dc1ad8b20c26e98109103` | `5ed58da0ae92abd31ba3454f5ba85fee42ff8b224abb4477518c5d1a8b229748` |

El tamaño total es de 14,5 kB (H1) y 9,1 kB (H3). No hay trazas retenidas, avisos, errores ni
bloqueos (`blocked_for_future_send_by_default: []`).

**Campos.** Solo metadatos de la captura del plugin:
- **Identificación:** `tfg_case_id` (`mcp-agri-planning-h1` o `mcp-agri-scenario-h3`) y
  `tfg_run_id`, que es la etiqueta genérica `real-hermes-20261024` y coincide en ambas capturas.
- **Llamadas al modelo:** modelo y proveedor, `api_mode`, `finish_reason`, tiempos medidos por
  Hermes (epochs, duración y desfase del primer fragmento), número de mensajes y de llamadas, y
  `context_length`.
- **Tokens:** valores normalizados por Hermes, con su estado (`zero_unconfirmed` y otros).
- **Herramientas:** nombres solicitados y, por cada llamada, nombre, estado, duración y fuente de
  la duración.
- **Referencias seudónimas** con forma `sha256:…`: sesión, turno, tarea, petición y llamada.
- **Identificadores de evento:** UUID del propio plugin.

**Revisión campo por campo** (barrido automático y lectura manual):

| Riesgo | Resultado |
| --- | --- |
| Secretos, credenciales o tokens | No hay |
| Rutas locales, usuario, correo o URL | No hay. El workspace no va en el body. |
| `session_id` en claro | No hay. Solo `tfg_session_ref` truncado (`sha256:…`): no se puede revertir, pero permite enlazar las trazas de una misma sesión. |
| Prompts, respuestas, argumentos o resultados de herramientas | No hay, incluidos coordenadas, POI, `mission_id` y hashes de misión. |
| Identificadores de H2 (secuencia, hijos) | No hay |
| Respuesta errónea de H3 (`r1_movement_authorized: true`) | **No hay.** El payload no contiene la respuesta ni el veredicto. |
| Datos no imprescindibles | `tfg_event_id` (UUID), epochs absolutos y `context_length`. Son inocuos y no se proponen redacciones. |

## H3 y su veredicto `NOT_VALIDATED`

El exportador actual **no exporta veredictos**: no tiene entrada para etiquetas de evaluación ni
para *feedback scores*. Por eso la traza de H3 aparecería en Opik como un turno normal sin error.
Eso describe correctamente lo que es: la ejecución técnica del turno, con dos consultas permitidas,
sin errores. **No es** una afirmación de que la respuesta fuera correcta, y la afirmación errónea
no viaja en el payload.

Propuesta, sin implementar:
1. **Ahora:** enviar los metadatos tal cual y mantener el veredicto en el repositorio
   (`agri_scenario_h3_nous_2026_10_24/accept_h3.json`, `hermes_stdout.txt` y su README). En la
   memoria, la traza de Opik se citaría siempre junto a ese veredicto.
2. **Después, con un cambio revisado del exportador:** añadir una entrada opcional y explícita
   del resultado de aceptación. Iría como etiqueta `acceptance:NOT_VALIDATED` y como metadato
   `tfg_acceptance = {"status": "NOT_VALIDATED", "failed_keys": ["r1_movement_authorized"],
   "source": "accept-h3"}`, sin el texto de la respuesta.
   - Cambiaría los bodies y sus hashes, y necesitaría tests y un nuevo dry-run.
   - Las *feedback scores* de Opik no están implementadas ni verificadas en este repositorio y
     no se suponen.

## Autorización necesaria para enviar (no concedida)

Cada envío es una invocación aparte de `observability.opik_export --send`:
- con la captura **original** de la evidencia, sin `--allow-*` y sin reintentos;
- con un `--record` nuevo y un `--error-body-file` fuera del repositorio;
- con la clave introducida con `read -rs` en la terminal de Joel.

La autorización debería nombrar el destino (`joowww` / `tfg-opik-hermes-real-20261021`), qué
capturas se envían (H1, H3 o ambas) y los cuatro hashes de body de la tabla. Cualquier diferencia
en esos hashes impide el envío.
