# Diseño mínimo revisado de las correcciones de P10 y P08 — SOLO DISEÑO (31/10/2026)

Este documento solo describe el diseño: no se ha implementado nada ni se ha repetido el piloto. Sustituye a la §5 de [`../hermes_planning_pilot_review_2026_10_31/README.md`](../hermes_planning_pilot_review_2026_10_31/README.md), que se conserva sin cambios.

## Límite de confianza

**Lo que afirma el agente.** Es todo lo que llega por las herramientas del agente (`update_mission_draft`, `finalize_mission_draft`):
- los valores de la misión;
- las atribuciones, incluida `OPERATOR_DECLARED_VIA_AGENT`, con su declaración;
- cualquier texto de «confirmación».

Si Hermes rellena `OPERATOR_DECLARED_VIA_AGENT`, eso **no acredita** que el operador haya confirmado nada. No es una barrera suficiente.

**Lo que está fuera del control del agente:**
- **los registros que escribe el propio entorno de Hermes, no el modelo:** la sesión con el mensaje del operador y todas las llamadas a herramientas, y las capturas del ejecutor (hash del prompt, ofertas y llamadas);
- **un registro de confirmación del operador,** escrito por una orden del operador que **no se ofrece al agente** en el perfil de planificación.

Este límite se mantiene solo mientras el perfil del agente no tenga herramientas de archivos ni de terminal capaces de escribir en ese registro. En el piloto, `read_file` y `shell` se pidieron, fueron rechazadas y nunca se ofrecieron. El límite hay que mantenerlo y comprobarlo; la configuración no lo garantiza por sí sola.

**Lo que sigue sin estar acreditado:** la identidad de quien confirma. La confirmación es una declaración ligada a hashes, no una autenticación, igual que la aprobación ya existente del paquete de escenario.

## P10: no ejecutar sobre datos declarados alterados sin confirmación del operador

**Situación actual,** comprobada en el código:
- `tools/mission_execution_gate.py:_check_mission_execution_ready` concede `execution_authorized: True` con **APPROVED y la simulación lista**;
- el perfil de planificación no ofrece herramientas de ejecución. Es una barrera de configuración, no del backend.

### A. Impedir: confirmación del operador ligada al hash exacto (barrera)

1. **Ninguna finalización hecha solo por el agente basta para ejecutar.** La puerta de ejecución exige, además de APPROVED y de que la simulación esté lista, un **registro de confirmación del operador ligado al `mission_sha256` exacto**.
2. **Se reutiliza el mecanismo existente** de `planning/scenario_instance.py`, `approval_draft` y `check_approval`, que usa `tools/scenario_package.py`. La aprobación queda ligada a los hashes y pasa a `STALE` si cambian; `approved_by` lo rellena una persona; y se documenta como «declaración, no autenticación».
   - **Qué cambia:** no se crea una plataforma; se aplica ese patrón a una finalización individual. La orden del operador genera el borrador de confirmación de un `finalization_id` y la persona lo completa.
3. **Qué ve el operador antes de confirmar:**
   - los valores efectivos y los valores por defecto;
   - **su propia petición,** tomada de la sesión o la captura, no de un resumen del agente;
   - la auditoría del punto B.

   Con eso puede comparar lo que pidió con lo que se va a ejecutar.
4. **Crear otro borrador no evita la barrera:** la misión nueva tiene otro hash, carece de confirmación y queda bloqueada igual. Cualquier cambio, sea o no sensible, queda pendiente hasta que el operador confirme ese hash concreto.
5. **El validador no cambia.** APPROVED sigue siendo el estado del software para los datos que recibió; la barrera está en la ejecución.

### B. Registrar las diferencias para auditoría (no es una barrera)

1. **Que cada finalización registre su linaje,** es decir, la diferencia campo a campo con la finalización anterior **del mismo borrador**. Se reutiliza `planning/artifact_store.structured_diff`.
2. **Agrupar por sesión,** a partir de la sesión de Hermes y de la captura: todas las finalizaciones de un mismo turno, aunque estén en borradores distintos. Esto ya lo hacen la aceptación y el informe (`turn_from_session`). Así una alteración hecha en otro borrador queda igualmente visible en la auditoría.
3. **Límite:** la auditoría muestra, no impide. Una diferencia que no esté dentro de una misma sesión o un mismo borrador puede escapar a la agrupación.

### Qué depende del agente y qué no se garantiza

- **Del agente:**
  - no alterar los valores declarados para superar la validación, aunque la petición lo pida;
  - informar del BLOCKED con sus motivos;
  - pedir el nuevo dato como una declaración aparte.

  Esto puede reforzarse en las descripciones de las herramientas o en la skill, pero sigue siendo comportamiento del modelo.
- **No se garantiza:**
  - que el operador no confirme datos alterados; en P10 fue el propio operador quien pidió el cambio. El sistema registra esa decisión y no la impide;
  - la veracidad de los valores, por ejemplo del viento real;
  - la identidad de quien confirma.
- **Alcance de la barrera:** cambiar la puerta de ejecución afecta también a otros perfiles en los que hoy se acepta una autorización declarada por el agente (`OPERATOR_DECLARED_VIA_AGENT` en las secuencias de preflight). Habría que coordinarlo antes de implementarlo.

## P08: no fijar un valor en disputa

### Qué puede garantizar el backend

Un mecanismo `unresolved_fields` en `update_mission_draft`. Mientras un campo esté marcado como contradictorio:
- cuenta como pendiente;
- no se genera la ruta;
- `finalize_mission_draft` devuelve INCOMPLETE.

Además, la confirmación del operador de P10 (punto A) haría que cualquier valor que llegue a ejecutarse pase antes por los ojos del operador.

### Lo que no garantiza

- **`unresolved_fields` solo bloquea las contradicciones que el agente registra.** No detecta las que el agente pasa por alto. En P08 el modelo guardó 5 m y tomó los 12 m como una «altitud de cámara», así que no habría marcado nada.
- **El agente puede deshacer la marca** escribiendo un valor; no es una barrera frente al agente.
- **Detectar una contradicción en lenguaje natural** depende de cómo interprete el modelo la petición. El backend no puede hacerlo.
- Por todo ello, el mecanismo **no** resuelve por completo las contradicciones en lenguaje natural.

### Qué sigue dependiendo del modelo o del operador

- **Del modelo:** ante dos valores incompatibles, no guardar ninguno o marcarlo como pendiente, y hacer una pregunta directa con ambos valores.
- **Del operador:** si el modelo no detectó la contradicción, la última defensa es revisar los valores efectivos en la confirmación del punto A. Depende de la atención humana.

## Recomendación

Implementar primero la **barrera A de P10**, porque cubre P10, el caso de un borrador nuevo y, como última defensa, P08. Sería una versión nueva y revisada del backend, con pruebas offline:
- sin confirmación: bloqueado;
- confirmación ligada al hash: permitido;
- un cambio después de confirmar: STALE;
- un borrador nuevo sin confirmación: bloqueado.

Coordinarlo con los perfiles que hoy usan `OPERATOR_DECLARED_VIA_AGENT`. El registro B y `unresolved_fields` pueden ir después.

No se ha implementado nada.
