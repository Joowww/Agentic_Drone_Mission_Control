# Comparación experimental y rúbrica de explicaciones — 26/10/2026

Archivos generados por `reporting/agri_experiment_comparison.py` a partir de las evidencias
conservadas:
- sin inferencias ni reevaluación: cada aceptación es la registrada en su momento;
- sin modificar ninguna evidencia original.

| Archivo | Comando | Contenido |
| --- | --- | --- |
| [`comparison.md`](comparison.md) y [`comparison.json`](comparison.json) | `comparison --out … --json …` | Herramientas, respuesta, formato, exactitud con denominadores, errores críticos, explicación, tiempos y tokens de H1, H3 y H3b; la ejecución H2; el piloto con su protocolo y su enmienda separados |
| [`explanation_rubric_review_sheet.md`](explanation_rubric_review_sheet.md) | `review-sheet --out …` | Rúbrica de 7 criterios (retrospectiva) y hoja de revisión humana **pendiente**, con los textos literales, sus hashes y sus referencias |

H3, H3b y el piloto **no** se agregan en una tasa global. Las observaciones asistidas se citan por
referencia y nunca cuentan como revisión de Joel.

El uso, el guion de la demostración y las preguntas de defensa están en
[docs/agri-demo-defense.md](../../../docs/agri-demo-defense.md). El generador nunca sobrescribe: se
regenera en archivos nuevos.
