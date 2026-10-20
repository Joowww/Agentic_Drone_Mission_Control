# c6eeb645: evidencia disponible y posible retiro administrativo

> Implementación posterior offline del procedimiento exclusivo: [uso, autorización, auditoría y recuperación](administrative-retirement-c6eeb645.md). El texto y JSON de propuesta anteriores se conservan como historia; no son autorización de ejecución.

Decisión del 19/10/2026: **no aplicar reconciliación técnica ni rellenar hechos
históricos desconocidos**. No hace falta otra modificación del código para que
rechace esos argumentos: ya los rechaza. El retiro excepcional descrito abajo es
una propuesta **documentada, no implementada, no autorizada y no ejecutable**.
No se ha ejecutado Docker, ROS, inspección operativa, liberación, arranque ni vuelo.

## Comprobaciones aportadas por Joel

Transcripción de su mensaje, no salida ejecutada por Codex ni TXT original:
[archivo y manifiesto](../simulation/ros2_gazebo/results/legacy_evidence_followup_2026_10_19/manifest.json).
A las 21:36:28 CEST / 19:36:28 UTC comunica MSI, Ubuntu 24.04.4, contexto default,
endpoint unix:///var/run/docker.sock, sin salida de DOCKER_HOST/DOCKER_CONTEXT;
engine 2c4ad774-b7c7-4d26-ba0e-690fb9d0ff99 y container
0274e4fd856ab21e888a1820ea3867f2e2ec8641e0cb39c4658d8f01f9fcd30f.
Creación/imagen/StartedAt/FinishedAt coinciden con ad234044; exited, Running=false,
Pid=0. Eso corrobora el mismo objeto observado **ahora**, no el endpoint original.
La equivalencia de las dos horas sólo muestra conversión local/UTC actual, no
sincronización histórica entre host WSL y daemon Docker Desktop.

Joel sabe que WSL se cerró y volvió a abrirse. No puede sostener continuidad histórica
de contexto/despliegue ni comparabilidad histórica de relojes. No se redefine
«desconocido» como true ni «sin conocimiento de un cambio» como prueba de continuidad.
Boot del host, engine_id y encarnación del contenedor siguen siendo conceptos distintos.

Se examinaron **336 archivos**: archivo diagnóstico del 18/10 y originales de la
secuencia y sus dos hijos. No hay campos de engine/container ID ni coincidencias de
los IDs actuales en esos archivos. `container_logs_capture.json` registra
`docker exec -i tfg-ardupilot-gazebo python3 -`: conserva el selector por nombre,
no el contexto/daemon que lo resolvió ni el ID completo. `final_metadata.json`
conserva el mismo StartedAt, pero tampoco esos identificadores. Versiones y alcance
exactos en historical_search.json. Esto no prueba que no existan logs fuera de ese archivo.

## Qué falta y dónde podría existir

Falta un registro contemporáneo que vincule **la petición/ejecución original**
(worker, petición exec o correlación específica equivalente) con el daemon/endpoint
y contenedor completos. Un ID de contenedor obtenido después, nombre, imagen,
StartedAt o eventos genéricos con fechas parecidas no bastan por sí solos.
Para usar la comparación entre fechas host/daemon también falta una base histórica
para relacionar ambos relojes; la hora actual y la zona +02:00 no la proporcionan.

Sólo son candidatas fuentes **ya existentes**: eventos retenidos del daemon,
logs de Docker Desktop/VM que incluyan peticiones exec y su destino, o una traza
host original con ese vínculo. Para relojes, registros antiguos de sincronización
host y daemon/VM, o una correlación identificable común. Nada de activar debug,
reiniciar o generar logs ahora para demostrar el pasado. Si no se registró o fue
rotado, no puede reconstruirse fielmente desde las lecturas actuales.

### Búsqueda acotada de sólo lectura, preparada y no ejecutada

Primera comprobación opcional en WSL: eventos del intervalo de la ejecución. La
ventana usa las fechas registradas como pista; no presupone relojes históricamente
idénticos. Cero líneas o timeout no prueban ausencia de actividad ni de vuelo.

```bash
timeout -k 2s 15s docker events --since '2026-10-18T21:10:00Z' --until '2026-10-18T21:30:00Z' --filter type=container --filter container=0274e4fd856ab21e888a1820ea3867f2e2ec8641e0cb39c4658d8f01f9fcd30f --format '{{json .}}'
```

Segunda fuente candidata: inventario de logs **ya existentes** de Docker Desktop
Windows, en una ruta candidata bajo LOCALAPPDATA. El comando comprueba que exista;
no se afirma haber encontrado ese directorio ni que conserve el periodo original.
No leer .docker/config.json, credenciales, llaves ni variables secretas.

```bash
timeout -k 2s 15s powershell.exe -NoProfile -Command '$p=Join-Path $env:LOCALAPPDATA "Docker\log"; if (Test-Path -LiteralPath $p) {Get-ChildItem -LiteralPath $p -Recurse -File -ErrorAction SilentlyContinue | Select-Object FullName,Length,LastWriteTimeUtc} else {"DIRECTORIO_NO_DISPONIBLE"}'
```

Sólo sobre un log de runtime del listado, con ruta realmente obtenida, buscar los
IDs concretos. Sustituir el marcador, sin inventar un archivo. No volcar logs completos.

```bash
timeout -k 2s 15s powershell.exe -NoProfile -Command 'Select-String -LiteralPath "<RUTA_DEL_LOG_DEL_LISTADO>" -SimpleMatch -Pattern "0274e4fd856ab21e888a1820ea3867f2e2ec8641e0cb39c4658d8f01f9fcd30f","2c4ad774-b7c7-4d26-ba0e-690fb9d0ff99" | Select-Object -First 80 Path,LineNumber,Line'
```

Fuente candidata para la parte WSL de los relojes, sólo si persiste ese boot:

```bash
timeout -k 2s 10s journalctl --utc --boot=cbb1fa33db154014a06b484e3f0b0dcc --since '2026-10-18 20:30:00 UTC' --until '2026-10-18 22:00:00 UTC' --unit=systemd-timesyncd.service --no-pager -n 80
```

Un journal vacío/no accesible no prueba que no hubiera sincronización. Un mensaje
de sincronización de WSL tampoco prueba por sí solo el reloj del daemon/VM.
Inspeccionar campos concretos y conservar salida con procedencia/hash antes de
extraer conclusiones. Los comandos sólo se comprobaron con bash -n; no se probaron
contra Docker, Windows o journal reales y no se garantiza retención/disponibilidad.

**Criterio de cierre de esta búsqueda:** una pasada acotada por las fuentes existentes.
Si no aparece vínculo específico y base temporal suficiente, registrar
NO_RECUPERADO_EN_FUENTES_REVISADAS. No repetir fecha/context/info actual ni inspecciones
MCP esperando que eso aporte evidencia histórica. No marcar PASSED técnico.

## Retiro administrativo excepcional, distinto de reconciliación verificada

Si el vínculo no es recuperable, el operador puede **autorizar retirar estas
restricciones locales aceptando explícitamente la incertidumbre**, sin afirmar
continuidad, relojes, aterrizaje o terminación del entorno original desconocido.
Eso es una decisión administrativa sobre archivos de este checkout, no una nueva
fuente de hechos ni permiso para controlar un posible entorno anterior.

Propuesta concreta de alcance y hashes, sin ejecución:
[administrative_retirement_c6eeb645_proposal_2026_10_19.json](../evaluation/operations/administrative_retirement_c6eeb645_proposal_2026_10_19.json).
Permite revisar únicamente estos dos registros exactos:

| Registro | Propietario | SHA-256 |
| --- | --- | --- |
| sequence.json | c6eeb645-17d2-4081-9afb-cecfd23af393 | 47385b4ebc900482d1202131e2421d55a316c7144ccce8bc135cabfaaf73505e |
| v2.json | 1b69dfc7-0707-4b68-a009-062610418fe4 | c7bcb0a629e02e9676a5b25b43a089b73686c23ce4e39e7a4368936c59b91954 |

Una eventual implementación revisada de **este único caso**, antes de poder usarse,
debe cumplir lo siguiente:

1. Autorización explícita para el retiro administrativo de estos UUID/hashes,
   aceptando original_environment_termination=UNKNOWN y vínculo no verificado.
   No pedir declaraciones de hechos que Joel desconoce. ID/hash de la propuesta
   y evidencias deben quedar en una auditoría separada.
2. Bajo mutex global de ejecución y registry.lock, comprobar propietarios/versiones
   exactos, 16 versiones/ausencias de artefactos fijadas, ausencia de restricciones
   nuevas y de procesos pertinentes/PID reciclados y mutex del executor libre.
   Los procesos se comprueban en el host local; el alcance no se extiende a hosts
   históricos desconocidos. Cualquier cambio/incoherencia detiene la operación.
3. Obtener metadatos recientes y coherentes del **motor/contenedor actual fijado**,
   nuevamente exited/Running=false/Pid=0. Comparar identidad/estado antes de actuar;
   si no puede verificarse o cambió, bloquear. No reutilizar ad234044 caducada ni
   la transcripción de las 19:36 como evidencia vigente de una acción posterior.
4. Persistir intención administrativa, incertidumbres, autorización y barrera
   durable; archivar exactamente las reservas originales con fsync antes de retirar
   exclusivamente esos registros. Sin borrado manual, force flag, rutas/propietarios
   arbitrarios ni liberación basada sólo en ausencia del proceso.
5. Registrar en auditoría separada ADMINISTRATIVELY_RETIRED_UNVERIFIED, conservando
   operación UNCONFIRMED, hijo v1 PASSED, hijo v2 ERROR y todos los informes/evidencias.
   No denominarlo PASSED o reconciliación técnicamente verificada. Ante interrupción,
   conservar barrera/restricciones restantes; no reanudar automáticamente.
6. Sin arranque/reinicio, control o vuelo y sin consentimiento heredado. Admisiones
   futuras del checkout actualizado mantienen su exclusión común; el retiro no prueba
   que no exista otra simulación antigua fuera de ese registro. Readiness, recuperación
   GUI y cada futuro ensayo requieren decisiones/autorizaciones independientes.

**No está implementado ni autorizado.** `apply_execution_reconciliation` actual no
es esa vía: exige los dos true que Joel no puede sostener. No llamarlo con declaración
ficticia, no cambiar el JSON de inspección y no mover/eliminar reservas por terminal.
Materializar este protocolo requeriría un encargo explícito y una implementación
puntual revisable; no se ha añadido un bypass genérico ni otra herramienta aquí.

## Decisión y siguiente paso concreto

El caso continúa bloqueado para reconciliación técnica. La repetición de la inspección
MCP no resuelve el dato histórico ausente. Siguiente paso de sólo lectura: consultar
una vez los eventos del intervalo con el primer comando. Si no contienen un vínculo
específico recuperable, revisar los logs existentes indicados y cerrar la búsqueda;
entonces la alternativa honesta es revisar/autorizar la propuesta administrativa,
no pedir a Joel certificar lo desconocido. Ninguna de esas acciones está ejecutada.
