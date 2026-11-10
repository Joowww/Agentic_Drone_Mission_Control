# Retiro administrativo puntual — verificación offline, 19/10/2026

Ninguna preparación/aplicación operativa ni liberación real. Sin Docker/ROS,
MCP operativo, simulador, vuelo, staging, commit ni push. Las nuevas pruebas usan
los bytes archivados del caso en directorios temporales y dobles para todas las
observaciones operativas y el lanzamiento de procesos.

## Material conservado

- `operator_events_observation.json`: observación aportada por Joel: consulta
  histórica de docker events vacía con código 0. No contiene argumentos exactos
  ni salida terminal original; no se infiere ausencia de actividad.
- `preservation_baseline.json` y `preservation_check.json`: 529 archivos anteriores
  conservados sin cambios y las 16 versiones/ausencias de la política contrastadas.
  Reservas reales y resultados históricos intactos. No se creó una operación real.
- `tests_first.txt`: 39 passed in 7.15s, desarrollo inicial antes de ampliar casos.
- `tests_affected.txt`: 111 passed in 15.63s, ejecución intermedia.
- `tests_affected_final.txt`: 112 passed in 15.31s, subconjunto final afectado.
- `tests_full.txt`: 601 passed in 44.11s, suite completa final.
- `syntax.json`: compile de 30 archivos Python pendientes, 5 Bash con bash -n y
  observador Python embebido sin importar/ejecutar ROS.
- `whitespace.json`: git diff --check y comprobación de archivos nuevos. Los nueve
  archivos con avisos son evidencias brutas anteriores, preservadas byte por byte;
  código/documentación nuevos sin avisos.
- `manifest.json`: rutas relativas, bytes y SHA-256 de este archivo de evidencias,
  excluido el propio manifiesto.

La propuesta fija se conserva intacta en
`evaluation/operations/administrative_retirement_c6eeb645_proposal_2026_10_19.json`,
SHA-256 `32eb6f31ae191174136fa6bf054beb5071f4625d2f6fbcff61209d213c76d99a`.
La implementación nueva no cambia su estado documental histórico ni los informes
PASSED/ERROR/UNCONFIRMED. No se reutiliza una inspección caducada como autorización.

## Reproducción offline

Suite completa desde la raíz del repositorio:

```bash
.venv/bin/python -m pytest -q
```

Pruebas específicas nuevas (también incluidas en esa suite):

```bash
.venv/bin/python -m pytest -q tests/test_legacy_administrative_retirement.py
```

Los tests ejercitan esquemas/dispatch registrados, exclusión con barreras
deterministas, rechazos por cambio/identidad, caducidad, consultas sin efectos,
fallos parciales de persistencia y recuperación explícita idéntica. No prueban
obediencia de Hermes, continuidad histórica del endpoint ni un retiro operativo.

Guía y prompts para una futura decisión del operador:
[administrative-retirement-c6eeb645.md](../../../../docs/administrative-retirement-c6eeb645.md).
El estado final administrativo, si Joel lo autoriza y las comprobaciones pasan,
será ADMINISTRATIVELY_RETIRED_UNVERIFIED; no acredita aterrizaje, éxito o terminación
verificada del entorno original, ni autoriza nuevos vuelos/lifecycle.
