# Revisión independiente del primer movimiento rover — 04/11/2026

Decisión: **NO_GO para solicitar todavía la navegación de 1 m**. No autoriza movimiento.
Base revisada: `8067f8b03c79b2b478d8120103f21b0368e8f4c2`, rama `feature/rover-sitl-first-motion`.

## Defectos confirmados y correcciones offline

1. NativeRos2Session perdía la cancelación local del future si SIGALRM llegaba entre el bucle y cancel(). Corregido con margen interno y finally sobre la creación, espera y lectura del future. Una segunda prueba determinista cubre también la alarma justo después de asignarlo, reproducida antes de corregir esa ventana. Eliminado el xfail estricto existente. La reproducción determinista pasa, y pasan 20 timeouts repetidos sin reenvío. Cancelar el future NO deshace una orden ejecutada; el diagnóstico sigue UNCONFIRMED.
2. Una reserva desaparecida entre assert_execution_authority y la lectura de scope causaba TypeError tanto al desarmar como al preparar. Ahora hay un rechazo RoverControlError explícito, antes de consultar un job inexistente.
3. El monitor esperaba el mismo lock retenido por una publicación bloqueada. Ahora enclava el rechazo de movimiento ANTES de adquirir recursos, no espera ese lock y registra UNCONFIRMED_PUBLISH_BUSY. Si la publicación en curso retorna, el emisor coloca después la velocidad cero. El monitor también detecta silencio/expiración si el principal está bloqueado fuera de busy(). No se ha demostrado que una llamada ROS de publicación llegue a retornar.
4. El worker podía aceptar otra orden de movimiento tras un servicio sin confirmación. Ahora queda stop-only tras EFFECT_UNCONFIRMED; siguen permitidos cero/HOLD/desarmado. La cancelación KeyboardInterrupt también intenta safe_stop antes del teardown. No se reenvía el comando incierto.
5. Una respuesta con graph de tipo lista provocaba AttributeError sin romper el canal. Ahora se verifica la forma del resultado/error/graph, se rompe la sesión y se conserva la incertidumbre. Una nueva orden de movimiento revalida además el fence de la ejecución. La factoría verifica autoridad/política antes de crear el worker y, para SITL, compara sus límites con el scope admitido.
6. El scope anterior solo vinculaba misión/goal/binding/ejecución, permitiendo cambiar límites, frescura, preparación o cierre sin cambiar la declaración SITL. El builder produce scope /2: digest del request completo salvo su propia declaración, más cadencia, pose inicial, tolerancias, derivación de tiempos y límites del worker. El executor rechaza scopes antiguos/incompletos o inconsistentes. La inserción de declaraciones rechaza cambios en el trial externo. No se han producido autorizaciones para un entorno real.
7. La cota antigua usaba el RTF bajo medido para reducir el desplazamiento durante una observación envejecida. Ahora no se concede ese crédito. A RTF 0,6 y status 1,2 Hz se mantienen 1,35 s de edad máxima, pero la velocidad derivada baja de 0,30 a 0,15 m/s: **0,30 × 1,35 = 0,405 m** frente a **0,15 × 1,35 = 0,2025 m ≤ 0,25 m**. La cota sigue suponiendo que el factor de avance sim/wall no supera el límite superior declarado por la derivación; no se ha demostrado ese límite en una ejecución real.
8. Se añade una comprobación de pose viva acreditada antes de GUIDED/ARM: odom, desvío ≤ 0,05 m y ≤ 0,05 rad respecto a la pose inicial declarada. Esas tolerancias también forman parte del scope.

Las dos allowlists se regeneraron solo para los tres módulos Python añadidos por los nuevos imports: rover_pipe_session.py, rover_pipe_worker.py y rover_target_frame.py. La checklist de Toni obtiene HEAD con git rev-parse --short HEAD; no se reescribió el guion.

## Pruebas ejecutadas

| Fase | PASSED | FAILED | SKIPPED | XFAIL | Duración |
|---|---:|---:|---:|---:|---:|
| Focal inicial | 198 | 0 | 50 | 1 | 21,55 s |
| Reproducciones antes de corregir | 18 | 17 | 0 | 0 | 2,38 s |
| Focal tras correcciones principales | 243 | 0 | 50 | 0 | 26,80 s |
| Cancelación nativa final | 24 | 0 | 0 | 0 | 1,88 s |
| Regresión final secuencial (rover + agri + demo) | 2067 | 6 | 247 | 0 | 332.49 s |
| Seis fallos comprobados sobre fuente base 8067f8b03 | 0 | 6 | 0 | 0 | 0.36 s |

La regresión final incluye **45 pruebas nuevas aprobadas** (23 native, 7 pipe, 15 scope), la antigua reproducción xfail ahora aprobada y los 11 tests de demo. Las cifras de las filas se solapan; no deben sumarse. Después del focal se añadió la comprobación de cancelación del worker; también pasó en la regresión final.

Los seis fallos de la regresión son exactamente los mismos que se reprodujeron usando fuente del commit base y los mismos datos históricos, enlazados en solo lectura desde una copia temporal: no hay regresiones nuevas detectadas en el alcance ejecutado.

- Pin: test_rover_clock_path_preparation::test_derived_closure_reader_pins_are_consumed_without_binary_changes. Preparación sellada y fuentes actuales divergentes; no se editó el sello.
- Entorno: cuatro journals SDK/reader encontrados por un glob genérico no son el formato pasivo esperado; report.start es None. La quinta prueba presupone 5 journals, pero ese glob encuentra 9. No se borró, movió ni editó ningún journal y no se cambiaron las pruebas para ocultar esos fallos.
- 243 omisiones antes de ejecutar fixtures por activar temporalmente OPERATIONAL_ROVER_ENABLED o SITL_TRIAL_POLICY_ENABLED. Incluyen recorridos completos de admisión/worker/finalización y pruebas de reserva retenida: esa integración positiva NO queda revalidada aquí.
- 4 omisiones preexistentes corresponden al invariante de parada de un arranque fallido (layout exitoso probado aparte).

La primera pasada amplia se interrumpió al detectar una guarda externa demasiado amplia para los symlinks ficticios de /proc; sus 13 errores de setup y un diagnóstico adicional quedan separados. Corregida la guarda, el caso de setup pasó y la regresión se repitió secuencialmente. No se modificaron pruebas de producto para resolver ese problema del arnés.

## Timeouts, watchdog y STOP

call_budget conserva W=min(0,7T,T−0,3), lectura hasta T−0,05. Para T=2 s: W=1,4 s, lectura=1,95 s; para T=0,5: W=0,2 y lectura=0,45. Por debajo del presupuesto mínimo de 0,1 s de worker (T aproximadamente menor de 0,4 s), no se envía nada. La alarma restante también limita T.

Las pruebas incluyen pipes y procesos hijos reales con backend falso, SIGALRM real, EOF, respuestas tardías/perdidas y comandos aplicados sin confirmación. Tras canal roto, no se reenvía ni se intenta utilizarlo como si siguiera íntegro; queda la parada propia del worker, cuyo efecto real no está verificado. Con timeout respondido y canal íntegro, solo se permiten paradas.

**IPC_RESERVE_S=0,25 s sigue siendo una hipótesis, no una medida del pipe real.** No se ha ejecutado docker exec ni medido ROS durante esta revisión. El monitor puede enclavar sin esperar un lock ocupado, pero su propia publicación ROS también puede bloquear o no llegar si DDS/subscriber desaparece. Ni publicar cero, ni recibir ACK de HOLD, ni cancelar un future demuestra por sí solo que el rover esté parado. El worker conserva NOT_CLAIMED_BY_WORKER y el host exige observaciones. A 0,15 m/s, los 3 s del watchdog todavía permiten 0,45 m antes de su intento de cero (suponiendo RTF ≤ 1), sin incluir frenado ni una API ROS bloqueada. La tolerancia de llegada de 0,25 m no certifica una distancia de parada de emergencia.

El ensayo conserva presupuestos independientes de preparación (20 s), navegación (45 s), parada (8 s en la cadencia de ejemplo), desarmado (10 s) y cierre (2 s). Sumando probe de 2 s son 87 s de fases; NO es un deadline global de 60 s. Hay además arranque/hello del worker. El worker declara 120 s de sesión. No se ha probado una cota física de parada ni que APIs C opacas siempre respeten una alarma Python.

## Scope, identidad y cadencia

Se mantienen las verificaciones de misión, frame odom, pose inicial, goal, binding, lifecycle, perfil rover_only, host boot y ejecución del contenedor. Se añaden límites, preparación, política de parada/finalización, frecuencia/frescura y límites propios del worker al contrato autorizado. Cambiar esos parámetros invalida la declaración anterior. La pose viva se compara antes de preparar. Los ejemplos de las pruebas son sintéticos, nunca nuevas autorizaciones humanas.

Se conserva el rechazo de RTF bajo y de telemetría congelada/duplicada/irregular. La derivación es viable en el ejemplo desde RTF 0,53 con status simulado de 2 Hz; a RTF 0,5 pide una edad de 1,55 s y se rechaza por superar el tope de 1,5 s. El ritmo solicitado de 2 Hz no acredita un ritmo efectivo de 2 Hz: depende de observaciones nuevas. La cadencia real, la correspondencia de relojes y la vinculación temporal de las métricas con un lifecycle nuevo deben comprobarse antes de autorizar el ensayo.

## Pines XRCE y revisión legítima pendiente

La propuesta xrce-pin-review-proposal.json enumera hashes históricos/actuales de rover_ground_executor.py, rover_ros2_adapter.py, rover_xrce_trace/session_precheck.py y simulation_lifecycle.py. No es un manifiesto aceptado, una aplicación ni una autorización.

REVISABLE_PINS del sucesor existente solo permite historical_disposition.py y simulation_profiles.py: no legitima actualizar arbitrariamente los otros pines. Hace falta revisar explícitamente las diferencias y un descriptor/procedimiento de revisión de esas dependencias, preparar un directorio nuevo conservando binarios/dependencias nativas salvo revisión aparte, ejecutar selection_dry_run y después obtener hechos actuales y la autorización exacta de Joel antes de cualquier apply. No se ha ejecutado precheck operativo ni se ha ampliado esa allowlist de permisos.

Se comprobó independientemente que 807aa1269 dejaba app y planner coincidentes con su generador en la fuente del HEAD base. Las nuevas tres entradas por imagen pertenecen exclusivamente a esta revisión y su prueba de distribución pasa.

## Demo, Git y conservación

La demo ejecutada fuera del repositorio devuelve **9 PASS, 9 BLOCKED esperados, 0 FAILED**. Los 11 tests específicos pasan. No se demuestra cámara, percepción, vuelo, navegación real o ejecución conjunta.

Los 786 archivos de sellos y estados operativos observados al inicio conservan sus hashes; el conjunto de archivos de missions/generated tampoco cambia. No se han modificado reservas, autorizaciones históricas, manifiestos sellados ni main. No se han arrancado/parado servicios, Docker, WSL, Gazebo o SITL, ni se ha armado/movido nada. Ambos flags permanecen False. Pruebas en Python 3.12.3, venv independiente copiado del entorno exacto de constraints ya disponible; sin instalación externa ni acceso a proveedores. pip-freeze.txt recoge las versiones.

## Decisión y mínimos pendientes

**NO_GO.** Para volver a evaluar si se puede solicitar el primer metro:

1. Revisión XRCE nueva, explícita y autorizada, conservando la anterior; después precheck vigente. El borrador no sustituye la autorización ni valida hechos actuales.
2. Completar la integración positiva del contrato /2 en un arnés offline expresamente autorizado que conserve los flags operativos reales en False; verificar especialmente nueva pose inicial, límites de la factoría, reserva retenida y cierre. Las 243 omisiones impiden atribuir esa cobertura a esta ejecución.
3. Validar en una fase previa y autorizada de commissioning la latencia real del pipe/ROS y la capa de parada/failsafe de ArduRover frente a publicación bloqueada, pérdida de DDS y pérdida del host. Si no hay límite demostrable, añadir uno independiente (watchdog/failsafe de autopiloto o transporte acotado) antes del ensayo de 1 m. El monitor Python no es prueba suficiente.
4. Obtener readiness, MotionBinding y métricas de un nuevo lifecycle rover_only con boot/ejecución/relojes actuales, derivar el trial y presentar su scope a Joel. Nada de esta revisión habilita una política o sustituye sus declaraciones.

Los cinco fallos ambientales pueden corregirse posteriormente delimitando las pruebas históricas por el esquema real de sus journals, sin borrar datos; no deben confundirse con el comportamiento de conducción.

Resultados y comandos de esta revisión: `/tmp/tfg-rover-review-20261104-l_24n_is/results` (copia persistente también en archivo_TFG).
