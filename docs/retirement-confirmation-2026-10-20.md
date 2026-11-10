# Barrera de confirmación del retiro legacy — 20/10/2026

La [auditoría](auditoria-retiro-c6eeb645-2026-10-20.md) contrasta los archivos con
el relato del operador: autorizó `a55dcde0…/0d93dde4…`, el intento caducó y el
backend recibió después una declaración con `88f0dfab…/8957c36b…`. La segunda
pareja y el retiro están persistidos; el nuevo consentimiento humano no está
demostrado. El defecto no fue de hash del snapshot: el servidor admitió texto del
agente como si renovase una autorización específica. No se alteran los originales,
la nota de auditoría ni el resultado ADMINISTRATIVELY_RETIRED_UNVERIFIED.

## Qué se inspeccionó y qué puede afirmarse

Sólo código local; sin conexión MCP, proveedor LLM ni prueba de UI/configuración
en vivo. No se leen credenciales ni se modifica configuración personal.

| Pieza local | Evidencia del código | Límite |
| --- | --- | --- |
| `tools/hermes_mcp_server.py` del proyecto | El wrapper pasaba autorización/IDs como argumentos ordinarios del agente al backend; no tenía intercambio independiente de confirmación | `source=OPERATOR_ADMINISTRATIVE_DECISION` no autentica al operador |
| `~/.hermes/hermes-agent/tools/mcp_tool_transport.py`, `_session_kwargs` | Puede instalar callbacks de elicitation en ClientSession | No demuestra las capacidades ni el comportamiento de una conexión activa |
| `~/.hermes/hermes-agent/tools/mcp_tool_sampling.py`, `ElicitationHandler` | Form-mode llama request_elicitation_consent; timeout/error declina/cancela. La aceptación lleva content vacío; URL-mode se rechaza | No transporta al proyecto un recibo de identidad humana/ID/hash; no se probó la UI |
| `~/.hermes/hermes-agent/tools/approval_prompt.py`, `request_elicitation_consent` | Ruta CLI/TUI a prompt y gateway a resolución de aprobación; no un argumento ordinario extraído del diálogo por el modelo | La autenticidad del callback, quién resolvió la aprobación y configuración efectiva no se acreditan al servidor |
| `.venv/lib/python3.12/site-packages/mcp/server/mcpserver/context.py`, `Context.elicit` | Ofrece elicitation por protocolo | Su documentación advierte que un cliente agente puede preguntar al usuario **o generar automáticamente la respuesta** |

Por tanto hay un mecanismo de interacción candidato fuera del texto del modelo,
pero **no una confirmación humana verificable integrada en este proyecto**. No se
confunde ausencia de integración con ausencia universal de elicitation en Hermes.
Tampoco se presupone que todos los clientes MCP tengan el mismo comportamiento.
Un accept por protocolo sin contrato de confianza revisado no habilita el retiro.

## Contrato efectivo

1. La declaración exige su propio preparation_id y preparation_sha256; el backend
   los compara con la pareja exterior, además de comprobar el hash del archivo.
   Otro ID/hash produce CONFIRMATION_BINDING_MISMATCH. Copiar o reescribir ambos
   campos sólo consigue una declaración bien formada, nunca confirma a una persona.
2. Preparación caducada/otro boot produce PREPARATION_EXPIRED_OR_BOOT_CHANGED.
   No llama prepare ni sustituye scope. Un error tampoco renueva permisos.
3. `_require_operator_confirmation` siempre rechaza en producción con
   OPERATOR_CONFIRMATION_UNAVAILABLE. No hay flag, variable de entorno, token
   inventado, fallback de elicitation ni configuración que active el bypass.
   Está antes de cualquier observación operativa, mutex o escritura de aplicación.
4. Recarga/reconexión y respuesta perdida no guardan una confirmación en memoria
   ni la reconstruyen desde intent/statement. Consultar no confirma ni reanuda.
   Los intentos bloqueados por esta barrera no crean archivos de runtime.
5. Un resultado ya completado se devuelve sólo como historia, sin aplicación,
   revalidación de Docker ni retirada. Los registros legacy se leen sin migrar.
   Consulta expone operator_confirmation_verified=false y application_enabled=false;
   authorization_recorded sólo significa declaración persistida, no consentimiento
   autenticado. Una transacción parcial sigue protegida y no puede recuperarse.

La firma MCP de apply conserva su nombre y parámetros exteriores; el modelo anidado
añade dos campos obligatorios. Las antiguas llamadas de aplicación sin esos campos
se rechazan por esquema; para leer historia se usa get, sin reescribir los artefactos
ni hacer migración. Un replay Python de un resultado final sólo puede leerlo.

## Pruebas y alcance

`tests/test_retirement_confirmation.py` prueba la barrera de producción con
directorios temporales y herramientas realmente registradas: pareja exacta fresca
sin canal humano sigue bloqueada; otra pareja, caducidad, declaración reescrita,
timeout/error, respuesta perdida, recarga, consultas y estado legacy ya retirado.
No usa frases del prompt como prueba de seguridad.

Las regresiones de persistencia en `test_legacy_administrative_retirement.py`
conservan sus verificaciones de archivo, fsync, barreras y carreras. Para ejercitar
ese motor ahora usan un **doble explícito del verificador sólo en tests**. Un éxito
con ese doble no afirma que exista una ruta de aprobación operativa ni una persona
autenticada. La regresión de caducidad/recarga ahora exige bloqueo y barrera intacta,
en lugar de continuar una transacción caducada.

Este bloqueo protege las entradas actualizadas del proyecto. No es una frontera
contra un proceso que pueda editar código/archivos o suplantar un cliente con las
mismas credenciales del sistema. No se implementa un firmante externo ni se afirma
seguridad universal del consentimiento MCP. Una futura integración necesitará
definir confianza del cliente, origen de la respuesta y vínculo único a scope y
sesión, verificar caducidad tras preguntar, consumir/revocar la confirmación y
fallar cerrada sin reintentos. No se habilita provisionalmente un terminal o receipt
que el mismo agente pueda fabricar. La aplicación queda bloqueada hasta resolverlo.
