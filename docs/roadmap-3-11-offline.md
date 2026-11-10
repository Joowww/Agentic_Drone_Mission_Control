# Pasos 3–11: cierre del 19/10/2026

> Actualización posterior del 19/10: [SITL detenido y cierre administrativo](stopped-sitl-reconciliation.md). Las limitaciones de suelo visual de este cierre anterior describen la vía ACTIVE; no se exige telemetría ni imagen de un entorno terminado verificablemente. La aplicación real sigue pendiente.

Estado del código y de sus pruebas offline. **No significa validación operativa**.
Se conserva la rama y el trabajo previo, sin staging/commit/push ni operaciones
Docker/ROS/MCP, vuelos, reconciliación real o liberación de las reservas existentes.

| Paso | Estado principal | Evidencia y pendiente |
| --- | --- | --- |
| 3. Diagnóstico de operaciones | IMPLEMENTADO_OFFLINE | Origen/geopose/status/controles con identidad, endpoint, etapa, tiempos de pared, timeout, retorno y error; trazas acotadas. Confirmar el observador/executor en el stack real queda pendiente. |
| 4. Fallos iniciales y contexto parcial | IMPLEMENTADO_OFFLINE | Resultado FAILED persistido y analizado incluso antes de GUIDED/ARM; no recuperación innecesaria, ARM fallido conserva incertidumbre y recuperación LAND. No reinterpreta el ERROR anterior. |
| 5. Reconciliación explícita y auditable | IMPLEMENTADO_OFFLINE | Inspect/apply/get, versiones/hash/identidad/TTL, telemetría nueva y declaración visual independiente por ambos vehículos; historial y barrera ante interrupción. Sin fuente suficiente la aplicación es BLOCKED. |
| 6. Reconciliar la secuencia citada | PENDIENTE_OPERATIVO | Procedimiento concreto preparado, originales presentes y reservas intactas. No hay telemetría/confirmación visual actual aportada en este trabajo ni autorización para aplicar. Si la GUI continúa negra y no hay otra vista actual: BLOQUEADO, sin alternativa automática implementada. |
| 7. Exclusión lifecycle/admisión/ejecución | IMPLEMENTADO_OFFLINE | MCP, Python, scripts y backend protegido; registro y mutex global durante lifecycle, barrera durable, reinicio sin hueco. Demo paralela deshabilitada. Probar todas las entradas en entorno real queda pendiente. |
| 8. GUI negra y opciones GUI/headless | PENDIENTE_OPERATIVO | Logs conservados revisados, diagnóstico reproducible documentado y gui=false conectado al mecanismo existente. No se ha demostrado causa ni corrección de renderizado; READY no confirma imagen. |
| 9. Nueva secuencia v1→v2 | PENDIENTE_OPERATIVO | Plan con paths/hashes, orden y clave nueva `joel-secuencia-sitl-20261019-r02`, sin autorización preconcedida ni admisión. Sólo después de reconciliación, readiness actual y consentimiento nuevo. |
| 10. Regresiones y matriz operativa | IMPLEMENTADO_OFFLINE | Fallos iniciales, parcialidad, identidad/PID, caducidad/ausencia/cambios, idempotencia/auditoría, interrupción, carreras deterministas y bloqueo del segundo hijo. Matriz nominal/repetibilidad preparada, no ejecutada. |
| 11. Revisión y comprobaciones | IMPLEMENTADO_OFFLINE | 248 tests afectados y 477 suite completa pasados; sintaxis Python/Bash y diff revisados. Whitespace de evidencia bruta se informa y conserva, no se normaliza. Propuesta de commits preparada, sin ejecutarlos. |

## Resultados reales

- Selección ampliada: **248 passed in 9.97s**.
- Suite completa final: **477 passed in 15.65s**.
- Sintaxis: **23 archivos Python**, **5 scripts con bash -n** y código Python
  embebido del observador compilados sin ejecutarlo.
- `git diff --check` versionado: sin errores. Archivos nuevos de código, tests,
  configuración y documentación: sin avisos. Hay **9 piezas brutas/fuentes de
  evidencia con avisos de whitespace**: siete del diagnóstico anterior y el nuevo
  texto pegado de usuario y el primer log pytest con fallos; se mantienen bytes y hashes, incluidos espacios/CRLF.
- Primera suite completa verificable durante el incremento: **457 passed,
  2 failed in 14.98s**. Ambos fallos eran tests de scripts que seguían usando el
  checkout real: el guard nuevo los bloqueaba antes del Docker falso. Se adaptaron
  para ejecutar wrappers/backend reales en un proyecto temporal con Docker falso.
  No se debilitó la comprobación de abortar al fallar la limpieza.
- Los **428 tests** anteriores son un resultado histórico del registro. No hay
  una ejecución completa nueva de baseline sin cambios que permita atribuir otros
  fallos previos. La primera tanda nueva también detectó un job asíncrono ausente
  que indebidamente permitía inspección elegible; se corrigió y quedó en regresión.

No hay tests de obediencia del LLM por presencia de frases. El registro MCP se
prueba mediante SDK/esquemas reales con backends doblados, sin conexión operativa.
La cobertura de concurrencia usa Events/mutex reales sobre temporales; no sleeps
como coordinación entre threads. La reserva exterior se comprueba también en el
intervalo en que ya terminó el primer hijo y aún no se reservó el segundo.

## Documentos para usar después

- [Procedimiento, límites, matriz y prompts de una línea](reconciliation-and-lifecycle.md).
- [Plan de repetición, sin consentimiento](../evaluation/operations/sequence_v1_v2_retry_2026_10_19.json).
- [Demo pegada: copias, hashes y distinción de evidencia](../simulation/ros2_gazebo/results/demo_observability_2026_10_19/README.md).
- [Verificación y resultados offline](../simulation/ros2_gazebo/results/roadmap_offline_2026_10_19/verification.json).

La primera prueba de Joel debe ser inspección de sólo lectura. La aplicación de
reconciliación, la recuperación de GUI y cualquier vuelo posterior son decisiones
autorizadas **por separado**. La fuente de suelo admitida es observación visual
actual del operador de ambos modelos apoyados en la pista, no AP armed/flying.
Si esa fuente no puede obtenerse sin reiniciar un backend incierto, este incremento
no permite cerrar la reconciliación: hay que conservar restricciones y revisar una
fuente independiente o una recuperación administrativa específica. No se presenta
ese bloqueo como solucionado.

No se demuestra resistencia operativa a reinicios del host, coordinación simultánea,
separación, agricultura, seguimiento de velocidad, carga/ejecución del `.plan`,
causa de WP3/124/GUI ni fidelidad global de Hermes. Las garantías de exclusión son
para este checkout actualizado; clientes ROS/QGC/Docker directos u otros checkouts
pueden saltarse esta coordinación. Una interrupción durante reconciliación deja
una barrera que requiere revisión específica, sin reanudación automática.


## Actualización posterior: primer intento con contenedor detenido

La inspección operativa `1a977374-4df9-42a6-9409-d0e0c3a991e2` quedó BLOCKED sin
telemetría ni aplicación. Se conserva exacta. La vía administrativa adicional de
[entorno terminado](stopped-sitl-reconciliation.md) queda IMPLEMENTADO_OFFLINE:
no exige telemetría/GUI imposible, sí identidad previa y actual verificable,
propietarios/versiones/procesos y revalidación bajo exclusión con autorización.
El paso 6 sigue PENDIENTE_OPERATIVO: no se han liberado reservas ni alterado informes.
Las restricciones visuales de la tabla y cierre anteriores describen la primera
vía ACTIVE. No se presenta el contenedor como actualmente detenido sin consultarlo.
Verificación posterior final: 97 tests afectados, 532 suite completa; 27 Python,
5 Bash y observador embebido; diff de código/docs limpio, evidencia bruta preservada.
