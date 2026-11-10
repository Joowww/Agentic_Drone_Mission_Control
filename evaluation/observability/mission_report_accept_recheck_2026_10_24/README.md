# Nueva comprobación de `accept` sobre la sesión del `ask` real — 24/10/2026

**Resultado: `VALIDATED`** (rc 0, sin motivos, 11/11 claves `match`, contrato v3, respuesta
`FENCED_JSON_OBJECT`), tras corregir el defecto que hizo fallar la orden integrada.

Qué queda acreditado, y qué no:

1. **El `ask` real falló al emitir el informe.** Fue a las 07:35 UTC (rc=1, sin veredicto). Esa
   evidencia se conserva intacta en
   [mission_report_ask_integrated_2026_10_24](../mission_report_ask_integrated_2026_10_24/README.md).
2. **La corrección pasó el recorrido completo con dobles:** captura (ejecutor doble), exportación
   (CLI de Hermes doble), aceptación y salida final, con una respuesta en bloque ```json. El
   resultado fue rc 0, `VALIDATED` y el mismo informe que con JSON limpio. Ver los tests de
   `tests/test_mission_report_query.py`; las regresiones fallan con el código anterior.
3. **`accept` se volvió a comprobar sobre la sesión real ya existente** de ese `ask`, sin nueva
   inferencia.
4. **El `ask` corregido aún no se ha ejecutado con una nueva inferencia real.**

## Ejecución

```bash
.venv/bin/python -m tools.mission_report_query accept --usage-file ~/tfg-hermes-capture-private/20261024T073531Z/native-usage.json --run-id d4519cab-ebd1-4359-b547-44be38294a6a
```

- Se llamó a `main()` en el mismo proceso, con esos argumentos. El runner era `subprocess.run`,
  envuelto solo para calcular en memoria el hash de la exportación.
- **Exportación** con `hermes sessions export`: rc 0, una sesión, 21 121 bytes, sha256 `81e603c5…`.
  - Difiere de la del turno v4 porque esta es la sesión de **otro** turno, el del `ask`.
- **Archivo de uso:** el `native-usage.json` de esa misma invocación (hash en el JSON).
- **Fuentes:** `tools/mission_report_query.py`, `observability/mission_report_acceptance.py` y
  `observability/mission_query_cases.py` con la corrección. Hashes en `accept_recheck.json`.
- **Respuesta:** la que dio el modelo en aquel turno, leída de la sesión. No se consultó el registro
  para sustituir el resultado real.

## Archivos

- `accept_recheck.json`: versiones y hashes, código de salida, hash de la salida emitida, veredicto,
  motivos, clasificaciones por clave y alcance.
- **No se archivan:** el contenido exportado, el `session_id` ni su referencia, los argumentos y el
  resultado de la herramienta, ni los valores del informe. Se comprobó que el `session_id` real no
  está ni en la salida emitida ni aquí, y que no hay rutas `/home/`.
- **Alcance:** registro histórico; disponibilidad actual `NOT_CHECKED`; sin autorización operativa.
- `SHA256SUMS` cubre `accept_recheck.json` y este README.
