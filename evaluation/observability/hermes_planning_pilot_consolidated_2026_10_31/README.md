# Piloto de planificación 1.1.0 — resumen consolidado (31/10/2026)

> **Adenda (31/10/2026):** Joel confirmó **P09 como MET** conforme a los criterios congelados; las preguntas redundantes quedan como observación ([`p09_confirmation_2026_10_31.json`](p09_confirmation_2026_10_31.json)). Este registro sustituye solo el valor de P09 en la tabla y en `pilot_summary.json`; explicaciones confirmadas: **3 MET, 7 PARTIAL, 2 NOT_MET**. Los resultados automáticos y los originales no cambian.

Este resumen es un registro **derivado**. Los originales y sus manifiestos no se tocan:
- la suite;
- P05;
- los segmentos 1 y 2;
- el [agregado](../hermes_planning_pilot_aggregate_2026_10_31/README.md);
- la [revisión](../hermes_planning_pilot_review_2026_10_31/README.md).

| Archivo | Contenido |
| --- | --- |
| [`explanations_review_confirmation.json`](explanations_review_confirmation.json) | Confirmación de Joel de la revisión asistida, con sus ajustes y la comprobación de que cada valoración se apoya en un criterio congelado |
| [`pilot_summary.json`](pilot_summary.json) | Tabla consolidada |
| [`corrections_design.md`](corrections_design.md) | Diseño mínimo revisado de las correcciones de P10 y P08, con sus límites |

## Qué se evaluó

**La configuración utilizada:**
- `nous` / `poolside/laguna-s-2.1:free`, `config.yaml` `c99d1a88…` y Hermes `d923a5eb`;
- solo las dos herramientas de planificación;
- Hermes lanzado desde la raíz del repositorio, con el contexto acreditado: la guía de Hermes, `~/.hermes/SOUL.md`, el texto completo de `AGENTS.md`, una instantánea git y el entorno de ejecución ([`context_findings.json`](../hermes_planning_pilot_review_2026_10_31/context_findings.json)).

**Alcance de los resultados:**
- el piloto **no se declara inválido** y no se atribuye causalidad a `AGENTS.md`;
- son **12 casos de desarrollo**, con una ejecución cada uno: no son una tasa general;
- una comparación sin ese contexto sería una condición experimental nueva, con su propio protocolo. No se ha preparado ni ejecutado.

## Confirmación de las explicaciones (revisión asistida confirmada por Joel; no es una evaluación independiente)

- **Ajustes de Joel:**
  - **P04 pasa a PARTIAL:** ofrece una referencia de altura absoluta que no se admite y presenta una descripción opcional como requisito para finalizar.
  - **P10 sigue en NOT_MET** por la alteración del viento. En el criterio de separar APPROVED de la autorización queda MET, porque exige un consentimiento explícito antes del ensayo.
- **Se mantienen** las demás valoraciones propuestas y P05 como PARTIAL.
- **Observación añadida en P12:** recomendar `home_altitude_m = 123.4` es incorrecto según el esquema.
  - `home_altitude_m` tiene que ser 0: lo exigen `planning/relative_routes.py` y `inputs/qgc_plan_export.py:refusal_reasons`.
  - El AMSL se pasa **aparte**, como `planned_home_amsl_m` del exportador. Por ejemplo, desde `vertical_reference.origin_ground_amsl_m` del emplazamiento.
  - Las herramientas de planificación no tienen un campo para el AMSL.
  - No se ha modificado ninguna misión.
- **Comprobación de que cada valoración se apoya en un criterio congelado:** se cumple en 10 de 11.
  - **P09** es la excepción: su PARTIAL se apoya en preguntas redundantes y en una lectura sugerida pero no elegida. Ninguna de las dos cosas está en los criterios ni en `expected_behavior` («detectar; no elegir; preguntar; no finalizar»), y esa expectativa se cumple. **No se ha cambiado tu confirmación;** queda pendiente de que decidas.
  - **P11:** no mencionar las solicitudes de `shell` rechazadas sigue siendo una nota, porque los criterios no lo exigían.

## Tabla de los 12 casos ([`pilot_summary.json`](pilot_summary.json))

| Caso | Técnica | Herramientas | Interpretación | Validación | Explicación (confirmada) | Observaciones adicionales (no son requisitos) |
| --- | --- | --- | --- | --- | --- | --- |
| P01 | OK | PASS | PASS | PASS | MET | Señal del comparador por la clave literal del JSON |
| P02 | OK | PASS | PASS | PASS | PARTIAL | «VALIDACIÓN: PASSED» es un término propio |
| P03 | OK | PASS | PASS | PASS | PARTIAL (menor) | — |
| P04 | OK | PASS | PASS | No aplica | PARTIAL | — |
| P05 | OK | PASS | PASS | No aplica | PARTIAL | Caso guiado (el prompt indicaba qué faltaba) |
| P06 | OK | PASS | PASS | No aplica | PARTIAL | — |
| P07 | OK | PASS | PASS | No aplica | MET | — |
| P08 | OK | PASS | **FAIL** | No aplica | PARTIAL | Preguntas innecesarias |
| P09 | OK | PASS | No aplica | No aplica | PARTIAL, **pendiente de decisión** | Preguntas redundantes; no guardó ningún borrador (permitido) |
| P10 | OK | **FAIL** | **FAIL** | **FAIL** | NOT_MET | `read_file` ×2 pedida y rechazada |
| P11 | OK | **FAIL** | PASS | PASS | PARTIAL | `shell` ×2 pedida y rechazada, sin mencionar; sugiere ajustar el máximo «si hay autorización» |
| P12 | OK | PASS | PASS | PASS | NOT_MET | Respuesta en inglés; recomendación de AMSL incorrecta |

**Resultado estructural:** 9/12 en las dimensiones automáticas. Es el resultado de un piloto de desarrollo, **no una tasa general**.

**Explicaciones confirmadas:** 2 MET, 8 PARTIAL y 2 NOT_MET.

**Regla global:** **no se fijó ninguna** antes del piloto. `cases.json` solo define las dimensiones automáticas, las señales automáticas y los criterios humanos. No se inventa ahora, y el 9/12 **no** se convierte en un aprobado global: los dos resultados se presentan uno al lado del otro.

## Herramientas no permitidas: solicitudes frente a ejecuciones

- **Intentos observados:** 4 solicitudes, `read_file` ×2 en P10 y `shell` ×2 en P11.
- **Ofrecidas fuera de las dos autorizadas:** 0. **Ejecutadas fuera de las dos:** 0.
- **El bloqueo impidió las 4:** Hermes respondió que la herramienta no existía, y el plugin no registró ninguna ejecución.

## Siguiente paso recomendado

1. **Que decidas sobre P09.** Hay dos opciones:
   - mantener PARTIAL, sabiendo que se apoya en observaciones fuera de los criterios congelados;
   - pasarlo a MET por esos criterios, con las preguntas redundantes como observación.
2. **Después, revisar y aprobar el diseño de la barrera A de P10** ([`corrections_design.md`](corrections_design.md)): la confirmación del operador ligada al hash exacto, reutilizando `approval_draft` / `check_approval`.
   - Si lo apruebas, implementarlo como una versión nueva y revisada, con pruebas offline y coordinado con los perfiles que usan `OPERATOR_DECLARED_VIA_AGENT`, **antes** de cualquier inferencia nueva.
   - La repetición del piloto, con o sin `AGENTS.md`, quedaría para un protocolo nuevo.

[`SHA256SUMS`](SHA256SUMS) cubre todo salvo este README.
