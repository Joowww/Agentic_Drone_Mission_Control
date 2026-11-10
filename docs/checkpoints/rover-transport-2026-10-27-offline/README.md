# Cierre offline del transporte — 27 de octubre de 2026

Integración de selección/persistencia cerrada y probada offline. Preparación
operativa **BLOCKED por procedencia incompleta**; identidad completa y movimiento
siguen BLOCKED. No se inició el contenedor, simulación, ROS/DDS, receptor ni agente.
No se instalaron dependencias ni se hicieron staging, commits, push o disposiciones.

Rama/HEAD comprobados: feature/hermes-integration,
83a147dda9065c812e0ff3b931cb22948fe52346. No hay AGENTS.md aplicable.
Todos los archivos inventariados como task_related_files en el checkpoint de parada
coincidían byte a byte al empezar. Ese snapshot no permite distinguir los últimos
cambios del lote desconocido respecto del anterior lote de 324; no se recuperó su
salida. Se revisaron receptor, contrato RPC, puente de observaciones, cierre del
adaptador/executor y rama del driver; se ejecutaron sus pruebas afectadas.
No se tocaron los componentes agrícolas, reporting, flota ni exportación de Claude.

## Cambios finales

- LocalPorts exige preparación explícita, pareja RPC/modelo exacta y digest del
  manifiesto completo. Rechaza esquemas desconocidos, límites o pins incompletos
  y revisa las fuentes de nuevo antes de cualquier apertura.
- Se incluyen los headers locales transitivos, CMake y selector en los pins.
- La interrupción conserva error y resultado de arranque, intenta el cierre una
  sola vez y conserva la prohibición de repetir la apertura. La preparación de
  comandos conserva recibo de interrupción y archivos parciales sin reutilizarlos.
- La captura conserva bytes originales, error inicial y errores de cierre;
  una interrupción cierra el receptor antes de propagarse. Intenta escribir los
  otros recibos aunque falle un canal de persistencia. Un fallo de disco devuelve
  incertidumbre; no puede garantizar persistencia en un disco que rechaza escrituras.
- El CLI nuevo sólo realiza dry-run de archivos host; no abre sesiones.

## Resultados actuales

`pytest.log` y `pytest-result.json`: **450 passed, 22.02 s**, 16 archivos afectados.
Después se añadieron pins transitivos, recibo de interrupción de preparación y
CLI dry-run: `pytest-final-driver.log` y su resultado: **26 passed, 0.75 s**.
Este segundo lote cubre el driver final y se solapa con el primero; no sumar.
No se repitió la suite completa. Las pruebas usan dobles offline y no acreditan
recepción real, cierre real ni identidad. La restauración/cierre de selección y
monitor quedan cubiertos por diagnostic_selection/coordinated_cleanup/passive_driver.
Sintaxis Python, whitespace y manifiestos: véase `verification.json`.

`historical-manifests-verification.json` verifica las 164 entradas originales
(manifiesto 4d9558a2e31b9ea2ec42eca6d8b18cc007ce2cf4049bab011fa561ad59e34faf)
y las 45 entradas del informe offline, sin regenerarlos ni modificarlos.
No se diagnosticó el antiguo historical_proof=false: su salida completa sigue
sin recuperarse y esta tanda no la sustituye con inferencias.

## Artefactos recuperados y carencias

Se copiaron archivos desde el contenedor **detenido** con docker cp y se
inspeccionaron con sha256sum/readelf. Los tres hashes coinciden con el checkpoint:

| Artefacto | SHA-256 |
| --- | --- |
| rover_observation_receiver | 119159b4bba18fd193e0664ad1be6f1f96e491d122c0d951384ae3e9ced3fe98 |
| micro_ros_agent | 0743391476c0d89a2d3195ec6f7330692275790cc781f4443528c5b716b5c3f3 |
| libmicroxrcedds_agent.so.2.4.2 | 26b113bf6742187768e0b4b93cdb68859634c1104ae576a34dc326732514e240 |

Las inspecciones ELF y receiver.CMakeCache.txt quedan aquí de forma durable.
La caché señala /workspace/tfg/tools/rover_identity_probe, Release, contrato C++
activado y los prefijos ROS/ardu instalados. Esto NO prueba qué bytes tenían las
fuentes cuando se compiló. Faltan logs originales sellados, snapshot de fuentes
compiladas y pins completos de dependencias/headers. No se reconstruyó: hacerlo
con el SDK del contenedor exigiría reactivarlo, fuera de la autorización actual.
No se han revalidado los binarios del bridge/modelo en este cierre.

[transport-build-2026-10-27.json](../../../tools/rover_identity_probe/transport-build-2026-10-27.json)
registra hashes, fuentes actuales y carencias. Se ubica junto al receptor según
inventory.json y build-verification-2026-10-26.json, sin inventar otra ubicación.
[reader.transport.json](../../../tools/rover_identity_probe/reader.transport.json)
es una preparación **incompleta**, con prepared=false y native_dependencies vacío;
no es una selección válida. No cambiar esa bandera para eludir las carencias.
El selector RPC existente permanece explícito, sin despliegue o selección automática.
Los hashes finales del código/documentación están en `manifest.json` de este cierre.

## Comando seguro actual

Desde la raíz del repositorio:

```bash
.venv/bin/python -m tools.rover_xrce_trace.passive_trial --dry-run \
  --agent-manifest tools/rover_xrce_trace/diagnostic-agent.rpc.json \
  --reader-manifest tools/rover_identity_probe/reader.transport.json
```

Resultado esperado: BLOCKED, selection_files_valid=false,
Receiver preparation unavailable; no opening. Sólo comprueba archivos host:
no consulta Docker ni ejecuta binarios. Incluso una selección válida conservaría
BLOCKED hasta comprobar artefactos y autorización actual fuera del dry-run.

## Receta de preparación pendiente, no ejecutada

Las herramientas existentes permiten preparar copias nuevas sin instalar:

```bash
.venv/bin/python -m tools.rover_xrce_trace.prepare_identity \
  /home/joelm/TFG/ardupilot_ros2_ws/build/micro_ros_agent/agent/src/xrceagent \
  /home/joelm/TFG/ardupilot_ros2_ws/src/ros_gz/ros_gz_bridge \
  /tmp/identity-source-NEW
```

En un entorno SDK ya autorizado, guardar stdout/stderr, comandos y códigos de
retorno en un directorio nuevo durable. Copiar fuentes/preparación a /tmp aislado;
no usar el árbol compartido mutable como snapshot de compilación. Para el receptor:

```bash
cmake -S /tmp/transport-source-NEW/tools/rover_identity_probe \
  -B /tmp/transport-build-NEW -DCMAKE_BUILD_TYPE=Release \
  -DTFG_BUILD_OFFLINE_CONTRACT_TESTS=ON
cmake --build /tmp/transport-build-NEW \
  --target rover_observation_receiver rover_observation_contract_test --parallel 2
```

Requiere source previo de los setup.bash instalados de ROS Humble y ardu_ws.
Para la pareja RPC, build.sh acepta la copia native producida por prepare_identity:

```bash
bash /workspace/tfg/tools/rover_xrce_trace/build.sh \
  /tmp/identity-source-NEW/native /tmp/rpc-build-NEW
```

Estas recetas no ejecutan los binarios y usan dependencias instaladas. Fijar antes
y después hashes del snapshot y del cierre transitivo de headers/bibliotecas,
versiones de compilador/CMake y las salidas de readelf. Conservar logs y hashes
nuevos junto a los históricos. Cualquier hash distinto exige revisión explícita
del selector y de la pareja; no reemplazar automáticamente la pareja revisada.
No afirmar que la receta reproduce exactamente el hash histórico sin ejecutarla
y verificarla. Un build no equivale a selección, ejecución o identidad acreditada.

La siguiente operación que requiere autorización es reactivar un entorno SDK
sin simulación para completar procedencia/build aislado. Una posterior captura
pasiva real necesita autorización independiente y precheck fresco; movimiento
permanece BLOCKED y no forma parte de esa autorización.
