# Barrera de autorización — verificación offline del 20/10/2026

No se ejecutaron retiros, preparaciones ni consultas operativas. No se modificó
runtime, informes, reservas ni la nota/evidencias del incidente. Los tests usan
temporales y dobles; ninguna llamada MCP se envió a un servidor operativo.

- `tests_affected.txt`: **101 passed in 10.72s**, pruebas finales afectadas.
- `tests_full.txt`: **613 passed in 26.86s**, suite completa.
- `syntax.json`: compile de cuatro archivos Python, sin ejecutar/importar controles.
- `confirmation_protocol_review.json`: rutas/hashes del código local de cliente/SDK
  inspeccionado, resultados y límites; sin credenciales ni confirmación de UI viva.
- `preservation_baseline.json` y `preservation_check.json`: **663 archivos anteriores**
  contrastados por SHA-256, todos sin cambios. Incluyen artefactos del retiro ya
  completado, archivos de guard históricos y nota de auditoría.
- `whitespace.json`: git diff --check y archivos nuevos. Evidencias brutas previas
  conservan sus nueve avisos históricos de espacios; no se normalizan.
- `manifest.json`: bytes y SHA-256 de este directorio, excepto el propio manifiesto.

Los tests de persistencia existentes sustituyen expresamente el nuevo verificador
por un doble para mantener cobertura del motor transaccional. No prueba un canal
humano operativo. Los tests nuevos restauran la barrera de producción: aun una
declaración fresca con IDs exactos queda bloqueada. Recarga, timeout y texto
reconstruido no la habilitan. Resultado legacy completado se lee sin repetirse.

Reproducción de los afectados:

```bash
.venv/bin/python -m pytest -q tests/test_retirement_confirmation.py tests/test_legacy_administrative_retirement.py tests/test_reconciliation_mcp.py tests/test_hermes_mcp_server.py tests/test_legacy_binding_review.py tests/test_simulation_lifecycle_exclusion.py tests/test_sequence_lifecycle_exclusion.py
```

Suite completa:

```bash
.venv/bin/python -m pytest -q
```

El estado de producción es aplicación/recuperación mutantes deshabilitadas:
no hay verificador humano integrado. La vinculación estructural por ID/hash no
autentica a Joel ni corrige retrospectivamente el incidente. Guía vigente:
[revisión del protocolo](../../../../docs/retirement-confirmation-2026-10-20.md).
