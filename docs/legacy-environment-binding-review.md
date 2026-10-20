# Revisión del vínculo legacy: inspección ad234044 (19/10/2026)

**Conclusión: había una laguna en el criterio automático, corregida offline.**
El contenedor observado está documentado como detenido, pero su ID fue obtenido
por una inspección posterior al fallo. Eso no autentica el entorno al que se dirigió
la ejecución original. La vía de cierre administrativo sigue siendo viable con
revisión explícita de continuidad y comprobaciones de consistencia; no requiere
inventar un ID histórico de daemon ni arrancar SITL para obtener telemetría.

No se han ejecutado Docker, ROS, inspecciones operativas, aplicaciones,
liberaciones, arranques ni vuelos. No se ha modificado ninguna reserva o informe.

## Qué se leyó y conservó

Archivo local: `missions/generated/reconciliation_inspections/ad234044-4e5d-4785-b8c4-43f05b89a54a/inspection.json`,
53 756 bytes, SHA-256
`60a17c81680ea58864cd98c92f3d1102acfc8907d9d7ad89393f7d04b0eab844`.
La copia exacta está en
[el manifiesto de revisión](../simulation/ros2_gazebo/results/legacy_binding_review_2026_10_19/manifest.json).
No apareció un segundo JSON adjunto independiente entre los archivos accesibles;
se contrastó el JSON persistido identificado y los datos comunicados por el operador.

El **estado guardado al crearla** es AWAITING_TERMINATION_RECONCILIATION_AUTHORIZATION,
con reasons=[]; no se reescribe. Su **consulta actual de sólo lectura** devuelve
EXPIRED, application_eligible=false y application=null. Vigencia 120 s/mismo boot;
no puede aplicarse esta inspección, ni con una declaración nueva. No se llamó a
la operación de aplicación para comprobarlo sobre los registros reales.

Se verificaron los hashes de todos los contenidos capturados en snapshot.files y
su igualdad con los archivos runtime originales presentes. Secuencia y reserva v2
siguen UNCONFIRMED; hijo v1 PASSED e hijo v2 ERROR siguen intactos. No se infiere
que nunca hubo vuelo: el PASSED del primero documenta su ejecución y la falta de
resultado bruto del segundo no prueba ausencia de efectos.

## Por qué el código anterior no daba motivos de bloqueo

La copia anterior del código está conservada en
[execution_reconciliation_before.py](../simulation/ros2_gazebo/results/legacy_binding_review_2026_10_19/execution_reconciliation_before.py).

1. `_identity_reference` seleccionaba un registro anterior del mismo propietario.
   Extraía del error Docker el ID completo y lo etiquetaba
   LEGACY_FAILED_INSPECTION_CONTAINER_ID, con historical_engine_identity_known=false.
   `identity` sólo contenía container_id; no había motor, creación ni encarnación
   histórica con la que comparar.
2. `_environment_reasons` comparaba las claves **existentes** en identity y llamaba
   `stopped_reasons`. Por tanto, para legacy sólo comparaba el ID, seguido del
   estado actual exited/Running=false/Pid=0, flags y tiempos internos de Docker.
3. `capture` verificaba propietarios, snapshots/hashes, relaciones entre hijos y
   versiones; `_process_reasons` exigía ausencia de los procesos registrados y el
   mutex global libre. Esas verificaciones no vinculaban el endpoint Docker original.
4. `inspect_execution_reconciliation` asignaba ENVIRONMENT_TERMINATED y elegibilidad
   si esas comprobaciones pasaban. `historical_engine_identity_known=false` se
   presentaba como límite, pero no añadía una condición de aplicación ni revisión.

**Contraejemplo funcional:** se ejecuta contra Docker A y más tarde se cambia el
contexto a B; una inspección fallida de B captura su ID completo. B está detenido
y ese ID coincide con el posterior inspect de B, mientras el estado de A sigue
sin conocerse. Los procesos locales pueden haber terminado en ambos casos. El
código anterior aceptaba ese vínculo sin comprobar siquiera si el contenedor B
se creó después del ensayo original. No hace falta suponer una colisión aleatoria
de IDs: la referencia de partida ya es posterior a la ejecución.

Un ACTIVE_ENVIRONMENT_AUDIT posterior aporta identidad de motor en **esa auditoría**,
pero tampoco prueba qué motor recibió la ejecución anterior. El campo compatible
historical_engine_identity_known=true significa conocido en una auditoría previa,
no en el vuelo. Se añade original_execution_environment_bound=false; no se permite
que ese tipo de referencia posterior eluda la revisión del registro original legacy.

## Cronología y alcance de la corroboración disponible

| Hecho persistido (UTC) | Valor |
| --- | --- |
| Creación del contenedor observado | 02/10/2026 07:28:34.87176229 |
| Último StartedAt de Docker | 16/10/2026 16:41:55.313301992 |
| Inicio del primer worker | 18/10/2026 21:14:38.208705 |
| Inicio executor v2 | 18/10/2026 21:18:50.566241 |
| Último fin registrado de jobs/report | 18/10/2026 21:19:09.145298 |
| FinishedAt del contenedor | 19/10/2026 18:01:24.5530994 |
| Inspección fallida usada como referencia | 19/10/2026 18:38:58.438441 |
| Inspección ad234044 | 19/10/2026 19:06:18.905301 |

El diagnóstico conservado del 18/10 (`read_only_observations/final_metadata.json`)
registró **exactamente el mismo StartedAt**, estado running y PID interno del motor
6735. No guardó ID completo de contenedor ni ID del motor. Corrobora la continuidad
probable del arranque, pero no convierte el nombre/PID/fecha en identidad autenticada.
Los hashes y la comparación están en offline_analysis.json del archivo de revisión.
ExitCode=255 no identifica causa ni resultado del vuelo; no se asocia a 124/GUI.

Las comparaciones entre registros host y Docker son **consistencia condicional**:
ambos se presentan como UTC de pared, pero hace falta una base para aceptar que
esos relojes eran comparables y no hubo saltos relevantes. No son timestamps ROS,
no se calcula edad de simulación, y el orden temporal no demuestra continuidad de
endpoint. Una creación posterior a la actividad original contradice el vínculo
propuesto bajo esa base de relojes y bloquea. La terminación puede preceder al
registro final de un ERROR por timeout/postprocesado; no se exige que el contenedor
siga vivo hasta terminar de escribir el informe ni se deduce ausencia de vuelo.

## boot_id, motor y encarnación son identidades distintas

- `process_identity` usa `/proc/PID/stat` y `/proc/sys/kernel/random/boot_id` del
  **host/namespace donde corre el worker**, con start_ticks. Permite reconocer ese
  proceso o su ausencia en ese host; no inspecciona la VM del motor Docker.
- El boot del worker original fue `cbb1fa33-db15-4014-a06b-484e3f0b0dcc`; el de la
  inspección, `f4b6327f-8e51-43b5-9e72-7d0206aacb37`. Bajo continuidad del mismo
  host indican boots diferentes. Si se copió el workspace a otro host, consultar
  su /proc no acredita ausencia de workers en el primero: también debe revisarse
  esa continuidad. El procedimiento no descubre procesos remotos desconocidos.
- `engine_id=2c4ad774-b7c7-4d26-ba0e-690fb9d0ff99` procede de docker info en la
  inspección. No hay valor del motor durante el ensayo con el que compararlo.
  El ID puede persistir tras reiniciar el daemon; no es un contador de reinicios.
- container_id identifica el objeto conservado por Docker. Created e imagen
  ayudan a describirlo; StartedAt/FinishedAt describen su última encarnación.
  Ni el boot del host, ni el ID del motor, prueban por sí solos que Docker reinició,
  que nunca reinició, que no hubo live-restore ni que ese fuera el endpoint original.

## Contrato corregido y procedimiento viable para legacy

Las inspecciones nuevas devuelven binding_review y, sin contradicciones técnicas,
AWAITING_LEGACY_ENVIRONMENT_REVIEW con application_eligible=false y los supuestos
pendientes. No se confunden las razones técnicas vacías con autorización completa.
Se conservan ENVIRONMENT_TERMINATED como base física observada y la incertidumbre
original_execution_environment_bound=false. No se inventa procedencia histórica.

`_binding_review` consulta sólo archivos capturados/verificados: fechas de inicio
de job/report, metadatos actuales y auditoría de referencia con hash. Detecta
fechas ausentes/inválidas, contenedor creado después de la actividad original,
salida anterior al inicio y referencia anterior a los intentos observados. Guarda
los valores/fuentes y el alcance condicional de la comparación. Contradicciones
no se pueden anular con una declaración.

Aplicar sobre **otra inspección vigente**, con autorización separada, exige
`legacy_environment_confirmation` estructurada (también para una referencia ACTIVE
posterior que no registró el entorno durante la ejecución original):

- source=OPERATOR_ENVIRONMENT_REVIEW y engine_id/container_id exactos inspeccionados.
- continuous_project_environment=true: el operador revisó continuidad de despliegue
  y selector Docker, sin cambio conocido de contexto/host remoto, sustitución,
  clonación/restauración de metadatos o traslado del workspace mientras pudieran
  seguir activos workers anteriores.
- wall_clock_comparison_supported=true: existe una base declarada para comparar
  las fechas UTC de host y daemon; no deducirlo de boot_id.
- statement no vacío que explique qué hechos/registros y conocimiento operativo
  respaldan ambas declaraciones; no basta rellenarlo automáticamente desde el JSON.

No se exige obtener retrospectivamente un ID histórico no guardado. Para Joel,
el procedimiento es revisar si se usó el mismo Docker Desktop/despliegue y contexto
entre el ensayo y las inspecciones, si hubo renombrado/recreación/restauración o
traslado de WSL/workspace y qué base de reloj existía. Se puede apoyar en los logs
conservados, comandos históricos y conocimiento de las operaciones realizadas.
La coincidencia exacta de StartedAt y la cronología son corroboración, no sustituto
de esa revisión. Si lo sabe y puede sostenerlo, se registra honestamente como
**declaración administrativa**, no como medición ni autenticación del diálogo.

Si no puede confirmar continuidad o relojes, no declarar true. Conservar restricciones
y revisar los posibles endpoints/hosts originales con acceso de sólo lectura
**autorizado aparte**, o aportar un registro técnico histórico auténtico que cierre
el vínculo. No arrancar el simulador para producir esa evidencia y no fabricar un
ID retrospectivo. Esta versión no implementa una vía alternativa para descartar
múltiples hosts/contextos desconocidos o metadatos clonados; queda identificada esa
carencia sin un force-unlock genérico.

La declaración queda en la solicitud/aplicación vinculada a ID y SHA-256 exactos.
La revalidación bajo exclusión sigue exigiendo mismos archivos/procesos, referencia,
engine/container/metadatos y STOPPED, mismo boot del host de inspección y TTL.
Idempotencia, barrera durable e historial se conservan; una declaración no rescata
una inspección caducada ni contradicciones. Aplicaciones anteriores ya guardadas
siguen siendo consultables/idempotentes; no se reescriben con la política nueva.

La entrada MCP es del agente: esquema y tests garantizan forma, campos y comprobaciones,
**no que el operador haya dicho la verdad ni que Hermes reproduzca fielmente la
conversación**. Si el agente inventa la revisión, no existe en este canal una fuente
autenticada que lo detecte. No se presenta este incremento como resolución de ese
límite ni como prueba de fidelidad del LLM.

## Siguiente paso: revisión e inspección nueva, nunca aplicar ad234044

Primero revisar con Joel los hechos de continuidad y relojes descritos arriba.
Sólo si pueden sostenerse, preparar una declaración; autorización de cierre aparte.
La inspección real nueva sigue siendo sólo lectura y necesita observar otra vez
el estado actual: los metadatos del 19/10 a las 19:06 no se convierten en actuales.

```text
Inspecciona sólo en lectura las restricciones de la secuencia c6eeb645-17d2-4081-9afb-cecfd23af393 y devuelve una inspección nueva con revisión del vínculo legacy, identidad y estado actual del entorno, cronología, propietarios, versiones, procesos, hash, vigencia y supuestos pendientes; no deduzcas continuidad ni identidad del motor del boot del host, no apliques ad234044-4e5d-4785-b8c4-43f05b89a54a ni otra reconciliación, no liberes reservas, no arranques ni reinicies y no vueles.
```

Resultado esperado: AWAITING_LEGACY_ENVIRONMENT_REVIEW si el entorno sigue detenido,
las comprobaciones técnicas pasan y falta la revisión administrativa. BLOCKED ante
contradicción/dato ausente. Nunca asumir el estado actual sin esa observación futura.

### Verificación offline de esta revisión

Tests afectados finales: **114 passed in 6.04s**. Suite completa final:
**549 passed in 21.36s**. Sintaxis: **28 archivos Python**, **5 Bash** y observador
Python embebido. `git diff --check` sin avisos; código/docs nuevos limpios. Nueve
piezas brutas anteriores mantienen avisos de whitespace y no se normalizan.
**502 archivos previos** conservan hashes, incluidas inspecciones, reservas,
PASSED/ERROR y archivos de evidencia anteriores. La aplicación real de ad234044
sigue ausente. Regresiones: cambio de contexto/creación posterior, cronología
incompleta/contradictoria, revisión ausente/incoherente, boot de host distinto sin
prueba de motor, referencia ACTIVE posterior, ERROR registrado tras la salida,
caducidad, reserva e informes intactos, esquema/dispatch MCP y auditoría de la
atribución administrativa no autenticada. También se mantienen las carreras de
admisión/lifecycle con barreras. No se ejecutó LLM ni se probó obediencia por frases.
Logs/manifiesto en `simulation/ros2_gazebo/results/legacy_binding_review_2026_10_19/`.


## Seguimiento: Joel no puede declarar continuidad ni relojes históricos

Las nuevas comprobaciones aportadas coinciden con el objeto visto en ad234044,
pero no completan el vínculo original. No rellenar los dos true con hechos que
Joel desconoce. El código ya bloquea esa aplicación y no se modifica aquí.
[Fuentes históricas candidatas, búsqueda finita y propuesta administrativa exclusiva
del caso](legacy-administrative-retirement-c6eeb645.md). La propuesta no está
implementada/autorizada ni se presenta como reconciliación técnicamente verificada.
No hace falta otra inspección MCP para concluir que falta ese dato histórico.
