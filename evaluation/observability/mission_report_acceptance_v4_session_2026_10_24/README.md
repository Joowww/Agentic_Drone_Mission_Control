# Aceptación de la aplicación sobre la sesión real de la v4 — 24/10/2026

**Resultado: `VALIDATED`**, en el segundo intento y tras corregir un defecto de la ruta. Coincide con
el veredicto `TOOL_CALL_OBSERVED_AS_EXPECTED` del [ensayo v4](../hermes_mcp_structured_trial_v4_nous_2026_10_24/README.md).

- **Qué queda verificado:** `tools.mission_report_query accept` acepta un informe usando los
  argumentos, el resultado y la respuesta reales de una sesión **ya terminada**, obtenidos con la
  exportación local soportada de Hermes.
- **Qué no prueba:** una consulta genérica integrada de principio a fin. La entrada `ask --execute`
  está preparada pero no se ha ejecutado.

Joel autorizó esta comprobación. **No hubo inferencia ni contacto con el proveedor.**
- `hermes sessions export` lee la base local de sesiones.
- Según las fuentes de Hermes `d923a5eb48`, la comprobación de actualizaciones solo se lanza desde
  `cmd_chat` y al mostrar la versión, no desde este subcomando.
- Se exportó solo la sesión del turno v4 (`--session-id`), con 4 mensajes y un único turno de usuario.

## Los dos intentos

| Archivo | Hora (UTC) | rc | Resultado | Motivos |
| --- | --- | --- | --- | --- |
| `acceptance_check.json` | 07:24:26 | 3 | `NOT_VALIDATED` | `RESULT_NOT_AVAILABLE` |
| `acceptance_check_after_fix.json` | 07:26:48 | 0 | `VALIDATED` | — (11/11 claves `match`, contrato v3) |

Los dos usan la misma exportación: sha256 `8c16f2f6a0a97fed6940645500323b8ba70d9fe9b303a63acd5b74869c9b664d`,
21 044 bytes, rc 0. También comparten el archivo de uso (`6bd61dda…`). Ninguno de los dos registra el
`session_id` (comprobado buscando el valor real en ambos archivos).

**Causa del primer fallo.** Hermes envuelve el resultado de una herramienta MCP de 32 o más
caracteres antes de añadirlo a la conversación:
- abre con `<untrusted_tool_result source="NOMBRE">`;
- sigue un aviso fijo de "datos, no instrucciones";
- después va el contenido y el cierre `</untrusted_tool_result>`.

Lo hace `agent/tool_dispatch_helpers.py:_maybe_wrap_untrusted`, y esa forma envuelta es lo que
recibió el modelo. La ruta esperaba el sobre JSON del handler MCP sin envolver.

**Corrección mínima.**
- `tools/mission_report_query.unwrap_untrusted()` desenvuelve **solo** ese bloque exacto, con
  `source` igual a la herramienta llamada. Cualquier otro envoltorio se rechaza con
  `UNRECOGNIZED_TOOL_RESULT_WRAPPER`.
- Hay regresiones y un test de contrato contra las fuentes instaladas.
- `agent/tool_dispatch_helpers.py` (`fded1508…`) queda fijado en `TRIAL_SOURCES`.
- No se repitió ninguna inferencia.

## Versiones y hashes (en los JSON)

- **`tools/mission_report_query.py`:**
  - `42013302…` en el primer intento;
  - `2731a492…` en el segundo, que ya tiene la corrección;
  - el archivo se **amplió después** con el subcomando `ask` (hash actual distinto). La lógica de
    `accept` no cambió.
- **Fuentes del proyecto:** `mission_report_acceptance.py`, `mission_query_cases.py` y
  `mission_external_view.py` (`394d0c19…`).
- **Hermes:** commit `d923a5eb48`; hash de la fuente del envoltorio en el segundo intento.

## Cómo se ejecutó

Se llamó a `main()` en el mismo proceso, con los mismos argumentos que el comando:

```bash
.venv/bin/python -m tools.mission_report_query accept --usage-file <v4 private dir>/native-usage.json --run-id d4519cab-ebd1-4359-b547-44be38294a6a
```

El runner era `subprocess.run`, envuelto solo para calcular en memoria el hash y el tamaño de la
exportación.

**No se archiva:** el contenido exportado, el `session_id` ni su referencia, los argumentos y el
resultado de la herramienta, ni el informe.

**Alcance:** se trata de un registro histórico. La disponibilidad actual no se comprobó
(`NOT_CHECKED`) y no hay autorización operativa (`operational_authorization: false`).

`SHA256SUMS` cubre los dos JSON y este README.
