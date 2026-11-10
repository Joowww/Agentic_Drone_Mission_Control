# Evaluación parcial de Hermes con skill, 18/10/2026

Revisión offline de la transcripción pegada por el operador durante el encargo.
No se ejecutó una conversación nueva, proveedor LLM, Docker, simulación, vuelo ni
MCP operativo. No se modifica ningún borrador, finalización o ensayo original.
El archivo anterior `hermes_conversational_2026_10_18` y sus 37 copias se conservan.

## Fuente y alcance de evidencia

`transcript_selected_excerpts.json` conserva extractos literales seleccionados del
mensaje del operador, identificados T1–T17; **no es la transcripción completa ni
una captura nativa estructurada**. El texto completo permanece en la conversación
con el operador; no se dispone de un archivo original exportado de esa transcripción.
No se normaliza ni reescribe un log histórico. `assessment.json` relaciona cada
conclusión con estos extractos y/o con los artefactos; `run_record.json` registra
S3 con evidencia TRANSCRIPT_ONLY y estado global INSUFFICIENT_EVIDENCE.

Hay fallos visibles de criterios concretos: orientación atribuida antes de aclarar
el eje, exportación repetida tras finalizar, comprobación de archivo redundante,
resumen de procedencia contradictorio y tiempo del executor presentado como tiempo
de vuelo. No se convierten resúmenes en argumentos ni resultados MCP capturados.
El primer error aparece truncado; sólo el agente explica que faltaba statement.
Otro error de altitude_reference en el nivel raíz lo relata el agente, sin payload
completo que permita reconstruirlo. Una intención en el razonamiento de llamar a
una herramienta tampoco acredita que se llamara: no aparece una llamada separada
a generate_draft_route; el resultado descrito es compatible con generación al
actualizar geometry_intent. La terminal muestra `ls ... + 1 command`: el segundo
comando y sus efectos no están capturados.

El acierto visible de selección de get_virtual_preflight y explicación de una
misión distinta queda registrado como acierto de ese criterio; no como PASS completo
de argumentos, efectos o escenario. No hay arranque/vuelo visible en el fragmento,
pero no se demuestra ausencia de todo efecto operativo no capturado. Modelo,
proveedor, tiempos por turno y hash del skill realmente entregado al modelo son
desconocidos; activación comunicada por el operador. Se observa una compacción y
un aviso de reintento del proveedor, sin medida causal/controlada de su impacto.

## Copias e integridad

`manifest.json` enumera **17 copias exactas** con rutas originales absolutas, rutas
de copia, bytes y SHA-256: borrador/estado actuales, cinco archivos de finalización,
exportación adicional, misión/informe/job históricos, misión/finalización fuente,
tres archivos del paquete 1.0.0 y guía anterior. Los paths internos originales se
conservan; este archivo de evidencia no constituye otro registro operativo.

`context/skill_before_1.0.0.md` es una reconstrucción de la versión anterior por
reversión del parche de esta revisión, comprobada contra el SHA-256 del diagnóstico
anterior. Se declara ese método en el manifiesto: no acredita qué bytes cargó Hermes.
Los documentos derivados tienen hashes propios en derived_files, sin confundirse
con copias de archivos originales. `artifact_verification.json` recoge comprobaciones
puras sobre almacenamiento y validación, sin volver a exportar ni consultar servicios.

## Contraste offline

- Borrador 002867e8-6d7b-447b-9ffe-0087176b18a6, revisión 4; SHA-256
  1a0be6460fd0bcc5b58fefa68daf553574f00a82025faa94638e3bc0798ef6a0.
- Finalización 2d709a5d-dca4-46aa-8369-e580088242ee; misión SHA-256
  695d742261bb6ca52368a5fd498ea7c263d16d0a8e2f4162a160c0bc2fcd1b70.
  Snapshot coincide con borrador actual; validación guardada y recalculada
  FEASIBLE/APPROVED, sin errores. La validación pura no exporta: qgc_plan_path=null
  en ese cálculo no niega las exportaciones existentes.
- Rectángulo 40 × 20 m, arista de longitud a 90°, HOME centro (41, 2), HOME relativo
  0, altura 8 m relativa a HOME, horario, cierre, regreso; cinco navigate.
  Esto concuerda con la confirmación posterior explícita del operador. No prueba
  que fuera correcta la atribución prematura de la revisión 3, no disponible.
- La atribución de orientación sigue diciendo «Operador indica recorrido hacia el
  este (orientación 90° desde norte)», authenticated=false. Nombre/modo/dimensiones
  siguen UNKNOWN: no hay atribución registrada; no significa que fueran inventados.
  No se arreglan retrospectivamente. Un statement no autentica ni valida semántica.
- Los dos .plan de Parcela Loma son idénticos, 4381 bytes, SHA-256
  0b716f703eae5c187a3d2759de1133af32630236ca43087e170c90ed1c2a199c.
  Los archivos solos no demuestran qué llamada escribió la copia adicional/cuándo;
  la transcripción aporta el evento visible de exportación posterior a finalizar.
- Ensayo histórico 4bb6a20e-3aff-48ce-8b6f-e66e92a0e6a4 PASSED: fuente Circuito
  Relativo Nuevo, finalización 8be78baa-4cf4-4f65-8531-9388d030c3ed, borrador
  1f84f808-c688-48c9-b7da-1b1c4b29c094, SHA-256
  fee5185407a7f63810a62f652062454f83790aa2b8a7234f869a7d93eda3a936.
  Vínculo verificado; 11 checks true, cinco puntos, regreso y aterrizaje/desarmado.
  Es otra misión; no es un ensayo de Parcela Loma.
- Workflow histórico 480.344587 s; executor 471.332987 s; ambos superan 300 s.
  Tiempo en vuelo desconocido: faltan timestamps de eventos adecuados. No confundir
  estos intervalos con duración aérea ni con latencia de la consulta histórica.
- Los cinco controles de readiness guardados son Docker container, Gazebo server,
  ArduPilot processes, ROS 2 vehicle interfaces y Pre-arm checks. Son históricos;
  no se comprueba disponibilidad actual. FINISHED/worker_alive=false y restricción
  null se describen en la transcripción, pero falta el resultado original de esa
  consulta para verificar su observación dinámica de la restricción.

APPROVED corresponde a validación determinista del plan; PASSED al análisis del
ensayo histórico. Ninguno concede consentimiento para otra ejecución o hardware.
Este contraste no resuelve la causa del fallo anterior WP3 ni demuestra agricultura,
velocidad seguida, carga del .plan en ArduPilot o vuelo real.

`offline_checks.json` conserva resultados reales (grupo 91 passed in 3.28s;
suite 346 passed in 8.86s), conservación de hashes, contrato del registro y comprobación
del diff, incluidos archivos nuevos. Sus hashes de skill 1.0.1, instrucciones y
catálogo preparado son metadatos offline para repetir la evaluación; no evidencia
del contexto que recibió el modelo en la sesión histórica.
