# Hoja de revisión de explicaciones — `agri_scenario_pilot_nous_2026_10_24`

**Revisión humana: PENDIENTE.** Las columnas «Valoración» y «Nota» están vacías a propósito.

- **Texto literal:** campo `explanation` de la aceptación efectiva o, si la respuesta no se pudo
  analizar, la salida completa de Hermes. Nunca se corrige.
- **Referencias:** archivo y SHA-256 de donde procede cada texto.
- **Hechos:** la vista recibida (`tool_result_as_received.json`). El informe determinista
  (`agri_scenario_report_h2_2026_10_24`) los presenta generados por código.
- **Observaciones asistidas:** Claude (asistida, preliminar), 25/10/2026: lectura contra la vista recibida. NO es revisión humana, no cambia ningún estado y no sustituye a explanation_observations_assisted.json (24/10/2026), que se conserva.
- La revisión asistida de H3b no se reutiliza aquí.

Valores sugeridos para «Valoración»: `CORRECTO`, `INCOMPLETO`, `AMBIGUO`, `INCORRECTO`, `NO MENCIONA`.

## pilot-real-r01

Referencia: `pilot-real-r01/accept_h3b_post_fix.json` (SHA-256 `b611d49c21212f3f…`), campo `answer.explanation`. Estado automático: `STRUCTURED_VALIDATED_EXPLANATION_UNREVIEWED`.

Explicación literal:

> drone_01 (v1) realizó la misión agri_demo_001_h1_sector_a, alcanzando POI_A1 y POI_A2, regresando a casa y aterrizando, con estado PASSED. Posteriormente, drone_02 (v2) realizó agri_demo_001_h1_sector_b, alcanzando POI_B1 y POI_B2, también regresando y aterrizando con PASSED. El orden se acredita por marca de tiempo de ejecución (executor_started/finished), no por tiempos de admisión de trabajo. El regreso y aterrizaje están respaldados por return_home CONFIRMED y landing MISSION_LANDING_CONFIRMED. El escenario no está completo porque la tarea terrestre R1 (rover_01) permanece BLOCKED_PENDING: su dependencia lógica está cumplida (MET, pues drone_01 alcanzó POI_A1 y la secuencia PASÓ), pero el rover no está autorizado para moverse — no hay cadena de identidad XRCE establecida, no hay punto de entrada público con autorización/reservas, y el control del rover ofrece solo velocidad/rotación limitada. Los límites que impiden afirmar más incluyen: percepción sin imágenes ni detecciones reales, velocidad solo como estimado de planificación (no comandada ni medida), marco común no validado (cada misión es offset desde su propio lanzamiento), vuelo simultáneo no validado, y permisos actuales no verificados (registro histórico, no consulta de seguridad actual).

Avisos heurísticos automáticos (no validación semántica): ninguno.

| Criterio | Observación asistida (Claude, preliminar) | Valoración (pendiente) | Nota (pendiente) |
| --- | --- | --- | --- |
| Secuencia y prueba del orden (order.checks; no horas de admisión) | Atribuye el orden a executor_started/finished y descarta la admisión; no cita las tres comprobaciones de order.checks. |  |  |
| Armado/despegue (orden correcto; sin comprobaciones inexistentes) | No menciona armado ni despegue. |  |  |
| Dependencia completa de R1 (secuencia COMPLETED y POI_A1 REACHED por drone_01) | «drone_01 alcanzó POI_A1 y la secuencia PASÓ»: cubre las dos condiciones; «PASÓ» por COMPLETED es impreciso. |  |  |
| Autorización y órdenes al rover (no autorizado, sin órdenes; MET no autoriza) | Coherente: no autorizado y cita barreras de la vista. |  |  |
| Completitud del escenario (incompleto por R1) | Coherente: incompleto por R1. |  |  |
| Capacidades inventadas (imágenes, detecciones, velocidad, marco común, simultaneidad, permisos) | «vuelo simultáneo no validado»: ambiguo; la vista registra simultaneous_flight: false y ventanas disjuntas. |  |  |
| Alcance histórico (registro único; no reejecución ni estado actual) | Indica registro histórico, no consulta de seguridad actual. |  |  |
| Contradicciones con sus propios campos estructurados | Ninguna observada. |  |  |

Revisor: ________  Fecha: ________

## pilot-real-r02

Sin respuesta del modelo: no hay explicación que revisar.

## pilot-real-r03

Referencia: `pilot-real-r03/hermes_stdout.txt` (SHA-256 `48556ca0ccb353f8…`); la respuesta no se pudo analizar (`NOT_JSON`). Estado automático: `NOT_VALIDATED`.

Salida literal completa:

~~~~text
```{json}
{
  "scenario_status": "COMPLETED",
  "scenario_complete": true,
  "sequence_order": null,
  "order_basis": "NOT_ACCREDITED",
  "runs": [
    {
      "run_id": "agri-demo-001-h2-r01",
      "vehicle_id": "drone_001",
      "simulated_vehicle": true,
      "mission_id": "mission_agri_001",
      "status": "COMPLETED",
      "result_status": "SUCCESS",
      "reached_points": [
        {"point_id": "POI-01", "value": "REACHED"}
      ],
      "return_home": false,
      "landing": false,
      "executor_started_at": null,
      "executor_finished_at": null
    }
  ],
  "r1_status": null,
  "r1_dependency": null,
  "r1_commands_sent": null,
  "r1_movement_authorized": null,
  "claims": {
    "images_captured": false,
    "detections_made": false,
    "speed_commanded": false,
    "speed_measured": false,
    "simultaneous_flight": false,
    "common_frame_validated": false,
    "current_permissions_checked": false
  },
  "evidence_source": "Historical H1 binding record and scenario summary",
  "explanation": "Los drones no realizaron movimientos autorizados ni regreso ni aterrizaje validado. La secuencia no está acreditada por timestamps de ejecución. El escenario se marca como completo, pero no hay evidencia de acciones de vuelo autorizadas ni de cumplimiento de dependencias de tareas terrestres. Los límites del histórico impiden afirmar detalles operativos actuales."
}
```
~~~~

Avisos heurísticos automáticos (no validación semántica): ninguno.

| Criterio | Observación asistida (Claude, preliminar) | Valoración (pendiente) | Nota (pendiente) |
| --- | --- | --- | --- |
| Secuencia y prueba del orden (order.checks; no horas de admisión) | «no está acreditada por timestamps de ejecución»: contrario a la vista, que el modelo no consultó. |  |  |
| Armado/despegue (orden correcto; sin comprobaciones inexistentes) | No menciona. |  |  |
| Dependencia completa de R1 (secuencia COMPLETED y POI_A1 REACHED por drone_01) | «no hay evidencia de … dependencias de tareas terrestres»: contrario a MET. |  |  |
| Autorización y órdenes al rover (no autorizado, sin órdenes; MET no autoriza) | No menciona autorización ni órdenes. |  |  |
| Completitud del escenario (incompleto por R1) | «El escenario se marca como completo»: contrario a la vista. |  |  |
| Capacidades inventadas (imágenes, detecciones, velocidad, marco común, simultaneidad, permisos) | «no realizaron … regreso ni aterrizaje validado»: contrario a la vista (CONFIRMED / MISSION_LANDING_CONFIRMED). |  |  |
| Alcance histórico (registro único; no reejecución ni estado actual) | Menciona límites del histórico. |  |  |
| Contradicciones con sus propios campos estructurados | El JSON no se pudo analizar (bloque {json}); usa identificadores inexistentes (drone_001, POI-01, mission_agri_001). |  |  |

Revisor: ________  Fecha: ________

## pilot-real-r04

Referencia: `pilot-real-r04/accept_h3b_post_fix.json` (SHA-256 `fb0e40922c1749a3…`), campo `answer.explanation`. Estado automático: `STRUCTURED_VALIDATED_EXPLANATION_UNREVIEWED`.

Explicación literal:

> Drone_01 (sector A) voló primero: tomó empuje a las 12:51:48, alcanzó POI_A1 y POI_A2, ejecutó retorno a casa a las 12:53:36 y aterrizó en misión a las 12:54:22, finalizando el executor a las 12:55:42 con resultado PASSED. El coordinador verificó ese resultado exitoso antes de despachar drone_02. Drone_02 (sector B) voló en ventana disjunta: tomó empuje a las 12:56:17, alcanzó POI_B1 y POI_B2, regresó a casa a las 12:57:57 y aterrizó a las 12:58:31, finalizando a las 12:59:50. El orden de ejecución está acreditado por marcas de tiempo (status ACCREDITED_BY_EXECUTION_TIMESTAMPS) porque las ventanas de ejecución son disjuntas, el despacho del coordinador ocurrió después del primer resultado y el primer comando de aterrizaje precedió al primer comando de armado del segundo dron. El regreso y aterrizaje de ambos drones están respaldados por comandos confirmados (return_home CONFIRMED, landing MISSION_LANDING_CONFIRMED) y sus POI alcanzados se registran como REACHED. El escenario no está completo (scenario_complete=false) porque la tarea de tierra R1 (verificación rover en POI_A1) sigue BLOQUEADA; aunque su dependencia está MET (la secuencia terminó y drone_01 alcanzó POI_A1), eso no autoriza movimiento del rover. Los límites que impiden afirmar más: la dependencia MET no autoriza movimiento; el rover está bloqueado por la cadena de identidad XRCE no establecida, no hay punto de entrada público con autorización y reservas, el control del rover solo ofrece velocidad/torno limitada sin navegación a posición, y el registro es histórico sin verificación de disponibilidad, restricciones o permisos actuales. Además no se capturaron imágenes ni detecciones (percepción declarada como NONE), la velocidad no fue ni comandada ni medida (comandos tipo position-only, type_mask 3576), el marco común no fue validado y no hubo vuelo simultáneo.

Avisos heurísticos automáticos (no validación semántica): ninguno.

| Criterio | Observación asistida (Claude, preliminar) | Valoración (pendiente) | Nota (pendiente) |
| --- | --- | --- | --- |
| Secuencia y prueba del orden (order.checks; no horas de admisión) | Cita las tres comprobaciones de order.checks. Horas citadas coinciden con la vista. |  |  |
| Armado/despegue (orden correcto; sin comprobaciones inexistentes) | «tomó empuje a las 12:51:48» corresponde a takeoff; no menciona arm. Sin error observado. |  |  |
| Dependencia completa de R1 (secuencia COMPLETED y POI_A1 REACHED por drone_01) | «la secuencia terminó y drone_01 alcanzó POI_A1»: completa. |  |  |
| Autorización y órdenes al rover (no autorizado, sin órdenes; MET no autoriza) | Coherente. «velocidad/torno» parece errata de «giro». |  |  |
| Completitud del escenario (incompleto por R1) | Coherente. |  |  |
| Capacidades inventadas (imágenes, detecciones, velocidad, marco común, simultaneidad, permisos) | Coherente: percepción NONE, velocidad no comandada ni medida, marco común no validado, sin vuelo simultáneo. |  |  |
| Alcance histórico (registro único; no reejecución ni estado actual) | Coherente: histórico, sin verificación actual. |  |  |
| Contradicciones con sus propios campos estructurados | Ninguna observada. |  |  |

Revisor: ________  Fecha: ________

## pilot-real-r05

Referencia: `pilot-real-r05/accept_h3b_post_fix.json` (SHA-256 `17b5e9d7328d1dc5…`), campo `answer.explanation`. Estado automático: `STRUCTURED_VALIDATED_EXPLANATION_UNREVIEWED`.

Explicación literal:

> El escenario ejecutó dos drones en secuencia ordenada. drone_01 (sector A) tomó primero: se armó, despegó, alcanzó POI_A1 y POI_A2, regresó a casa (CONFIRMED) y aterrizó (MISSION_LANDING_CONFIRMED), culminando con PASSED. drone_02 (sector B) se despegó solo después de que drone_01 reportara PASSED (coordinador despachó el hijo 2 tras verificar el reporte final del hijo 1; el primer comando de aterrizaje de drone_01 precedió al comando de armado de drone_02). drone_02 alcanzó POI_B1 y POI_B2, regresó a casa y aterrizó, también con PASSED. El orden están acreditado por timestamps de ejecución (executor_started_at/at, job_admitted_at y coordinator_accepted_result_at), no por tiempos de admisión. Los POI alcanzados son POI_A1, POI_A2, POI_B1 y POI_B2, todos REACHED. El retorno y aterrizaje están respaldados por return_home CONFIRMED y landing MISSION_LANDING_CONFIRMED. El escenario NO está completo (scenario_complete=false) porque la tarea terrestre R1 sigue en BLOCKED_PENDING: su dependencia está MET (la secuencia terminó y drone_01 alcanzó POI_A1), pero R1 no avanzó. Esto no autoriza el movimiento del rover: commands_sent=false y movement_authorized=false. Las barras que mantienen R1 bloqueada son la cadena de identidad del rover (XRCE client-to-SITL/SYSID/puente/modelo no establecida), la ausencia de un punto de entrada público con autorización y reservas, el hecho de que el control del rover ofrece solo velocidad/curva limitada (sin navegación a posición), y que la puerta de ejecución cubre solo el perfil two_drones. Los límites impiden afirmar más: la percepción es NONE (POI son declaraciones operativas; no hay imágenes, detecciones ni análisis de cultivo), la velocidad no está comandada ni medida (objetivos de posición con type_mask 3576), el frame común no está validado (cada misión es offset de la posición de despegue de su propio vehículo; geoposes de lanzamiento son float32), la telemetría proviene de observaciones del ejecutor vía AP_DDS y no de una fuente independiente, y no hubo vuelo simultáneo (los drones volaron de forma disjunta). La autorización actual y las restricciones no fueron verificadas contra el estado actual.

Avisos heurísticos automáticos (no validación semántica): ninguno.

| Criterio | Observación asistida (Claude, preliminar) | Valoración (pendiente) | Nota (pendiente) |
| --- | --- | --- | --- |
| Secuencia y prueba del orden (order.checks; no horas de admisión) | CONTRADICCIÓN: dice «no por tiempos de admisión» pero enumera job_admitted_at entre las marcas que acreditan el orden. |  |  |
| Armado/despegue (orden correcto; sin comprobaciones inexistentes) | «se armó, despegó»: orden correcto. |  |  |
| Dependencia completa de R1 (secuencia COMPLETED y POI_A1 REACHED por drone_01) | Completa (secuencia terminada y POI_A1). |  |  |
| Autorización y órdenes al rover (no autorizado, sin órdenes; MET no autoriza) | Coherente: commands_sent=false y movement_authorized=false. |  |  |
| Completitud del escenario (incompleto por R1) | Coherente. |  |  |
| Capacidades inventadas (imágenes, detecciones, velocidad, marco común, simultaneidad, permisos) | Coherente; añade que la telemetría procede del ejecutor vía AP_DDS. |  |  |
| Alcance histórico (registro único; no reejecución ni estado actual) | Coherente: autorización y restricciones actuales no verificadas. |  |  |
| Contradicciones con sus propios campos estructurados | Su campo order_basis es EXECUTION_TIMESTAMPS, mientras la explicación incluye la admisión. |  |  |

Revisor: ________  Fecha: ________

## pilot-real-r06

Referencia: `pilot-real-r06/accept_h3b_post_fix.json` (SHA-256 `ed9d044ec25a1ce8…`), campo `answer.explanation`. Estado automático: `NOT_VALIDATED`.

Explicación literal:

> Dos misiones aéreas se ejecutaron secuencialmente (no simultáneamente) en la secuencia H1 de agri_demo_001. El dron drone_01 (simulado v1, misión agri_demo_001_h1_sector_a) se despachó y ejecutó primero: alcanzó los POI_A1 y POI_A2 (ambos REACHED, con errores de posición dentro de las tolerancias de 1.0 m horizontal y 0.75 m altitud), ejecutó comando de retorno a casa (CONFIRMED) y aterrizaje (MISSION_LANDING_CONFIRMED), finalizando el executor a las 12:55:42 UTC. El dron drone_02 (simulado v2, misión agri_demo_001_h1_sector_b) se despachó únicamente después de que el coordinador aceptó el resultado PASSED de drone_01 (dispatcher a las 12:55:42, posterior al comando de aterrizaje del primer dron a las 12:54:22): alcanzó POI_B1 y POI_B2, regresó a casa y aterrizó, finalizando a las 12:59:50 UTC. El orden se acredita por huellas de tiempo de ejecución (executor_started_at/finished_at y comandos started_at), que muestran ventanas de ejecutor disjuntas, el despacho del coordinador después del primer resultado y el comando de aterrizaje del primer dron antes del armao del segundo.
>
> El escenario no está completo (scenario_complete = false) porque la fase aérea concluyó (status AERIAL_COMPLETED_GROUND_PENDING) pero la tarea terrestre R1 sobre el rover_01 permanece BLOCKED_PENDING: aunque su dependencia está MET (el POI_A1 fue alcanzado por drone_01 y la secuencia COMPLETED), el rover no recibió comandos (commands_sent = false) ni movement_authorization (movement_authorized = false), debido a que la cadena de identidad XRCE del rover no está establecida, no hay punto de entrada público autorizado con reservas, el control del rover ofrece solo velocidad/rotación delimitada (sin navegación a posición) y el gate de ejecución cubre únicamente el perfil two_drones. La condición MET solo indica que la precondición declarada se cumple en este registro histórico; nunca autoriza el movimiento del rover.
>
> Límites que impiden afirmar más: la percepción es NONE (POI son entradas declaradas por operador, sin imágenes, detecciones ni análisis de cultivo), la velocidad no fue ni comandada ni medida (objetivos posicionales con type_mask 3576), el frame común no fue validado (misiones con offset respecto a la posición de lanzamiento), la información proviene de observaciones del ejecutor vía AP_DDS (no telemetry independiente), y las autorizaciones actuales no fueron verificadas (NOT_CHECKED). La declaración de autorización operativa proviene del operador vía agente, con ámbito limitado a estas dos capturas.

Avisos heurísticos automáticos (no validación semántica): ninguno.

| Criterio | Observación asistida (Claude, preliminar) | Valoración (pendiente) | Nota (pendiente) |
| --- | --- | --- | --- |
| Secuencia y prueba del orden (order.checks; no horas de admisión) | Coherente: despacho tras aceptar el PASSED; aterrizaje 12:54:22 anterior; cita las tres comprobaciones. |  |  |
| Armado/despegue (orden correcto; sin comprobaciones inexistentes) | Coherente («armao» es errata). |  |  |
| Dependencia completa de R1 (secuencia COMPLETED y POI_A1 REACHED por drone_01) | Completa (POI_A1 REACHED y secuencia COMPLETED). |  |  |
| Autorización y órdenes al rover (no autorizado, sin órdenes; MET no autoriza) | Coherente; reproduce el significado de MET de la vista. |  |  |
| Completitud del escenario (incompleto por R1) | Coherente. |  |  |
| Capacidades inventadas (imágenes, detecciones, velocidad, marco común, simultaneidad, permisos) | Coherente; cita tolerancias 1,0/0,75 m presentes en la vista. |  |  |
| Alcance histórico (registro único; no reejecución ni estado actual) | Coherente: NOT_CHECKED y declaración del operador limitada a dos capturas. |  |  |
| Contradicciones con sus propios campos estructurados | Ninguna en la explicación. El rechazo estructurado es por el formato de reached_points. |  |  |

Revisor: ________  Fecha: ________

## pilot-real-r07

Referencia: `pilot-real-r07/accept_h3b_post_fix.json` (SHA-256 `44e59b040a998f03…`), campo `answer.explanation`. Estado automático: `STRUCTURED_VALIDATED_EXPLANATION_UNREVIEWED`.

Explicación literal:

> Dos drones volaron en secuencia acreditada por marcas de tiempo de ejecución: drone_01 (v1) cubrió sector A y alcanzó POI_A1 y POI_A2, luego regresó y aterrizó (CONFIRMED/MISSION_LANDING_CONFIRMED); drone_02 (v2) cubrió sector B y alcanzó POI_B1 y POI_B2, también con regreso y aterrizaje confirmados. La ordenación se acredita por timestamps: las ventanas de ejecutor son disjuntas, el coordinador despachó el hijo 2 tras el resultado PASSED del hijo 1, y el primer comando de aterrizaje precede al comando de armamento del segundo. El escenario no está completo porque la tarea de tierra R1 (rover_01) permanece BLOCKED_PENDING: su dependencia está MET (la secuencia COMPLETED y POI_A1 REACHED), pero MET no autoriza movimiento. Los límites que impiden afirmar más son: percepción sin imágenes ni detecciones reales, sin velocidad ni frame común validado, vuelo simultáneo no validado, autorización operativa como declaración de operador sin autenticar, y la cadena de identidad del rover no establecida. No se enviaron comandos al rover ni se autorizó su movimiento.

Avisos heurísticos automáticos (no validación semántica): ninguno.

| Criterio | Observación asistida (Claude, preliminar) | Valoración (pendiente) | Nota (pendiente) |
| --- | --- | --- | --- |
| Secuencia y prueba del orden (order.checks; no horas de admisión) | Cita las tres comprobaciones de order.checks. |  |  |
| Armado/despegue (orden correcto; sin comprobaciones inexistentes) | «comando de armamento» del segundo: coherente. |  |  |
| Dependencia completa de R1 (secuencia COMPLETED y POI_A1 REACHED por drone_01) | Completa. |  |  |
| Autorización y órdenes al rover (no autorizado, sin órdenes; MET no autoriza) | Coherente. |  |  |
| Completitud del escenario (incompleto por R1) | Coherente. |  |  |
| Capacidades inventadas (imágenes, detecciones, velocidad, marco común, simultaneidad, permisos) | «vuelo simultáneo no validado»: ambiguo. «sin velocidad ni frame común validado»: mezcla velocidad no comandada/medida con validación. |  |  |
| Alcance histórico (registro único; no reejecución ni estado actual) | No dice explícitamente que es histórico; sí que la autorización es una declaración sin autenticar. |  |  |
| Contradicciones con sus propios campos estructurados | Ninguna observada. |  |  |

Revisor: ________  Fecha: ________

## pilot-real-r08

Referencia: `pilot-real-r08/accept_h3b_post_fix.json` (SHA-256 `a6a710dd6ca47ea7…`), campo `answer.explanation`. Estado automático: `NOT_VALIDATED`.

Explicación literal:

> El escenario registró dos vuelos aéreos secuenciales (no simultáneos) ejecutados sobre SITL: primero drone_01 (v1), que alcanzó POI_A1 y POI_A2, ejecutó regreso a casa y aterrizaje confirmado (executor 12:51:28 a 12:55:42 UTC); luego drone_02 (v2), que alcanzó POI_B1 y POI_B2, regresó y aterrizó confirmado (executor 12:55:50 a 12:59:50 UTC). El orden está acreditado por marcas de tiempo de ejecución (no por tiempos de admisión de trabajo): el despacho del coordinador de drone_02 ocurrió a las 12:55:42.21580, después de que drone_01 reportara PASSED a las 12:55:42.177521. Todos los POI declarados (A1, A2, B1, B2) aparecen como REACHED. El regreso a casa y el aterrizaje están confirmados para ambos drones en el registro de comandos completo. El escenario no está completo porque la tarea terrestre R1 sobre el rover_01 sigue en estado BLOCKED_PENDING: la dependencia (secuencia COMPLETED y POI_A1 REACHED por drone_01) está MET (satisfecha), pero eso no autoriza movimiento del rover. El rover permanece bloqueado por las siguientes limitaciones no superadas: cadena de identidad del rover (cliente XRCE a instancia SITL/SYSID y puente/modelo) no establecida, no hay punto de entrada público de rover con autorización y reservas, el control del rover ofrece solo velocidad/rotación acotada (sin navegación a posición) y la puerta de ejecución cubre únicamente el perfil two_drones. Por tanto, el escenario aéreo concluyó pero la fase terrestre no pudo iniciarse. No se registran imágenes, detecciones, velocidad comandada o medida real, la validación de marco común es falso y la cadena de permisos actual no se verificó; el registro es puramente histórico (scope NOT_CHECKED para disponibilidad/restricciones/permiso actual).

Avisos heurísticos automáticos (no validación semántica): may_claim_measured_or_commanded_speed.

| Criterio | Observación asistida (Claude, preliminar) | Valoración (pendiente) | Nota (pendiente) |
| --- | --- | --- | --- |
| Secuencia y prueba del orden (order.checks; no horas de admisión) | Horas del ejecutor y despacho (12:55:42.21580 tras PASSED 12:55:42.177521) coinciden con la vista. |  |  |
| Armado/despegue (orden correcto; sin comprobaciones inexistentes) | No menciona. |  |  |
| Dependencia completa de R1 (secuencia COMPLETED y POI_A1 REACHED por drone_01) | Completa. |  |  |
| Autorización y órdenes al rover (no autorizado, sin órdenes; MET no autoriza) | Coherente. |  |  |
| Completitud del escenario (incompleto por R1) | Coherente. |  |  |
| Capacidades inventadas (imágenes, detecciones, velocidad, marco común, simultaneidad, permisos) | Niega correctamente imágenes, detecciones y velocidad. El aviso heurístico de velocidad es un falso positivo (negación). |  |  |
| Alcance histórico (registro único; no reejecución ni estado actual) | Coherente: histórico, NOT_CHECKED. |  |  |
| Contradicciones con sus propios campos estructurados | CONTRADICCIÓN con sus campos: la explicación niega esas capacidades, pero cinco claims son null (rechazo crítico). |  |  |

Revisor: ________  Fecha: ________

## pilot-real-r09

Referencia: `pilot-real-r09/accept_h3b_post_fix.json` (SHA-256 `8524aabe566fcfc8…`), campo `answer.explanation`. Estado automático: `STRUCTURED_VALIDATED_EXPLANATION_UNREVIEWED`.

Explicación literal:

> El escenario ejecutó dos drones en secuencia ordenada por timestamps de ejecución: primero drone_01 (sector A, alcanzó POI_A1 y POI_A2) y luego drone_02 (sector B, alcanzó POI_B1 y POI_B2), con regreso y aterrizaje confirmados en ambos. La ordenación se acredita por order.status ACCREDITED_BY_EXECUTION_TIMESTAMPS, con el motor de coordinación despachando drone_02 (12:55:42) solo después de aceptar el resultado PASSED de drone_01 (12:55:42), y el primer comando land (12:54:22) precediendo al primer arm de drone_02 (12:56:14). Los POI alcanzados fueron A1, A2, B1 y B2. Regreso y aterrizaje están respaldados por los estados CONFIRMED/MISSION_LANDING_CONFIRMED de cada ejecución. El escenario no está completo (scenario_complete=false, estado AERIAL_COMPLETED_GROUND_PENDING) porque la tarea terrestre R1 sobre el rover_01 permanece en BLOCKED_PENDING. La dependencia de R1 es MET (la condición declarada — secuencia COMPLETED y POI_A1 REACHED por drone_01 — se cumple), pero MET no autoriza movimiento: el rover no tiene cadena de identidad establecida, no hay punto de entrada público, su control es de velocidad/torno limitada y el gate de ejecución cubre solo el perfil two_drones. Los límites impiden afirmar más: la percepción es NONE (no hay imágenes ni detecciones), la velocidad no se comandó ni midió (objetivos tipo_mask 3576), el marco común no se validó (misiones con offset del lanzamiento propio en float32), no hubo vuelo simultáneo (secuencial), y disponibilidad/restricciones actuales están en NOT_CHECKED — el registro es histórico y no consulta autorización ni hardware actual.

Avisos heurísticos automáticos (no validación semántica): ninguno.

| Criterio | Observación asistida (Claude, preliminar) | Valoración (pendiente) | Nota (pendiente) |
| --- | --- | --- | --- |
| Secuencia y prueba del orden (order.checks; no horas de admisión) | Despacho tras aceptar el PASSED y land 12:54:22 antes del arm 12:56:14: coherente; no cita ventanas disjuntas. |  |  |
| Armado/despegue (orden correcto; sin comprobaciones inexistentes) | Coherente. |  |  |
| Dependencia completa de R1 (secuencia COMPLETED y POI_A1 REACHED por drone_01) | Completa. |  |  |
| Autorización y órdenes al rover (no autorizado, sin órdenes; MET no autoriza) | Coherente. |  |  |
| Completitud del escenario (incompleto por R1) | Coherente. |  |  |
| Capacidades inventadas (imágenes, detecciones, velocidad, marco común, simultaneidad, permisos) | Coherente. |  |  |
| Alcance histórico (registro único; no reejecución ni estado actual) | Coherente. |  |  |
| Contradicciones con sus propios campos estructurados | Ninguna observada. |  |  |

Revisor: ________  Fecha: ________

## pilot-real-r10

Referencia: `pilot-real-r10/accept_h3b_post_fix.json` (SHA-256 `5bdd4ee383f89795…`), campo `answer.explanation`. Estado automático: `STRUCTURED_VALIDATED_EXPLANATION_UNREVIEWED`.

Explicación literal:

> El escenario ejecutó dos drones en secuencia: drone_01 realizó primero su misión (POI_A1 y POI_A2 alcanzados), retornó y aterrizó; luego drone_02 realizó su misión (POI_B1 y POI_B2 alcanzados), retornó y aterrizó. El orden está acreditado por marcas de tiempo de ejecución: la secuencia del coordinador solo despachó drone_02 después de que drone_01 reportó PASSED. El retorno y aterrizaje de ambos drones están confirmados por comandos de retorno y aterrizaje completados. El escenario no está completo porque la tarea de rovers (R1) está pendiente: su dependencia está cumplida (MET) porque drone_01 alcanzó POI_A1 tras la secuencia completada, pero el rover está bloqueado por falta de cadena de identidad del rover, sin punto de acceso público con autorización, sin capacidad de navegación posicional (solo velocidad/turno limitada) y el perfil de ejecución solo cubre los dos drones. La dependencia MET no autoriza movimiento del rover; por lo tanto R1 no se ejecutó. Limitaciones: percepción sin imágenes ni detecciones (POI declarados por operador), velocidad no comandada ni medida (estimación de planificación solo), marco común no validado (posiciones flotantes), vuelo simultáneo no ocurrido (ejecución secuencial), y permisos actuales no verificados (registro histórico).

Avisos heurísticos automáticos (no validación semántica): ninguno.

| Criterio | Observación asistida (Claude, preliminar) | Valoración (pendiente) | Nota (pendiente) |
| --- | --- | --- | --- |
| Secuencia y prueba del orden (order.checks; no horas de admisión) | Solo cita el despacho del coordinador: correcto pero parcial. |  |  |
| Armado/despegue (orden correcto; sin comprobaciones inexistentes) | No menciona. |  |  |
| Dependencia completa de R1 (secuencia COMPLETED y POI_A1 REACHED por drone_01) | «drone_01 alcanzó POI_A1 tras la secuencia completada»: completa. |  |  |
| Autorización y órdenes al rover (no autorizado, sin órdenes; MET no autoriza) | Coherente. |  |  |
| Completitud del escenario (incompleto por R1) | Coherente. |  |  |
| Capacidades inventadas (imágenes, detecciones, velocidad, marco común, simultaneidad, permisos) | «marco común no validado (posiciones flotantes)»: impreciso; la vista lo atribuye a offsets desde lanzamientos distintos. |  |  |
| Alcance histórico (registro único; no reejecución ni estado actual) | Coherente. |  |  |
| Contradicciones con sus propios campos estructurados | Ninguna observada. |  |  |

Revisor: ________  Fecha: ________

