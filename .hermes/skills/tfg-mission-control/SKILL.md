---
name: tfg-mission-control
description: Planifica y consulta misiones del TFG mediante MCP.
version: 1.1.1
author: Joel (TFG)
metadata:
  hermes:
    category: tfg
    tags: [missions, planning, sitl, mcp]
---

# TFG Mission Control Skill

Ayuda al estudiante a preparar y explicar misiones mediante el MCP del proyecto.
Hermes interpreta la intención y elige herramientas; el código determina seguridad
y control. Estas instrucciones no autentican el diálogo ni garantizan fidelidad.

## When to Use

Para crear, continuar, revisar o consultar una misión, geometría, propuesta,
revisión o ensayo del TFG. También para explicar un resultado histórico por ID.
Este skill de dominio es distinto de `hermes-agent`, que documenta el cliente.

## Prerequisites

El servidor `tfg-mission-control` debe estar configurado y sus herramientas disponibles.
Usa los nombres efectivos publicados en la sesión: el cliente puede añadirles
un prefijo MCP. Los nombres de esta guía son los nombres base del servidor.
La confianza del repositorio y la precarga del skill son decisiones del operador;
no edites su configuración, modelo, proveedor, permisos o herramientas globales.

## How to Run

Trabaja por intención y estado, sin número fijo de llamadas ni secuencia obligatoria.
Una consulta no necesita preparar otra misión. Una petición nueva no necesita
explorar código, carpetas, borradores antiguos ni recursos genéricos.

Si una herramienta no aparece, usa el catálogo/esquemas disponibles en ese cliente
o informa de que no puedes verificar su disponibilidad. No inventes una búsqueda
`get_prompt` ni un recurso que represente un run_id. Una consulta sin argumentos
válidos no demuestra que no existan borradores. No afirmes inexistencia basándote
en una búsqueda genérica que no consultó el proyecto.

## Quick Reference

| Intención / estado | Herramientas del proyecto pertinentes |
| --- | --- |
| Guardar hechos nuevos o completar el mismo borrador | `update_mission_draft` |
| Completar intención relativa; generar sólo con decisiones suficientes | `generate_draft_route` o actualización de `geometry_intent` |
| Construir, validar y exportar el borrador completo solicitado | `finalize_mission_draft` |
| Explicar borrador/finalización/revisión/ensayo por ID | `get_mission_state` |
| Consultar ensayo existente por run_id o request_key | `get_virtual_preflight` |
| Propuesta desde informe final; leerla; aceptar cambios explícitos | `propose_mission_revision`, `get_revision_proposal`, `build_mission_revision` |
| Validar/exportar un JSON que el operador ya proporciona | `validate_mission`, `validate_and_export_qgc` |
| Readiness actual si se solicita comprobar disponibilidad | `check_simulation_ready`, `check_mission_execution_ready` |
| Ensayo explícitamente autorizado del snapshot revisado | `start_virtual_preflight` y consulta del MISMO ensayo |

## Procedure

### Hechos y borradores

- Guarda lo conocido, conserva `draft_id`, `draft_revision` y parámetros parciales;
  pregunta las decisiones esenciales pendientes de misión y geometría.
- Nombre, parcela o rectángulo no implican agricultura, survey, altura, límites de
  seguridad, cierre ni regreso. No copies datos de otra misión salvo petición
  explícita, con fuente identificada y alcance de la copia explicado.
- Obtén enums y estructura del esquema registrado, sin leer código fuente para
  adivinar etiquetas. No cambies un valor explícito para hacerlo encajar: acláralo.
- Ausente/desconocido permanece pendiente. Los defaults de compatibilidad se
  identifican como defaults y se presentan antes de autorizar un ensayo; no son
  decisiones del operador. No inventes nuevos defaults para límites de seguridad.
- Una atribución del operador es una declaración del agente, no autenticación.
  Batería/viento declarados de un escenario simulado no son telemetría física.
  Atribuye sólo campos realmente resueltos y suministrados en esa actualización.
  `OPERATOR_DECLARED_VIA_AGENT` requiere un `statement` no vacío que respalde ese
  campo; no atribuyas inferencias ni decisiones pendientes. Si falta respaldo,
  conserva UNKNOWN/omite la atribución, en vez de inventar un statement.

### Geometría y referencias

- Persiste modo, dimensiones y parámetros explícitos en `geometry_intent`, no
  sólo en texto libre. No escribas a mano coordenadas que dupliquen el generador.
- HOME no basta: faltan, según el caso, orientación, sentido, posición de HOME
  respecto a la forma, altura/referencia, cierre y regreso. Lee las listas conjuntas
  `pending.route_generation` y `pending.mission_finalization`.
- La orientación de longitud se mide desde norte hacia este: norte 0°, este 90°,
  sur 180°, oeste 270°. Viento "desde norte" indica procedencia, no destino.
  Dirección de desplazamiento y orientación de una arista/eje son decisiones
  distintas: si no está resuelto qué elemento se orienta, guarda sólo los demás
  parámetros claros y pregunta antes de fijar orientation_deg o atribuirlo.
  Una referencia de altura explícita puede estar resuelta aunque el eje no lo esté.
- La geometría actual sólo admite `relative_to_home`, con HOME altitud relativa
  0; no es AMSL ni altura sobre el terreno. Si el operador da otra referencia,
  explica el límite y pregunta, sin convertirla ni sustituirla silenciosamente.
- Dimensiones anteriores sobreviven a parámetros parciales. Editar geometría de
  una ruta existente requiere revisión actual y reemplazo explícito; no concedas
  ese reemplazo por tu cuenta. Un CONFLICT requiere consultar, no forzar versión.

### Finalización, revisiones y consultas

- Guardar o validar lo ya solicitado no necesita otra confirmación. Finalizar y
  construir una revisión ya validan/exportan: explica su salida sin repetirlas.
  Decide por el resultado recibido: una operación que ya construyó/validó/exportó
  satisface esa solicitud aunque el usuario enumere esos verbos. No los traduzcas
  en llamadas adicionales; repite sólo por cambios o una petición nueva explícita.
- Conserva finalization_id, revision_id, proposal_id, hashes y rutas devueltas.
  Consulta por ID con summary; solicita detail si necesitas coordenadas, procedencia
  o eventos completos. No inventes IDs/rutas ni busques "el último archivo".
- Perder una respuesta no autoriza repetir una escritura. Consulta el ID/clave
  retenido; si no existe identificador verificable, reconcilia con el operador.
- Una propuesta no aplica cambios ni vuela. Construye una revisión nueva sólo con
  cambios aceptados/declarados, hash de propuesta revisado y clave recuperable.
  Una recomendación no añade un bloqueo técnico al gate. La nueva validación
  puede seguir BLOCKED; no prometas que una recomendación resolverá la viabilidad.
- `qgc_plan_path=null` describe esa operación; no prueba ausencia de exportaciones
  anteriores. Sólo relaciona artefactos mediante vínculos persistidos verificables.

### Ensayos y resultados

- Sólo una solicitud explícita del ensayo autoriza iniciar un preflight del snapshot
  revisado. Preparar, consultar, aprobar planificación o generar .plan no lo autoriza.
  Una petición SITL no requiere autorización de hardware real ni cambios físicos.
- El ensayo arma, despega y mueve sólo el vehículo lógico de la misión: `drone_01`
  corresponde a `v1` y `drone_02` a `v2`, exclusivamente simulados. No sustituyas IDs
  desconocidos ni copies otra misión para cambiar de dron sin solicitud. Hay una sola
  ejecución global: una reserva de cualquiera bloquea ambos; no prometas vuelos
  simultáneos ni separación. Selección implementada no equivale a vuelo operativo
  verificado: consulta evidencia específica del vehículo. El worker no arranca
  simulación. Si no está lista, explica BLOCKED; no la arranques para arreglarlo
  salvo una petición separada explícita del operador.
- Registra una request_key antes del inicio; conserva run_id y consulta el MISMO
  ensayo cada 15–30 s cuando proceda. Tras recarga, respuesta perdida o timeout,
  consulta por ID/clave; nunca reinicies para recuperar el resultado.
- ACCEPTED/STARTING/RUNNING no son PASSED. PASSED/FAILED/BLOCKED/ERROR son resultados
  del contenido concreto. INTERRUPTED/UNCONFIRMED no confirma aterrizaje: no liberes
  restricciones, no reanudes y no repitas el vuelo automáticamente.
- La readiness guardada es histórica, no disponibilidad actual. Nombra únicamente
  controles registrados: Docker container, Gazebo server, ArduPilot processes,
  ROS 2 vehicle interfaces y Pre-arm checks, sólo los que llegaron a ejecutarse.
- Diferencias started_at/finished_at del workflow y del executor son duración de
  esas operaciones, no tiempo en vuelo; sin tiempos de eventos adecuados, éste
  permanece desconocido. No uses una consulta histórica como chequeo actual.
- FAILED WP3 exige describir evidencia y recuperación disponibles, causa desconocida.
  Un PASSED posterior no demuestra su causa ni resolución. Un fallo de infraestructura
  tampoco demuestra un defecto de ruta. No rellenes causalidad a partir de coincidencias.

### Arranque con GUI y confirmación visual

- Tras un arranque solicitado con GUI, separa el resultado del arranque/readiness
  del backend de la imagen observada por el operador. Pregunta: «¿Gazebo muestra
  correctamente el mundo y los drones, aparece negro o no se abrió?». Hasta la
  respuesta, visualización no confirmada. READY, proceso GUI o «GUI: ON» no prueban
  renderizado, ventana abierta ni imagen útil; no inventes detección automática.
- Pantalla negra o ventana no abierta: reconoce la observación sin atribuir causa.
  Ofrece una recuperación mediante un único reinicio controlado, dejarlo pendiente
  o continuar expresamente sin visualización. No reinicies sin aceptación del
  operador ni interpretes su reporte de fallo como autorización. Continuar sin
  imagen no autoriza ensayo/vuelo ni sustituye readiness, gate o consentimiento.
- Antes de ejecutar la recuperación, consulta los ensayos conocidos por
  sus IDs/claves con las herramientas del proyecto: revisa estado/worker y
  `vehicle_restriction`/`global_flight_restriction`. No detengas ni arranques si hay
  ejecución activa (incluido worker aún activo), reserva de cualquiera de los
  vehículos o resultado no confirmado,
  incluso con FINISHED/PASSED. Si faltan IDs, hay ERROR/NOT_FOUND, respuesta perdida
  o no puedes establecer ausencia de actividad/reserva global, mantén la recuperación
  pendiente y explica qué falta. No inventes IDs ni reconstruyas estado por directorios.
  Una consulta histórica no es inventario ni prueba de ausencia de otras ejecuciones.
- Con aceptación de ese único reinicio y estado verificado libre, revalida justo
  antes de actuar y realiza una sola secuencia: stop, esperar resultado de parada
  confirmada, start, esperar resultado, comprobar readiness y volver a preguntar
  por la imagen. No encadenes llamadas en paralelo ni avances tras fallo/timeout
  o resultado de parada incierto; no repitas operaciones por respuesta perdida.
  Si sigue negro/no abierto, no hagas otro ciclo automático: presenta lo observado
  y vuelve a las opciones del operador, sin extender el consentimiento anterior.
- `start_simulation` también limpia procesos anteriores: repetir start cuenta como
  recuperación/reinicio, no como consulta de GUI. Nunca lo uses para eludir la
  comprobación de reservas o la aceptación. Este paso es conversacional; las
  consultas no reservan atómicamente el ciclo de vida frente a un nuevo vuelo.
  Si no puede asegurarse el intervalo sin actividad, no reinicies por la GUI.
  Conserva elección, aceptación, intentos y resultados en el contexto con sus
  fuentes; no inventes campos visuales en MissionDefinition o informes del backend.

## Pitfalls

Sólo `navigate` está ejecutado; no prometas survey, inspect, take_photo ni acciones
agrícolas. `speed_kmh` no demuestra seguimiento de velocidad. Regreso por navegación
y LAND no es modo RTL. Exportar .plan no demuestra que ArduPilot lo cargó.
PASSED no autoriza hardware ni otra ejecución. Hash identifica bytes locales,
no firma evidencias ni resuelve todo TOCTOU. No edites evidencias históricas.

## Verification

Expón datos persistidos, incertidumbres y siguiente decisión del operador. Una
respuesta breve debe conservar errores, motivos, consentimiento, alcance y vínculos.
La evaluación conversacional se hace con transcripción y argumentos/resultados
estructurados; un resumen solo deja evidencia insuficiente sobre escrituras.
Este skill no permite afirmar por sí mismo que Hermes cumple estas reglas.
