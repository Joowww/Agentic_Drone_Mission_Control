# Primer envío a LangSmith: fixtures SINTÉTICOS del loader (20/10/2026)

**Datos sintéticos, no una captura real de proveedor ni un baseline de rendimiento o gasto.**
Envío único autorizado por Joel. Sin reintentos (transporte `Retry(total=0)` y un solo intento
del SDK por run). No se ejecutaron modelos, Hermes, MCP ni simulación.

- **Destino:** `https://eu.api.smith.langchain.com` (cuenta EU), proyecto `tfg-synthetic`.
- **Clave:** tipo *tracing-only* (`lsv2_tr_`), cargada sólo en un entorno `env -i` desde
  `~/.config/tfg-langsmith/synthetic.env` (archivo 0600, directorio 0700). Nunca se imprimió
  ni se copió; 0 apariciones en el informe y en stderr (`secret_scan.txt`). Sin `LANGSMITH_TRACING`.
- **Entrada:** [evidencia sintética del loader](../hermes_loader_hooks_synthetic_2026_10_20/),
  `hermes-events-2026-10-20.jsonl` (`input.sha256`, igual que su manifiesto).
- **Plan revisado antes de enviar:** `dry_run.json` y `dry_run_summary.txt`: 6 eventos, 1 traza
  con 4 runs y 1 evento puntual, y 2 trazas sin intervalo medido retenidas (no enviadas).
- **Resultado** (`send_report.json`, `send.rc`): rc=0, `posted=4`, `conflict_reported=0`,
  `completed_traces=1`, `failed_trace=null`, `withheld_untimed_traces=2`, stderr vacío.
  `posted` significa que cada `POST /runs` volvió sin error. No se ha comprobado leyendo de
  LangSmith, porque la clave tracing-only no puede leer, y no se ha observado la interfaz.
- **Ids** (`sent_ids.txt`): traza raíz `bec45370-184e-5b66-b211-6ad75481eb5e`; runs `llm`
  `d7d8d043-a1fc-51f0-9a9a-b17e2a684089`, `1665c78e-84b2-5793-98a7-89f03254f189` y
  `c875087f-df7a-52e8-9a8f-6fab97f540b0` (`llm_error`).
- **Ledger:** `~/tfg-langsmith/ledger-tfg-synthetic-20261020.jsonl`, SHA-256 en `ledger.sha256`,
  copia exacta en `ledger_copy.jsonl` (sólo ids, proyecto y resultado, sin secretos).
- **Intervalo artificial aceptado:** la raíz y el `llm_error` abarcan unos 3 días por el
  `api_start_time` sintético fijo del fixture.

`manifest.json` lista el SHA-256 y el tamaño de todos los archivos de esta carpeta, salvo él mismo.
