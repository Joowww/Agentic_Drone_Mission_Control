# Evidencias conversacionales conservadas — 18/10/2026

Copias seleccionadas de artefactos locales comunicados por el operador. No se
realizó un nuevo ensayo, vuelo ni llamada MCP operativa al preparar este archivo.
El [manifiesto](manifest.json) contiene rutas originales absolutas, rutas de copia,
SHA-256 y tamaño de cada uno de los **31 archivos copiados byte a byte**. Incluye
los índices de solicitud ya existentes que identifican las propuestas/revisiones.
No se copiaron locks ni se cambiaron reservas.

| Artefacto | Identificador | Resultado guardado comprobado offline |
| --- | --- | --- |
| Finalización geométrica | 8be78baa-4cf4-4f65-8531-9388d030c3ed | FEASIBLE / APPROVED; borrador 1f84f808-c688-48c9-b7da-1b1c4b29c094, revisión 4, geometría 3 |
| Revisión al 95% | b880d6c3-4557-42c7-ada4-5a04db5e9237 | FEASIBLE / APPROVED; declaración explícita de condición simulada, no telemetría ni sustitución física |
| Revisión al 11% | 89c3da7d-bc20-42ae-baeb-21d4e839355a | NOT FEASIBLE / BLOCKED; reserva insuficiente; `.plan` candidato |
| Propuesta de batería | 727082c5-4008-4bf2-a61e-87b48eed35a8 | PLANNING_REVIEW; fuente 0844c190-59c8-40cf-991e-93cebbd3cf02 |
| Propuesta de WP3 | e44903a2-0405-4ea5-99c7-7233ce0ea333 | INVESTIGATE_EXECUTION; FAILED histórico con recuperación LAND |
| Propuesta de PASSED | ae3bf4c2-3a56-4402-89b9-020e6232d5cf | NO_CORRECTION_REQUIRED; fuente f5f55084-5af6-4e58-ab1a-ce30a13832b3 |
| Propuesta de infraestructura | 4bff56e2-48c9-421f-b8b6-1969aa5ddf74 | INFRASTRUCTURE_PENDING; fuente d7717942-9b43-45c7-bf3a-65b02bb1155a |

Se usaron los verificadores existentes de borrador/finalización/revisión,
identidad y hashes; para las propuestas se contrastaron las copias con las fuentes
y se volvió a evaluar/analizar la evidencia mediante los servicios deterministas,
sin infraestructura. La geometría final es un rectángulo 40x20 m, HOME central,
cinco waypoints por cierre, altitud relativa 5 m y regreso solicitado. Su aprobación
de planificación y exportación no constituye ensayo de esa ruta.

La fuente de infraestructura registra `[1/5] Docker container...` con PASS y
`[2/5] Gazebo server...` con FAIL. No registra ejecución de los controles restantes.
No se comprueba aquí disponibilidad actual. La revisión al 95% conserva literalmente
la declaración de escenario simulado; no se acredita una medición física.

`response_sizes.json` registra consultas Python de sólo lectura a los identificadores
reales, sin usar transporte MCP: JSON UTF-8, sin escapes ASCII, formato compacto
o indentado dos espacios. Para el borrador: detalle 48.842 bytes, resumen 5.698
bytes, reducción del 88,33% en formato indentado. No es una medición de tokens,
tráfico MCP completo, tiempo de respuesta ni frecuencia de compacciones del LLM.

Las copias retienen los campos de ruta originales incrustados en JSON: son
evidencia, no un registro operativo reubicado. Para verificarlas fuera de este
checkout se usan los hashes y `copy_path` del manifiesto; no se ejecutan las rutas
incrustadas. El manifiesto no es una firma ni autentica la conversación. No incluye
su propio hash ni los documentos/mediciones derivados, para evitar autorreferencia.
Las evidencias previas y originales no se modificaron ni normalizaron.

La realización de las conversaciones y las compacciones se registran según las
observaciones del operador. Los archivos respaldan el contenido persistido, no la
fidelidad completa del LLM al diálogo. El PASSED histórico no establece la causa ni
la resolución del fallo WP3 anterior. No se probó resistencia a reinicios del host.

## Ampliación: ensayo geométrico 4bb6a20e (18/10/2026)

Se añaden **6 copias exactas**, para un total de **37 originales conservados**:
`mission.json`, `input.json`, `report.json`, `job.json` y `worker.log` del ensayo
`4bb6a20e-3aff-48ce-8b6f-e66e92a0e6a4`, y el índice de admisión correspondiente a
`joel-rectangulo-preflight-01`. Las 31 copias de la selección inicial permanecen
intactas. El manifiesto anterior se conserva byte a byte en `history/`, con su
SHA-256 registrado en `extensions`; las entradas anteriores no se sustituyen.
El archivo contiene ahora 42 ficheros: 37 copias y cinco documentos derivados
(README, manifiesto actual, manifiesto anterior, mediciones anteriores y nueva
verificación). No se copiaron locks ni se liberaron restricciones.

El [detalle de verificación](preflight_4bb6a20e-3aff-48ce-8b6f-e66e92a0e6a4_verification.json)
registra los cálculos y su alcance. Se ejecutaron offline `verified_source` y
`load_link`, sin infraestructura: validación determinista, análisis recalculado
idéntico al guardado y hashes de la finalización, `.plan` y borrador/metadatos
fuente. Finalización `8be78baa-4cf4-4f65-8531-9388d030c3ed`, borrador
`1f84f808-c688-48c9-b7da-1b1c4b29c094`. La misión fuente, entrada admitida y
snapshot ensayado son idénticos: SHA-256
`fee5185407a7f63810a62f652062454f83790aa2b8a7234f869a7d93eda3a936`.
Informe: SHA-256 `8137aa9c212fe0b0bfc1d5021ed78cfa2961c4054323df71b4b85157e15ebff3`.

Resultado guardado y recalculado: **PASSED**, executor **COMPLETED**, WP1–WP5,
regreso y `LANDED` con `landed=true`, `armed=false`, `flying=false`; los once
checks son verdaderos. Sin fallo ni recuperación registrados. Todos los controles
readiness guardados pasan: Docker container, Gazebo server, ArduPilot processes,
ROS 2 vehicle interfaces y Pre-arm checks. Es readiness histórica, no una consulta
actual. El retorno es navegación al lanzamiento y LAND; no prueba modo RTL.

| Medida a partir de timestamps UTC persistidos | Segundos |
| --- | ---: |
| Workflow: `started_at` → `finished_at` del informe | 480.344587 |
| Llamada al executor: `execution_started_at` → `execution_finished_at` | 471.332987 |
| Worker: `started_at` → `finished_at` del job | 480.244514 |
| Inicio de nodo snapshot → final del informe | 478.735180 |
| Admisión → toma del trabajo por el worker | 0.101906 |

El workflow incluye la admisión y supera 300 s; también los supera el executor.
Estas diferencias de reloj de pared no son una medición monotónica ni tiempo en
vuelo: los eventos no conservan timestamps individuales para calcularlo. Los
0,102 s hasta la toma del worker no miden latencia de respuesta MCP. No hay una
respuesta de admisión cronometrada conservada para este ensayo.

| Evento alcanzado | Error horizontal (m) | Error de altitud (m) |
| --- | ---: | ---: |
| WP1 | 0.555499380 | 0.030029297 |
| WP2 | 0.555500108 | 0.030029297 |
| WP3 | 0.305965658 | 0.000000000 |
| WP4 | 0.555499380 | 0.010009766 |
| WP5 | 0.488362164 | 0.030029297 |
| Regreso | 0.424174983 | 0.030029297 |

Tolerancias originales: horizontal 1 m y altitud 0,75 m; error de despegue
0,109985352 m. Son errores de las observaciones finales aceptadas, no errores
máximos durante la trayectoria. Las cifras completas están en el informe bruto.

`job.json` conserva `FINISHED`, identidad PID/start_ticks/boot_id y tiempos;
`worker.log` conserva toma y final PASSED. La consulta final `FINISHED` y
`vehicle_restriction=null` se atribuye a la transcripción del operador: el estado
FINISHED está además corroborado por el job, pero no se encontró una copia de esa
respuesta ni un registro histórico explícito de liberación. No se consulta la
restricción actual para reconstruirla retrospectivamente.

Se acredita un ensayo SITL de la ruta geométrica persistida. La construcción por
conversación, las inferencias indebidas ante la primera petición incompleta,
exploración redundante y errores de resumen son observaciones del operador; el
impacto sobre compacciones no se evaluó de forma controlada. Tampoco se acredita
causa/resolución del antiguo WP3, agricultura, velocidad comandada, carga del
`.plan` en ArduPilot, reinicio del host ni hardware real. PASSED no autoriza otra
ejecución. Esta ampliación no ejecutó vuelos ni llamadas MCP operativas.
