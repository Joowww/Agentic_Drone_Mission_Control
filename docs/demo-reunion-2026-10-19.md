# Demo del TFG — 19 de octubre de 2026, 10:30 (Europe/Madrid)

Guion de **6 minutos y 15 segundos**, ampliable hasta 7 minutos con preguntas.
Se muestran evidencias guardadas: no hace falta arrancar simulación, volar ni
acceder a un proveedor LLM. Los comandos siguientes sólo leen copias locales.
Las consultas opcionales de Hermes son históricas y no autorizan operaciones.

## Preparación antes de la reunión

Abrir este documento y una terminal. Ejecutar este bloque una vez y mantener la
misma terminal para los tres bloques de lectura posteriores:

```bash
cd /home/joelm/TFG/Agentic_Drone_Mission_Control
DEMO_RESULTS=simulation/ros2_gazebo/results
DEMO_LOMA="$DEMO_RESULTS/hermes_skill_repetition_2026_10_18/artifacts/missions/generated/drafts/f4463a1d-d4b1-4d9e-b986-809a5c43f28a/0dde4214-9cca-4514-9176-25607adaea39"
DEMO_V2="$DEMO_RESULTS/simulated_vehicle_v2_2026_10_18/artifacts/missions/generated/preflights/7162bce5-3635-4a76-bf02-6a5a22612aab"
DEMO_SEQ="$DEMO_RESULTS/sequential_preflight_diagnostic_2026_10_18/c6eeb645-17d2-4081-9afb-cecfd23af393"
```

Copias disponibles bajo `simulation/ros2_gazebo/results/`, con manifiestos de
rutas y SHA-256; no se depende de reconstruir el estado de `missions/generated`:

| Ejemplo | Carpeta de resultados | Documentos de referencia |
| --- | --- | --- |
| Planificación | `hermes_skill_repetition_2026_10_18` | [Verificación geométrica](../simulation/ros2_gazebo/results/hermes_skill_repetition_2026_10_18/artifact_verification.json), [evaluación y límites](../simulation/ros2_gazebo/results/hermes_skill_repetition_2026_10_18/assessment.json), [manifiesto](../simulation/ros2_gazebo/results/hermes_skill_repetition_2026_10_18/manifest.json) |
| Ensayo individual v2 | `simulated_vehicle_v2_2026_10_18` | [Verificación offline](../simulation/ros2_gazebo/results/simulated_vehicle_v2_2026_10_18/offline_checks.json), [manifiesto](../simulation/ros2_gazebo/results/simulated_vehicle_v2_2026_10_18/manifest.json) |
| Secuencia incompleta | `sequential_preflight_diagnostic_2026_10_18/c6eeb645-17d2-4081-9afb-cecfd23af393` | [Diagnóstico](../simulation/ros2_gazebo/results/sequential_preflight_diagnostic_2026_10_18/c6eeb645-17d2-4081-9afb-cecfd23af393/README.md), [manifiesto](../simulation/ros2_gazebo/results/sequential_preflight_diagnostic_2026_10_18/c6eeb645-17d2-4081-9afb-cecfd23af393/manifest_final.json) |

Las dos primeras carpetas están versionadas. La carpeta diagnóstica está presente
como evidencia incorporable a Git, todavía sin seguimiento en el árbol revisado.
`DEMO_LOMA` contiene misión, finalización, borrador/estado fuente y `.plan`;
`DEMO_V2` contiene misión, entrada, job, informe y log del worker;
`DEMO_SEQ` conserva operación, hijos, reservas, logs y observaciones posteriores.

## 0:00–0:45 — Qué aporta el sistema

**Decir:** «Hermes interpreta la conversación y selecciona herramientas. MCP
expone sus contratos y resultados estructurados. El lenguaje natural y el JSON
convergen en `MissionDefinition`. LangGraph conserva el estado del ensayo y
conecta snapshot, validación, readiness, compatibilidad, ejecución y análisis.
El código determinista aplica los controles de seguridad; el executor vuelve
a pasar su gate antes de mandar órdenes ROS 2. La conversación no sustituye
esas comprobaciones ni el consentimiento explícito para ensayar».

La correspondencia es `drone_01 → v1` y `drone_02 → v2`. La exclusión global
permite como máximo una ejecución de vuelo del proyecto a la vez. Esto no
demuestra coordinación simultánea ni separación entre vehículos.

## 0:45–3:00 — Ejemplo 1: conversación → geometría → misión y .plan

**Mostrar como conversación histórica; no reenviar estos textos para escribir
otro borrador durante la demo.**

Petición inicial:

```text
Quiero preparar una misión nueva llamada Parcela Loma Repetición con un recorrido rectangular de 40 por 20 metros; guarda lo que sabemos y pregúntame las decisiones y datos pendientes, sin iniciar simulación ni vuelo.
```

Después de aportar HOME en latitud 41, longitud 2 y referencia relativa cero,
el operador dejó deliberadamente ambigua la orientación:

```text
Quiero que el recorrido vaya hacia el este y vuele a 8 metros sobre HOME; conserva lo que esté claro y pregúntame lo necesario para resolver la orientación y las demás decisiones, sin finalizar ni ejecutar nada.
```

**Decir:** «En la repetición visible, Hermes conservó los 8 metros y preguntó
qué arista se orientaba. “Hacia el este” por sí solo no decide el eje del
rectángulo. El operador confirmó después la longitud de 40 m orientada al este,
a 90° desde el norte, sentido horario, HOME central, cierre y regreso; también
completó vehículo, objetivo, condiciones y límites para finalizar».

El tramo de finalización está conservado en
[la transcripción](../simulation/ros2_gazebo/results/hermes_skill_repetition_2026_10_18/transcripts/finalization_raw.txt);
la aclaración previa aparece en
[extractos identificados](../simulation/ros2_gazebo/results/hermes_skill_repetition_2026_10_18/early_transcript_excerpts.json).
No hay argumentos/resultados completos de todas las llamadas ni snapshots de
cada revisión intermedia: la aclaración visible y la geometría final son
evidencias distintas.

**Ejecutar esta lectura compacta:**

```bash
.venv/bin/python - "$DEMO_LOMA" <<'PY'
import hashlib, json, sys
from math import cos, dist, radians
from pathlib import Path
p = Path(sys.argv[1]); m = json.loads((p/'mission.json').read_text()); f = json.loads((p/'finalization.json').read_text())
g = f['geometry_intent']; route = m['route']; h = route['home']; w = route['waypoints']
plan = p/Path(f['validation']['qgc_plan_path']).name
assert hashlib.sha256((p/'mission.json').read_bytes()).hexdigest() == f['mission_sha256']
assert hashlib.sha256(plan.read_bytes()).hexdigest() == f['qgc_plan_sha256']
xy = [((v['longitude']-h['longitude'])*111320*cos(radians(h['latitude'])), (v['latitude']-h['latitude'])*111320) for v in w]
print('Borrador:', f['draft_id'], 'revisión:', f['draft_revision'], '| finalización:', f['finalization_id'])
print('Geometría:', g['length_m'], 'x', g['width_m'], 'm;', g['orientation_deg'], 'grados;', g['traversal'], '; HOME:', g['home_position'])
print('Aristas locales (m):', [round(dist(a,b), 3) for a,b in zip(xy,xy[1:])])
print('WP (N,E) m:', [(v['waypoint_id'], round(y,2), round(x,2)) for v,(x,y) in zip(w,xy)])
print('Alturas:', sorted({v['altitude_m'] for v in w}), g['altitude_reference'], '| cierre:', xy[0] == xy[-1], '| regreso:', route['return_to_home'])
v = f['validation']; print('Validación guardada:', v['mission_status'], v['execution_status'], '| motivos/errores:', v['failure_reasons'], v['errors'])
print('Plan:', plan.name, plan.stat().st_size, 'bytes; ambos SHA-256 coinciden | consentimiento:', f['flight_consent'])
print('SHA-256 misión:', f['mission_sha256'])
PY
```

**Se verá:** revisión 4 del borrador
`f4463a1d-d4b1-4d9e-b986-809a5c43f28a`, finalización
`0dde4214-9cca-4514-9176-25607adaea39`, aristas locales **40, 20, 40, 20 m**,
orden **NO → NE → SE → SO → NO**, cinco puntos `navigate` a **8 m sobre HOME**,
cierre y regreso solicitados. La aproximación local del generador no equivale
a una medición geodésica exacta. Validación persistida **FEASIBLE / APPROVED**,
exportación `parcela_loma_repeticion_001.plan` de **4381 bytes** y consentimiento
de vuelo **NOT_GRANTED**. No se atribuye a esta misión un vuelo realizado.

**Decir:** «La finalización ya construye, valida y exporta; en el tramo visible
no aparece una segunda exportación. El fichero `.plan` es una salida para QGC,
no evidencia de que ArduPilot lo haya cargado o ejecutado. `APPROVED` es un
resultado de validación, no permiso de vuelo».

La repetición también tuvo un error de JSON, un intento fallido de `execute_code`
y un resumen final incorrecto de coordenadas y del término RTL. El nombre
persistido es `Parcela Loma Repeticion`, sin tilde. Se muestran las coordenadas
de los archivos, no el resumen erróneo. Una repetición no acredita fidelidad
global del agente ni mejora estadística; la procedencia tampoco autentica el
diálogo. La intención de regreso, el comando 20 exportado en este `.plan` y el
executor que navega al lanzamiento y después ordena LAND tienen semánticas distintas.

## 3:00–4:30 — Ejemplo 2: ensayo individual drone_02 / v2

**Decir:** «Este es otro ejemplo: una misión JSON de navegación de tres puntos,
no un vuelo de Parcela Loma. El primer ensayo individual operativo de v2 quedó
persistido como PASSED y ahora sólo leemos su evidencia».

```bash
.venv/bin/python - "$DEMO_V2" <<'PY'
import hashlib, json, sys
from datetime import datetime
from pathlib import Path
p = Path(sys.argv[1]); r = json.loads((p/'report.json').read_text()); j = json.loads((p/'job.json').read_text())
e = r['executor_result']; a = r['analysis']; events = e['events']; dt = datetime.fromisoformat
assert hashlib.sha256((p/'mission.json').read_bytes()).hexdigest() == r['mission_sha256']
assert r['vehicle_selection'] == r['expected_vehicle_selection'] == {'vehicle_id':'drone_02','simulated_vehicle':'v2'}
print('Ensayo:', r['run_id'], '| misión:', r['mission_identity']['mission_id'], '| vehículo:', e['vehicle_id'], e['vehicle'])
print('Job:', j['job_state'], '| informe:', r['status'], '| executor:', e['status'], '| success:', e['success'])
print('WP esperados/observados:', a['expected_waypoint_ids'], a['observed_waypoint_ids'], '| completados:', e['waypoints_completed'])
print('Regreso alcanzado:', any(v['event']=='RETURN_HOME_REACHED' and v.get('reached') is True for v in events))
print('Aterrizaje:', json.dumps([{k:v[k] for k in ('landed','armed','flying')} for v in events if v['event']=='LANDED']))
print('Análisis:', sum(v is True for v in a['checks'].values()), '/', len(a['checks']), '| motivos:', r['reasons'], a['reasons'], '| tolerancias:', a['tolerances'])
print('Duración workflow desde snapshot:', round((dt(r['finished_at'])-dt(r['transitions'][0]['started_at'])).total_seconds(),3), 's; executor:', round((dt(r['execution_finished_at'])-dt(r['execution_started_at'])).total_seconds(),3), 's')
print('Intervalo total del informe desde admisión:', round((dt(r['finished_at'])-dt(r['started_at'])).total_seconds(),3), 's | source_artifact:', r['source_artifact'])
print('SHA-256 misión:', r['mission_sha256'])
PY
```

**Se verá:** `7162bce5-3635-4a76-bf02-6a5a22612aab`, **drone_02 / v2**,
job **FINISHED**, informe **PASSED**, executor **COMPLETED / success=true**,
**WP1–WP3**, regreso alcanzado y **landed=true / armed=false / flying=false**.
Los **11/11** checks del análisis son verdaderos, sin motivos de fallo.
Tolerancias: horizontal **1 m**, altura **0,75 m**.

Duraciones: workflow desde el nodo snapshot **297,181 s**, executor
**285,972 s**, intervalo del informe desde admisión **299,843 s**. Incluyen
lecturas, esperas y comprobaciones: **no son tiempo en vuelo**; los eventos no
aportan timestamps suficientes para calcularlo.

`source_artifact=null` identifica este ensayo independiente: no hay vínculo a
la finalización de Parcela Loma. No demuestra agricultura, seguimiento de la
velocidad comandada, carga del `.plan`, inmovilidad de v1 ni hardware real.
La consulta del operador comunicó entonces reservas liberadas; el informe no
es una auditoría persistente de esa liberación ni acredita ausencia de reservas
posteriores. Su readiness es histórico, no una comprobación actual ni una
confirmación visual de Gazebo. PASSED no autoriza otra ejecución y tampoco
explica el fallo anterior de WP3.

## 4:30–5:45 — Estado honesto de la secuencia posterior

**Decir:** «La orquestación secuencial se probó después: v1 terminó PASSED;
el segundo hijo produjo ERROR sin resultado estructurado del executor. La
secuencia está incompleta y mantiene restricciones; no la reanudamos en la
reunión. El PASSED individual anterior de v2 sigue siendo válido para aquel
ensayo, no convierte este segundo intento en éxito».

```bash
.venv/bin/python - "$DEMO_SEQ" <<'PY'
import json, sys
from pathlib import Path
p = Path(sys.argv[1]); b = p/'artifacts/missions/generated'
o = json.loads((b/'preflight_sequences/c6eeb645-17d2-4081-9afb-cecfd23af393/operation.json').read_text())
print('Secuencia:', o['sequence_id'], o['job_state'], o['phase'], '| resultado:', o['result_status'])
for interface,run in [('v1','467f7ec6-b2a6-4b68-9d97-766d85732f8e'),('v2','1b69dfc7-0707-4b68-a009-062610418fe4')]:
    r = json.loads((b/'preflights'/run/'report.json').read_text())
    print(interface, run, '| informe:', r['status'], '| executor presente:', r['executor_result'] is not None, '| motivos:', json.dumps(r['reasons']))
print('Reservas archivadas:', {v:json.loads((b/'vehicle_locks'/f'{v}.json').read_text())['state'] for v in ('sequence','v2')})
a = json.loads((p/'assessment.json').read_text())
for v,t in a['current_telemetry_observed'].items():
    s = t['latest_status']['message']; print('Observación posterior:', v, t['latest_status_europe_madrid'], 'armed=', s['armed'], 'flying=', s['flying'])
PY
```

La operación `c6eeb645-17d2-4081-9afb-cecfd23af393`, clave
`joel-secuencia-sitl-01`, conserva **UNCONFIRMED / reconciliation_required**,
`result_status=null`. El hijo v1 `467f7ec6-b2a6-4b68-9d97-766d85732f8e` tiene
PASSED. El v2 `1b69dfc7-0707-4b68-a009-062610418fe4` tiene informe **ERROR**,
`FlightControlError`, retorno **124**, `executor_result=null`, `analysis=null`;
su aceptación por el coordinador queda UNCONFIRMED. Las reservas global de
secuencia y de v2 están conservadas como UNCONFIRMED.

La inspección del código sitúa el hueco de evidencia en lecturas iniciales de
origen o posición previas al bloque principal de captura del executor. **No se
identificó cuál falló ni su causa**: el 124 no lo demuestra. Worker terminado
no significa vehículo aterrizado. A las **23:42 CEST del 18/10**, consultas
posteriores guardadas observaron `armed=false / flying=false` en ambos vehículos,
con varias muestras y stamps que avanzaban; no reparan el resultado histórico,
no son telemetría actual de la reunión ni liberan reservas. No hay reconciliación.
La GUI negra fue comunicada por el operador; no se ha demostrado causa común
con el fallo ROS 2, y readiness no confirma una imagen correcta.

## Consultas históricas opcionales y alternativa offline

Estos prompts son opcionales para Joel en la reunión; **no se han ejecutado al
preparar el guion**. Cada uno sólo solicita lectura por identificador:

```text
Consulta la finalización 0dde4214-9cca-4514-9176-25607adaea39 del borrador f4463a1d-d4b1-4d9e-b986-809a5c43f28a y resume geometría, validación y exportación existentes; no guardes, finalices, exportes de nuevo ni ejecutes nada.
```

```text
Consulta históricamente el ensayo 7162bce5-3635-4a76-bf02-6a5a22612aab y resume vehículo, resultado, waypoints, regreso, aterrizaje y límites; distingue duraciones del workflow y executor de tiempo en vuelo y no inicies operaciones.
```

```text
Consulta la secuencia c6eeb645-17d2-4081-9afb-cecfd23af393 y explica resultados individuales, incertidumbres y restricciones; no la reanudes, no repitas ensayos y no modifiques ni liberes reservas.
```

Si Hermes falla, tarda o propone operaciones, continuar directamente con los
tres bloques de lectura de este documento. Son una alternativa **totalmente
offline**: Python estándar, copias bajo `results`, sin importar módulos del
proyecto ni abrir Docker, ROS, MCP o un proveedor LLM. Mostrar archivos y
transcripciones preservados permite separar resultados persistidos de lo que
el agente dijo; no hace falta reconstruir misiones ni regenerar exportaciones.

Comprobación de preparación: los tres bloques se ejecutaron offline y se
contrastaron los manifiestos de las tres carpetas (**22, 10 y 320 entradas**,
respectivamente), sin discrepancias SHA-256. Las comprobaciones de hash de los
bloques verifican misión/plan del ejemplo 1 y snapshot del ejemplo 2; no
autentican el diálogo ni resuelven todos los riesgos TOCTOU. No se ha hecho una
nueva prueba operativa ni una evaluación conversacional del LLM para esta demo.

## 5:45–6:15 — Tres próximos pasos

1. **Diagnóstico estructurado de las lecturas iniciales:** conservar operación,
   vehículo, topic, tiempos, error y contexto parcial para identificar la lectura
   fallida sin deducir una causa del código 124.
2. **Reconciliación explícita y recuperación de GUI:** revisar evidencias,
   propietarios y telemetría fresca antes de decidir sobre restricciones;
   preservar ERROR/UNCONFIRMED históricos. Recuperar la GUI sólo con autorización
   y cuando se haya resuelto la incertidumbre, comprobando la imagen con el operador.
3. **Repetición autorizada de la secuencia:** después de la reconciliación,
   readiness y consentimiento nuevo, realizar otro ensayo estrictamente
   secuencial con una identidad nueva; conservar ambos intentos y sus límites.
