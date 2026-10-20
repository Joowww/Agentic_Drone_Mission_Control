# Demo del 19/10: material inicial de observabilidad

Verificación offline. No conversación nueva con LLM, MCP operativo, Docker ni vuelo.

## Qué se conserva y qué falta

El TXT anunciado `Texto pegado(20261019-153307).txt` **no estaba disponible** en
los adjuntos accesibles. El operador pegó después el texto como respuesta en este
chat. `operator_pasted_reply.txt` conserva exactamente ese string Unicode codificado
en UTF-8, incluida su introducción «es este el texto pegado perdon» y espacios;
se extrajo únicamente la respuesta de usuario del registro local de la sesión.
No se archivó la sesión completa ni se reconstruyó el comienzo de Hermes.

Son **74834 bytes**, SHA-256
`7e361bcc9074274650f0e45ad9d9accd7a3b9cb98fadb4dc91ece1acf81af0eb`.
Este hash identifica el texto recibido aquí; no demuestra igualdad de bytes con
el TXT original no disponible, ni autenticidad de la conversación. Bytes y longitud
de texto no son tokens facturados. El indicador de contexto/modelo de la UI tampoco
es una métrica de facturación ni una configuración de proveedor verificada.

El manifiesto relaciona otras siete copias exactas con originales locales:
borrador/estado `7f2e3345-a62e-4060-a0c0-9b034714b49e`, finalización
`17764ef0-5114-4447-87d5-de6f00455bf3`, misión, fuentes y `.plan`. Los originales
permanecen intactos. `artifact_verification.json` es análisis derivado separado.

## Hechos persistidos verificados

- Revisión 4, misión `demo_reunion_001`, drone_02, multirrotor ArduPilot.
- Rectángulo 40×20 m en el modelo local, eje largo 90° desde norte, horario,
  HOME central 41/2/0 relativo, cinco puntos `navigate` a 8 m, cierre y regreso.
- Velocidad declarada 36 km/h, batería 100%, consumo 1,5%/min, viento 10 km/h
  desde 0°, reserva 20%, viento máximo 15 km/h, altura máxima 120 m.
- Objetivo `custom`, target `demonstracion_rectangular`.
- FEASIBLE/APPROVED, `.plan` existente y hash coincidente;
  consentimiento de vuelo NOT_GRANTED.
- SHA-256 misión `e48467db54874ea36e68652ae2cbf8460cba2c08865060e8d3326cbd1c38ea42`.
- SHA-256 plan `4b52c02f91cae25ff30963fe772241b76f1bce5f2ff1d2d543c7a465eed3f5c5`.
- Comandos QGC `[22,16,16,16,16,16,20]`: takeoff, cinco navegación y retorno.
  El 20 es RETURN_TO_LAUNCH, no NAV_LAND (21); exportación no demuestra carga/ejecución.

## Observaciones de la transcripción parcial

Se ve un fragmento sobre errores JSON y repetición de razonamiento; faltan los
payloads completos de las llamadas fallidas. La explicación del agente acerca de
Unicode/nesting/string vs objeto no identifica una causa demostrada. También se ve
un clarify rechazado por superar cinco ítems y otro aceptado con respuestas sobre
orientación, horario, centro, cierre y ArduPilot. Aparece la etiqueta confusa
«Nordeste 0° (norte)». Se observan respuestas del operador sobre velocidad/batería,
viento y límites sugeridos como «estándar», sin fundamento acreditado para ese estándar.

No hay confirmación visible suficiente de consumo 1,5%/min, viento procedente de
norte u objetivo `custom/demonstracion_rectangular`, que sí están persistidos.
Como el texto empieza a mitad de interacción y faltan argumentos/resultados MCP
estructurados, no puede afirmarse que nunca fueran aportados antes, ni reconstruir
todas las escrituras a partir del razonamiento del agente.

Se ve finalización y después lectura fallida de una ruta con `4477` en lugar de
`4447`, una afirmación incorrecta de que todavía no había exportación, exploración
de directorios y rectificación del UUID. Los archivos contradicen la ausencia de
exportación. No aparece otra llamada de exportación en el tramo suministrado; esto
no demuestra ausencia global de llamadas no capturadas.

El resumen final mezcla «5 + LAND» y «comando 20 NAV_LAND / RETURN_TO_HOME».
Las coordenadas finales citadas coinciden con la misión, pero esa terminología no
describe correctamente el plan ni acredita un vuelo. La finalización guardada no
autoriza ensayo. No hay PASS global de fidelidad conversacional ni mejora estadística.

Estas incidencias se registran para futura observabilidad con argumentos/resultados,
timestamps y configuración no sensible. No se integra LangSmith/Opik ni se abre una
refactorización del comportamiento de Hermes en este incremento.
