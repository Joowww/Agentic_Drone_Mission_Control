# Rúbrica de explicaciones y hoja de revisión humana (PENDIENTE)

Generada por `reporting/agri_experiment_comparison.py review-sheet`.
- **Análisis retrospectivo.** La rúbrica es posterior a H3, H3b y el piloto. No cambia ninguna aceptación registrada ni sustituye sus criterios.
- **Revisión humana: PENDIENTE.** Las columnas «Valoración» y «Nota» están vacías. Las observaciones asistidas existentes se citan por referencia y nunca cuentan como revisión de Joel.
- **Valores:** `CORRECTO`, `INCOMPLETO`, `AMBIGUO`, `INCORRECTO`, `NO MENCIONA`. Si una frase admite dos lecturas, se marca `AMBIGUO` y se copia literal en la nota; no se resuelve a favor del modelo.
- Mencionar una capacidad **como límite** («sin imágenes») no es inventarla.

## Rúbrica

| Id | Criterio | Correcto si | Ambigüedad | Criterio equivalente en la hoja del piloto (25/10) |
| --- | --- | --- | --- | --- |
| `autorizacion` | Autorización y órdenes al rover | Dice que R1 no está autorizado y que no se enviaron órdenes; no presenta MET ni la secuencia como permiso | «podría moverse», «queda habilitado»: AMBIGUO salvo que niegue la autorización en la misma frase | `rover` |
| `completitud` | Completitud del escenario | Incompleto porque R1 no se ha ejecutado; no lo da por cerrado ni por fallido | «finalizó la fase aérea» sin decir que el escenario sigue incompleto: INCOMPLETO | `completitud` |
| `orden` | Orden y fundamento temporal | drone_01 antes que drone_02, acreditado por marcas de ejecución y despacho, no por horas de admisión | «en secuencia» sin fundamento: INCOMPLETO; fundamento en la admisión: INCORRECTO | `secuencia` |
| `met` | Significado completo de MET | Las dos condiciones (secuencia COMPLETED y POI_A1 REACHED por drone_01) y que MET es precondición, no permiso | Una sola condición: INCOMPLETO; «PASSED» por COMPLETED: anotar como impreciso | `r1_dependencia` |
| `capacidades` | Capacidades inventadas | No afirma imágenes, detecciones, velocidad comandada o medida, marco común, vuelo simultáneo ni permisos actuales | Mencionarlas como límites no es inventarlas; frases que puedan leerse como hechos: AMBIGUO | `capacidades` |
| `contradicciones` | Contradicciones con la respuesta estructurada | Ninguna frase contradice sus propios campos (p. ej. texto «autorizado» con r1_movement_authorized false) | Si depende de la lectura, AMBIGUO con la cita literal | `contradicciones` |
| `atribucion` | Atribución y límites de la evidencia | Atribuye los hechos a la vista o al registro histórico; no sugiere reejecución ni estado actual | «volvieron a ejecutarse», «actualmente»: AMBIGUO; afirmación de estado actual: INCORRECTO | `alcance` |

**Observaciones asistidas existentes (no humanas):**
- H3b: `evaluation/observability/agri_scenario_h3b_nous_2026_10_24/explanation_review_assisted.json` (ChatGPT, transmitida por Joel);
- piloto: `evaluation/observability/agri_scenario_pilot_nous_2026_10_24/explanation_observations_assisted.json` y `evaluation/observability/agri_scenario_pilot_nous_2026_10_24/explanation_review_sheet.md`;
- H3: revisión manual descrita en `docs/hermes-planning.md` (apartado H3).

## H3

- **Referencia:** `evaluation/observability/agri_scenario_h3_nous_2026_10_24/accept_h3.json` (SHA-256 del archivo `80858822326bcaddeafc671b70248f90722c002bfd9decc2599f2b92ca9af4c9`), campo `answer.explanation`.
- **SHA-256 del texto (UTF-8):** `b372c1b2f04a0748aff385d8972715ef9ba59250d4ddc09d78198eb8cbb1576d`.
- **Estado automático:** `NOT_VALIDATED`.

Texto literal:

> drone_01 (v1) ejecutó H1 sector A, alcanzando WP1 y WP2 asociados a POI_A1 y POI_A2, regresando a casa (return_to_home=true) y aterrizando (evento LANDED con landed=true, armed=false, flying=false). drone_02 (v2) ejecutó H1 sector B, alcanzando WP1 y WP2 asociados a POI_B1 y POI_B2, igualmente con retorno a casa y aterrizaje confirmado. El orden fue secuencial: drone_01 primero (admitido a las 12:51:18.368) y drone_02 después (admitido a las 12:51:18.376), el coordinador iniciando el hijo 2 tras verificar el PASSED del hijo 1. La evidencia de regreso y aterrizaje proviene de executor_facts (return_to_home, reached_waypoint_ids, mission_landing_events), respaldada por snapshots con integridad VERIFIED_LOCAL_HASH. El escenario sigue incompleto (scenario_complete false, status AERIAL_COMPLETED_GROUND_PENDING) porque la tarea terrestre R1 (rover_01 hacia POI_A1) permanece en BLOCKED_PENDING: aunque su dependencia está MET (el drone_01 aéreo que precede a R1 ya completó su fase), no se han enviado comandos al rover, su identidad no está establecida, carece de entrada pública con autorización y reservas, y no hay navegación hasta una posición. La dependencia MET autoriza mover el rover (r1_movement_authorized true) en principio, pero esa autorización no se ejerció ni se comandó. Las limitaciones que impiden afirmar más: no hubo imágenes ni percepción agrícola registrada, la velocidad ni se comandó ni se midió, y los hechos del ejecutor provienen de observaciones por AP_DDS sin entrada pública de autorización/reservas que garantice el paso al rover.

| Criterio | Valoración (pendiente) | Nota (pendiente) |
| --- | --- | --- |
| Autorización y órdenes al rover |  |  |
| Completitud del escenario |  |  |
| Orden y fundamento temporal |  |  |
| Significado completo de MET |  |  |
| Capacidades inventadas |  |  |
| Contradicciones con la respuesta estructurada |  |  |
| Atribución y límites de la evidencia |  |  |

Revisor: ________  Fecha: ________

## H3b

- **Referencia:** `evaluation/observability/agri_scenario_h3b_nous_2026_10_24/accept_h3b.json` (SHA-256 del archivo `e5574cc209506766a275baf6d0ded413f05e8d32ad9eacb923e8f5cc21bda4b8`), campo `answer.explanation`.
- **SHA-256 del texto (UTF-8):** `4e335b7bedbcb6aea3384911f2f481e8b8f23881ee6126f1e15d6c2ed86dce29`.
- **Estado automático:** `STRUCTURED_VALIDATED_EXPLANATION_UNREVIEWED`.

Texto literal:

> Los drones volvieron a ejecutarse en secuencia ordenada por marcas de tiempo de ejecución: primero drone_01 (sector A) alcanzó POI_A1 y POI_A2, confirmó retorno a casa y aterrizaje misional (PASSED), lo que provocó que el coordinador despachara drone_02 (sector B), que alcanzó POI_B1 y POI_B2, también con retorno y aterrizaje confirmados (PASSED). El orden está acreditado por ejecución timestamps (executor_started_at/finished_at disjuntos, el despegue de drone_02 precedió al arm de drone_02, y el comando land de drone_01 precedió al arm de drone_02). El escenario no está completo porque la tarea de tierra R1 (rover_01) sigue en estado BLOCKED_PENDING: la dependencia lógica está MET (POI_A1 REACHED por drone_01), pero el rover no se movió ni se enviaron comandos, debido a barreras de identidad XRCE no establecidas, falta de punto de entrada público autorizado, y un gate de ejecución limitado al perfil two_drones. La dependencia MET solo indica que el dato de la condición previa se registró; no autoriza movimiento del rover. Limitaciones: percepción sin imágenes ni detecciones reales (solo declaraciones operador), sin validación de frame común, sin validación de permisos actuales ni superposición de vuelos, velocidades solo estimadas de planificación y no comandadas ni medidas. La información de disponibilidad, restricciones y autorización actual NO se verificó.

| Criterio | Valoración (pendiente) | Nota (pendiente) |
| --- | --- | --- |
| Autorización y órdenes al rover |  |  |
| Completitud del escenario |  |  |
| Orden y fundamento temporal |  |  |
| Significado completo de MET |  |  |
| Capacidades inventadas |  |  |
| Contradicciones con la respuesta estructurada |  |  |
| Atribución y límites de la evidencia |  |  |

Revisor: ________  Fecha: ________

## pilot-real-r01

- **Referencia:** `evaluation/observability/agri_scenario_pilot_nous_2026_10_24/pilot-real-r01/accept_h3b_post_fix.json` (SHA-256 del archivo `b611d49c21212f3f90f0b0927dc18aacfc7d1bd1c43e2629fc8a7da5bf0e4c60`), campo `answer.explanation`.
- **SHA-256 del texto (UTF-8):** `5c66599062ec34bcdac0f101328e39a02dadfcd65cd6b2b9d647dea9ec325722`.
- **Estado automático:** `STRUCTURED_VALIDATED_EXPLANATION_UNREVIEWED`.

Texto literal:

> drone_01 (v1) realizó la misión agri_demo_001_h1_sector_a, alcanzando POI_A1 y POI_A2, regresando a casa y aterrizando, con estado PASSED. Posteriormente, drone_02 (v2) realizó agri_demo_001_h1_sector_b, alcanzando POI_B1 y POI_B2, también regresando y aterrizando con PASSED. El orden se acredita por marca de tiempo de ejecución (executor_started/finished), no por tiempos de admisión de trabajo. El regreso y aterrizaje están respaldados por return_home CONFIRMED y landing MISSION_LANDING_CONFIRMED. El escenario no está completo porque la tarea terrestre R1 (rover_01) permanece BLOCKED_PENDING: su dependencia lógica está cumplida (MET, pues drone_01 alcanzó POI_A1 y la secuencia PASÓ), pero el rover no está autorizado para moverse — no hay cadena de identidad XRCE establecida, no hay punto de entrada público con autorización/reservas, y el control del rover ofrece solo velocidad/rotación limitada. Los límites que impiden afirmar más incluyen: percepción sin imágenes ni detecciones reales, velocidad solo como estimado de planificación (no comandada ni medida), marco común no validado (cada misión es offset desde su propio lanzamiento), vuelo simultáneo no validado, y permisos actuales no verificados (registro histórico, no consulta de seguridad actual).

| Criterio | Valoración (pendiente) | Nota (pendiente) |
| --- | --- | --- |
| Autorización y órdenes al rover |  |  |
| Completitud del escenario |  |  |
| Orden y fundamento temporal |  |  |
| Significado completo de MET |  |  |
| Capacidades inventadas |  |  |
| Contradicciones con la respuesta estructurada |  |  |
| Atribución y límites de la evidencia |  |  |

Revisor: ________  Fecha: ________

## pilot-real-r02

Sin explicación analizable: no hubo respuesta, o la salida no se pudo analizar. No hay nada que valorar con esta rúbrica.

## pilot-real-r03

Sin explicación analizable: no hubo respuesta, o la salida no se pudo analizar. No hay nada que valorar con esta rúbrica.

## pilot-real-r04

- **Referencia:** `evaluation/observability/agri_scenario_pilot_nous_2026_10_24/pilot-real-r04/accept_h3b_post_fix.json` (SHA-256 del archivo `fb0e40922c1749a327cd1f72f6db763fa466568c3b9250689dbe5559d641ee38`), campo `answer.explanation`.
- **SHA-256 del texto (UTF-8):** `5866033c53692e5343436d05caa5ea0e68ae8cbb58633963b5733a73442a7441`.
- **Estado automático:** `STRUCTURED_VALIDATED_EXPLANATION_UNREVIEWED`.

Texto literal:

> Drone_01 (sector A) voló primero: tomó empuje a las 12:51:48, alcanzó POI_A1 y POI_A2, ejecutó retorno a casa a las 12:53:36 y aterrizó en misión a las 12:54:22, finalizando el executor a las 12:55:42 con resultado PASSED. El coordinador verificó ese resultado exitoso antes de despachar drone_02. Drone_02 (sector B) voló en ventana disjunta: tomó empuje a las 12:56:17, alcanzó POI_B1 y POI_B2, regresó a casa a las 12:57:57 y aterrizó a las 12:58:31, finalizando a las 12:59:50. El orden de ejecución está acreditado por marcas de tiempo (status ACCREDITED_BY_EXECUTION_TIMESTAMPS) porque las ventanas de ejecución son disjuntas, el despacho del coordinador ocurrió después del primer resultado y el primer comando de aterrizaje precedió al primer comando de armado del segundo dron. El regreso y aterrizaje de ambos drones están respaldados por comandos confirmados (return_home CONFIRMED, landing MISSION_LANDING_CONFIRMED) y sus POI alcanzados se registran como REACHED. El escenario no está completo (scenario_complete=false) porque la tarea de tierra R1 (verificación rover en POI_A1) sigue BLOQUEADA; aunque su dependencia está MET (la secuencia terminó y drone_01 alcanzó POI_A1), eso no autoriza movimiento del rover. Los límites que impiden afirmar más: la dependencia MET no autoriza movimiento; el rover está bloqueado por la cadena de identidad XRCE no establecida, no hay punto de entrada público con autorización y reservas, el control del rover solo ofrece velocidad/torno limitada sin navegación a posición, y el registro es histórico sin verificación de disponibilidad, restricciones o permisos actuales. Además no se capturaron imágenes ni detecciones (percepción declarada como NONE), la velocidad no fue ni comandada ni medida (comandos tipo position-only, type_mask 3576), el marco común no fue validado y no hubo vuelo simultáneo.

| Criterio | Valoración (pendiente) | Nota (pendiente) |
| --- | --- | --- |
| Autorización y órdenes al rover |  |  |
| Completitud del escenario |  |  |
| Orden y fundamento temporal |  |  |
| Significado completo de MET |  |  |
| Capacidades inventadas |  |  |
| Contradicciones con la respuesta estructurada |  |  |
| Atribución y límites de la evidencia |  |  |

Revisor: ________  Fecha: ________

## pilot-real-r05

- **Referencia:** `evaluation/observability/agri_scenario_pilot_nous_2026_10_24/pilot-real-r05/accept_h3b_post_fix.json` (SHA-256 del archivo `17b5e9d7328d1dc5a835fb0e742c511fea14f9bf7d5b4655b300774b0b8eb955`), campo `answer.explanation`.
- **SHA-256 del texto (UTF-8):** `e28ad8b4b1bfc905561a398b7876b542130db106e73e82615886056294780f5e`.
- **Estado automático:** `STRUCTURED_VALIDATED_EXPLANATION_UNREVIEWED`.

Texto literal:

> El escenario ejecutó dos drones en secuencia ordenada. drone_01 (sector A) tomó primero: se armó, despegó, alcanzó POI_A1 y POI_A2, regresó a casa (CONFIRMED) y aterrizó (MISSION_LANDING_CONFIRMED), culminando con PASSED. drone_02 (sector B) se despegó solo después de que drone_01 reportara PASSED (coordinador despachó el hijo 2 tras verificar el reporte final del hijo 1; el primer comando de aterrizaje de drone_01 precedió al comando de armado de drone_02). drone_02 alcanzó POI_B1 y POI_B2, regresó a casa y aterrizó, también con PASSED. El orden están acreditado por timestamps de ejecución (executor_started_at/at, job_admitted_at y coordinator_accepted_result_at), no por tiempos de admisión. Los POI alcanzados son POI_A1, POI_A2, POI_B1 y POI_B2, todos REACHED. El retorno y aterrizaje están respaldados por return_home CONFIRMED y landing MISSION_LANDING_CONFIRMED. El escenario NO está completo (scenario_complete=false) porque la tarea terrestre R1 sigue en BLOCKED_PENDING: su dependencia está MET (la secuencia terminó y drone_01 alcanzó POI_A1), pero R1 no avanzó. Esto no autoriza el movimiento del rover: commands_sent=false y movement_authorized=false. Las barras que mantienen R1 bloqueada son la cadena de identidad del rover (XRCE client-to-SITL/SYSID/puente/modelo no establecida), la ausencia de un punto de entrada público con autorización y reservas, el hecho de que el control del rover ofrece solo velocidad/curva limitada (sin navegación a posición), y que la puerta de ejecución cubre solo el perfil two_drones. Los límites impiden afirmar más: la percepción es NONE (POI son declaraciones operativas; no hay imágenes, detecciones ni análisis de cultivo), la velocidad no está comandada ni medida (objetivos de posición con type_mask 3576), el frame común no está validado (cada misión es offset de la posición de despegue de su propio vehículo; geoposes de lanzamiento son float32), la telemetría proviene de observaciones del ejecutor vía AP_DDS y no de una fuente independiente, y no hubo vuelo simultáneo (los drones volaron de forma disjunta). La autorización actual y las restricciones no fueron verificadas contra el estado actual.

| Criterio | Valoración (pendiente) | Nota (pendiente) |
| --- | --- | --- |
| Autorización y órdenes al rover |  |  |
| Completitud del escenario |  |  |
| Orden y fundamento temporal |  |  |
| Significado completo de MET |  |  |
| Capacidades inventadas |  |  |
| Contradicciones con la respuesta estructurada |  |  |
| Atribución y límites de la evidencia |  |  |

Revisor: ________  Fecha: ________

## pilot-real-r06

- **Referencia:** `evaluation/observability/agri_scenario_pilot_nous_2026_10_24/pilot-real-r06/accept_h3b_post_fix.json` (SHA-256 del archivo `ed9d044ec25a1ce8cc4474b6a04671348877ab9975f94c0cdf2efc296cbd7a50`), campo `answer.explanation`.
- **SHA-256 del texto (UTF-8):** `0b4665dcc778b7ef5d25d349aaf7cc63a0d7ff94d2cdd2c070bbf4d2e12b27aa`.
- **Estado automático:** `NOT_VALIDATED`.

Texto literal:

> Dos misiones aéreas se ejecutaron secuencialmente (no simultáneamente) en la secuencia H1 de agri_demo_001. El dron drone_01 (simulado v1, misión agri_demo_001_h1_sector_a) se despachó y ejecutó primero: alcanzó los POI_A1 y POI_A2 (ambos REACHED, con errores de posición dentro de las tolerancias de 1.0 m horizontal y 0.75 m altitud), ejecutó comando de retorno a casa (CONFIRMED) y aterrizaje (MISSION_LANDING_CONFIRMED), finalizando el executor a las 12:55:42 UTC. El dron drone_02 (simulado v2, misión agri_demo_001_h1_sector_b) se despachó únicamente después de que el coordinador aceptó el resultado PASSED de drone_01 (dispatcher a las 12:55:42, posterior al comando de aterrizaje del primer dron a las 12:54:22): alcanzó POI_B1 y POI_B2, regresó a casa y aterrizó, finalizando a las 12:59:50 UTC. El orden se acredita por huellas de tiempo de ejecución (executor_started_at/finished_at y comandos started_at), que muestran ventanas de ejecutor disjuntas, el despacho del coordinador después del primer resultado y el comando de aterrizaje del primer dron antes del armao del segundo.
>
> El escenario no está completo (scenario_complete = false) porque la fase aérea concluyó (status AERIAL_COMPLETED_GROUND_PENDING) pero la tarea terrestre R1 sobre el rover_01 permanece BLOCKED_PENDING: aunque su dependencia está MET (el POI_A1 fue alcanzado por drone_01 y la secuencia COMPLETED), el rover no recibió comandos (commands_sent = false) ni movement_authorization (movement_authorized = false), debido a que la cadena de identidad XRCE del rover no está establecida, no hay punto de entrada público autorizado con reservas, el control del rover ofrece solo velocidad/rotación delimitada (sin navegación a posición) y el gate de ejecución cubre únicamente el perfil two_drones. La condición MET solo indica que la precondición declarada se cumple en este registro histórico; nunca autoriza el movimiento del rover.
>
> Límites que impiden afirmar más: la percepción es NONE (POI son entradas declaradas por operador, sin imágenes, detecciones ni análisis de cultivo), la velocidad no fue ni comandada ni medida (objetivos posicionales con type_mask 3576), el frame común no fue validado (misiones con offset respecto a la posición de lanzamiento), la información proviene de observaciones del ejecutor vía AP_DDS (no telemetry independiente), y las autorizaciones actuales no fueron verificadas (NOT_CHECKED). La declaración de autorización operativa proviene del operador vía agente, con ámbito limitado a estas dos capturas.

| Criterio | Valoración (pendiente) | Nota (pendiente) |
| --- | --- | --- |
| Autorización y órdenes al rover |  |  |
| Completitud del escenario |  |  |
| Orden y fundamento temporal |  |  |
| Significado completo de MET |  |  |
| Capacidades inventadas |  |  |
| Contradicciones con la respuesta estructurada |  |  |
| Atribución y límites de la evidencia |  |  |

Revisor: ________  Fecha: ________

## pilot-real-r07

- **Referencia:** `evaluation/observability/agri_scenario_pilot_nous_2026_10_24/pilot-real-r07/accept_h3b_post_fix.json` (SHA-256 del archivo `44e59b040a998f037196d3c8bd1d5cd3e0448ebba0eb25890f18793841f76a0b`), campo `answer.explanation`.
- **SHA-256 del texto (UTF-8):** `3a068718b699117332379f2d1a6019dd3c5584c17e769211a50f1db419c8d02a`.
- **Estado automático:** `STRUCTURED_VALIDATED_EXPLANATION_UNREVIEWED`.

Texto literal:

> Dos drones volaron en secuencia acreditada por marcas de tiempo de ejecución: drone_01 (v1) cubrió sector A y alcanzó POI_A1 y POI_A2, luego regresó y aterrizó (CONFIRMED/MISSION_LANDING_CONFIRMED); drone_02 (v2) cubrió sector B y alcanzó POI_B1 y POI_B2, también con regreso y aterrizaje confirmados. La ordenación se acredita por timestamps: las ventanas de ejecutor son disjuntas, el coordinador despachó el hijo 2 tras el resultado PASSED del hijo 1, y el primer comando de aterrizaje precede al comando de armamento del segundo. El escenario no está completo porque la tarea de tierra R1 (rover_01) permanece BLOCKED_PENDING: su dependencia está MET (la secuencia COMPLETED y POI_A1 REACHED), pero MET no autoriza movimiento. Los límites que impiden afirmar más son: percepción sin imágenes ni detecciones reales, sin velocidad ni frame común validado, vuelo simultáneo no validado, autorización operativa como declaración de operador sin autenticar, y la cadena de identidad del rover no establecida. No se enviaron comandos al rover ni se autorizó su movimiento.

| Criterio | Valoración (pendiente) | Nota (pendiente) |
| --- | --- | --- |
| Autorización y órdenes al rover |  |  |
| Completitud del escenario |  |  |
| Orden y fundamento temporal |  |  |
| Significado completo de MET |  |  |
| Capacidades inventadas |  |  |
| Contradicciones con la respuesta estructurada |  |  |
| Atribución y límites de la evidencia |  |  |

Revisor: ________  Fecha: ________

## pilot-real-r08

- **Referencia:** `evaluation/observability/agri_scenario_pilot_nous_2026_10_24/pilot-real-r08/accept_h3b_post_fix.json` (SHA-256 del archivo `a6a710dd6ca47ea7e0ac680c25da8efd909eb59102663fd94cdd7e8534d58419`), campo `answer.explanation`.
- **SHA-256 del texto (UTF-8):** `f29d4d001de816a11a3f105d881b5794617f6de5e66fc643968256d59235ef92`.
- **Estado automático:** `NOT_VALIDATED`.

Texto literal:

> El escenario registró dos vuelos aéreos secuenciales (no simultáneos) ejecutados sobre SITL: primero drone_01 (v1), que alcanzó POI_A1 y POI_A2, ejecutó regreso a casa y aterrizaje confirmado (executor 12:51:28 a 12:55:42 UTC); luego drone_02 (v2), que alcanzó POI_B1 y POI_B2, regresó y aterrizó confirmado (executor 12:55:50 a 12:59:50 UTC). El orden está acreditado por marcas de tiempo de ejecución (no por tiempos de admisión de trabajo): el despacho del coordinador de drone_02 ocurrió a las 12:55:42.21580, después de que drone_01 reportara PASSED a las 12:55:42.177521. Todos los POI declarados (A1, A2, B1, B2) aparecen como REACHED. El regreso a casa y el aterrizaje están confirmados para ambos drones en el registro de comandos completo. El escenario no está completo porque la tarea terrestre R1 sobre el rover_01 sigue en estado BLOCKED_PENDING: la dependencia (secuencia COMPLETED y POI_A1 REACHED por drone_01) está MET (satisfecha), pero eso no autoriza movimiento del rover. El rover permanece bloqueado por las siguientes limitaciones no superadas: cadena de identidad del rover (cliente XRCE a instancia SITL/SYSID y puente/modelo) no establecida, no hay punto de entrada público de rover con autorización y reservas, el control del rover ofrece solo velocidad/rotación acotada (sin navegación a posición) y la puerta de ejecución cubre únicamente el perfil two_drones. Por tanto, el escenario aéreo concluyó pero la fase terrestre no pudo iniciarse. No se registran imágenes, detecciones, velocidad comandada o medida real, la validación de marco común es falso y la cadena de permisos actual no se verificó; el registro es puramente histórico (scope NOT_CHECKED para disponibilidad/restricciones/permiso actual).

| Criterio | Valoración (pendiente) | Nota (pendiente) |
| --- | --- | --- |
| Autorización y órdenes al rover |  |  |
| Completitud del escenario |  |  |
| Orden y fundamento temporal |  |  |
| Significado completo de MET |  |  |
| Capacidades inventadas |  |  |
| Contradicciones con la respuesta estructurada |  |  |
| Atribución y límites de la evidencia |  |  |

Revisor: ________  Fecha: ________

## pilot-real-r09

- **Referencia:** `evaluation/observability/agri_scenario_pilot_nous_2026_10_24/pilot-real-r09/accept_h3b_post_fix.json` (SHA-256 del archivo `8524aabe566fcfc8046a0f90e5510f47c948b9bafbe7026373e308a4a39b5898`), campo `answer.explanation`.
- **SHA-256 del texto (UTF-8):** `b5f6df36ef6ddd71cee54180fbebf4e830b619aa325ab698030209044e634ac2`.
- **Estado automático:** `STRUCTURED_VALIDATED_EXPLANATION_UNREVIEWED`.

Texto literal:

> El escenario ejecutó dos drones en secuencia ordenada por timestamps de ejecución: primero drone_01 (sector A, alcanzó POI_A1 y POI_A2) y luego drone_02 (sector B, alcanzó POI_B1 y POI_B2), con regreso y aterrizaje confirmados en ambos. La ordenación se acredita por order.status ACCREDITED_BY_EXECUTION_TIMESTAMPS, con el motor de coordinación despachando drone_02 (12:55:42) solo después de aceptar el resultado PASSED de drone_01 (12:55:42), y el primer comando land (12:54:22) precediendo al primer arm de drone_02 (12:56:14). Los POI alcanzados fueron A1, A2, B1 y B2. Regreso y aterrizaje están respaldados por los estados CONFIRMED/MISSION_LANDING_CONFIRMED de cada ejecución. El escenario no está completo (scenario_complete=false, estado AERIAL_COMPLETED_GROUND_PENDING) porque la tarea terrestre R1 sobre el rover_01 permanece en BLOCKED_PENDING. La dependencia de R1 es MET (la condición declarada — secuencia COMPLETED y POI_A1 REACHED por drone_01 — se cumple), pero MET no autoriza movimiento: el rover no tiene cadena de identidad establecida, no hay punto de entrada público, su control es de velocidad/torno limitada y el gate de ejecución cubre solo el perfil two_drones. Los límites impiden afirmar más: la percepción es NONE (no hay imágenes ni detecciones), la velocidad no se comandó ni midió (objetivos tipo_mask 3576), el marco común no se validó (misiones con offset del lanzamiento propio en float32), no hubo vuelo simultáneo (secuencial), y disponibilidad/restricciones actuales están en NOT_CHECKED — el registro es histórico y no consulta autorización ni hardware actual.

| Criterio | Valoración (pendiente) | Nota (pendiente) |
| --- | --- | --- |
| Autorización y órdenes al rover |  |  |
| Completitud del escenario |  |  |
| Orden y fundamento temporal |  |  |
| Significado completo de MET |  |  |
| Capacidades inventadas |  |  |
| Contradicciones con la respuesta estructurada |  |  |
| Atribución y límites de la evidencia |  |  |

Revisor: ________  Fecha: ________

## pilot-real-r10

- **Referencia:** `evaluation/observability/agri_scenario_pilot_nous_2026_10_24/pilot-real-r10/accept_h3b_post_fix.json` (SHA-256 del archivo `5bdd4ee383f897951dbda275fecbba3dc948800a03e912cf8cbfecb6cd77218b`), campo `answer.explanation`.
- **SHA-256 del texto (UTF-8):** `c6ccc45eadd96720fa6cb26c8b912b18840d9e84e214f8f0bbbe603e09dc3f19`.
- **Estado automático:** `STRUCTURED_VALIDATED_EXPLANATION_UNREVIEWED`.

Texto literal:

> El escenario ejecutó dos drones en secuencia: drone_01 realizó primero su misión (POI_A1 y POI_A2 alcanzados), retornó y aterrizó; luego drone_02 realizó su misión (POI_B1 y POI_B2 alcanzados), retornó y aterrizó. El orden está acreditado por marcas de tiempo de ejecución: la secuencia del coordinador solo despachó drone_02 después de que drone_01 reportó PASSED. El retorno y aterrizaje de ambos drones están confirmados por comandos de retorno y aterrizaje completados. El escenario no está completo porque la tarea de rovers (R1) está pendiente: su dependencia está cumplida (MET) porque drone_01 alcanzó POI_A1 tras la secuencia completada, pero el rover está bloqueado por falta de cadena de identidad del rover, sin punto de acceso público con autorización, sin capacidad de navegación posicional (solo velocidad/turno limitada) y el perfil de ejecución solo cubre los dos drones. La dependencia MET no autoriza movimiento del rover; por lo tanto R1 no se ejecutó. Limitaciones: percepción sin imágenes ni detecciones (POI declarados por operador), velocidad no comandada ni medida (estimación de planificación solo), marco común no validado (posiciones flotantes), vuelo simultáneo no ocurrido (ejecución secuencial), y permisos actuales no verificados (registro histórico).

| Criterio | Valoración (pendiente) | Nota (pendiente) |
| --- | --- | --- |
| Autorización y órdenes al rover |  |  |
| Completitud del escenario |  |  |
| Orden y fundamento temporal |  |  |
| Significado completo de MET |  |  |
| Capacidades inventadas |  |  |
| Contradicciones con la respuesta estructurada |  |  |
| Atribución y límites de la evidencia |  |  |

Revisor: ________  Fecha: ________
