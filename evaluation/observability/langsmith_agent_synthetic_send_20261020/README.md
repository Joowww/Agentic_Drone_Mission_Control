# Envío sintético al agente `tfg-synthetic`, entorno `local` (20/10/2026)

**Fixtures SINTÉTICOS del loader; no es una captura real de proveedor ni un baseline.** Única
ejecución autorizada por Joel. Sin reintentos (transporte `Retry(total=0)` y un intento del SDK
por run). No se ejecutaron modelos, Hermes, MCP ni simulación.

- **Destino:** `https://eu.api.smith.langchain.com`, `address: lrn:agents/tfg-synthetic/environments/local`
  (sin `project_name`/`session_name`).
- **SDK:** `langsmith 0.14.11` (`langsmith_version.txt`). Exportador versión 3.
- **Clave:** la misma tracing-only local, cargada sólo en un `env -i` desde un archivo 0600. Nunca
  se imprimió ni se copió; 0 apariciones en el informe y en stderr (`secret_scan.txt`). Sin `LANGSMITH_TRACING`.
- **Entrada:** `input.sha256`, igual que en la evidencia del loader y en la preparación.
  `pre_send_dry_run.json` confirma, justo antes del envío, los mismos 4 ids que el dry-run revisado
  en [la preparación](../langsmith_agent_addressing_prep_2026_10_20/).
- **Resultado** (`send_report.json`, `send.rc`): rc=0, `posted=4`, `conflict_reported=0`,
  `completed_traces=1`, `failed_trace=null`, `withheld_untimed_traces=2`. `send.stderr` sólo contiene
  el `LangSmithBetaWarning` del SDK.
- **Lo que confirma el SDK:** cada `POST /runs` volvió sin excepción. En esta ruta el SDK lanza una
  excepción ante cualquier error HTTP salvo 409 (un 403 de workspace sin direccionamiento por agente
  también lanzaría), y no guarda el código ni el cuerpo de la respuesta. No confirma que los runs
  se hayan procesado ni dónde aparecen: no se leyó nada de vuelta (la clave tracing-only no puede)
  y la interfaz no se ha observado.
- **Ids** (`sent_ids.txt`): raíz `a9b215b9-8ea1-52e0-84a4-e8acbacab2e3`; runs `llm`
  `72923aae-a642-5880-a3f9-20d6f1e5d0fd`, `cd77e897-c75d-5a36-b3c8-67e97920d1b4` y
  `dfa445c4-6ea1-5854-9b26-e39ebf068f98` (`llm_error`). Retenidas sin enviar: 2 trazas sin intervalo.
- **Ledger:** `~/tfg-langsmith/ledger-agent-tfg-synthetic-local-20261020.jsonl`, SHA-256 en
  `ledger.sha256`, copia exacta en `ledger_copy.jsonl`.
- La evidencia y el ledger del [primer envío](../langsmith_first_synthetic_send_2026_10_20/) se
  verificaron intactos después de este envío.

`manifest.json` lista el SHA-256 y el tamaño de todo salvo él mismo.
