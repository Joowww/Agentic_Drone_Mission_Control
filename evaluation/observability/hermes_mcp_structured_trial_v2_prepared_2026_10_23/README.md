# Ensayo `failed-structured-v2` — PREPARADO, NO EJECUTADO (23/10/2026)

No se ha ejecutado Hermes, el servidor MCP por stdio ni ningún proveedor. La explicación del
contrato v2 y el recorrido del código están en el
[runbook, Recorrido 6](../../../docs/hermes-capture-runbook.md#recorrido-6-contrato-v2-y-ensayo-failed-structured-v2--preparado-23102026).

- **Caso:** `d4519cab-ebd1-4359-b547-44be38294a6a`, `FAILED` (fallo de misión, 17/10/2026). Es
  histórico; el simulador no se consulta.
- **Archivos fijados:** `report.json` `f265cf77…` (idéntico a la copia versionada
  `failed_wp3_report.json`) y `mission.json` `2366d5a2…`. No cambiaron al generar esta carpeta.
- **Sustituye a:** `failed-structured`, ejecutado el 22/10 a las 17:40 con resultado
  `FINAL_RESPONSE_NOT_AS_EXPECTED`. Aquel resultado no se modifica.

| Archivo | Contenido |
| --- | --- |
| [tool_result_external_view.json](tool_result_external_view.json) | Lo que recibirá el modelo: vista externa del esquema 2 (~2,8 KB) generada por la función real en solo lectura. El servidor MCP solo cambia los espacios. |
| [prompt.txt](prompt.txt) | Prompt fijo: el campo de origen de cada clave, sin valores esperados. |
| [answer_contract.json](answer_contract.json) | Las 11 claves con su origen, tipo y regla para `null`/ausente. |
| [expected_answer.json](expected_answer.json) | Respuesta esperada, calculada del informe bruto (`return_to_home` = `UNKNOWN`). |
| [result-expectation.json](result-expectation.json) | 29 punteros sobre el resultado real más los argumentos `run_id` y `view="external"` (`b48aa035…`). |

**Criterio de éxito (`TOOL_CALL_OBSERVED_AS_EXPECTED`)** — deben cumplirse todos:
- se ofrece solo la herramienta;
- el modelo la pide por su nombre una vez;
- hay una sola ejecución;
- los argumentos ejecutados coinciden;
- 29/29 punteros del resultado coinciden;
- 11/11 claves de la respuesta son correctas.

Un único turno no mide fiabilidad.

```bash
.venv/bin/python -m observability.hermes_capture_run capture --mcp-tool-trial --trial-case failed-structured-v2 --execute
```

`SHA256SUMS` cubre los cinco archivos de datos y este README.
