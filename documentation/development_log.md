# Development log

Registro de avances, pruebas, incidencias, decisiones y próximos pasos.
Los resultados deben estar respaldados por código, tests o evidencias.

## 2026-10-17 — Planificación conversacional mediante Hermes y MCP

### Objetivo y punto de partida

Conectar la conversación de Hermes con la creación de misiones,
la validación determinista, la exportación QGC y la ejecución simulada.

- Rama: feature/hermes-integration.
- Commit inicial: fcb13a1.
- Estado inicial limpio y sincronizado.
- Ya funcionaba la ejecución de un dron con tres waypoints.
- El servidor MCP recibía mission_path y ejecutaba únicamente v1.

### Implementación

- update_mission_draft crea, recupera y completa borradores persistentes.
- draft_id permite continuar la misión entre turnos y reinicios.
- finalize_mission_draft construye MissionDefinition, guarda un JSON
  y reutiliza la validación y exportación QGC.
- Cada finalización utiliza un directorio UUID independiente.
- Hermes interpreta el lenguaje natural y selecciona herramientas.
- Esta integración reutiliza los modelos y servicios de planificación
  sin invocar un segundo LLM de Ollama.
- Se corrigió un parámetro de validate_and_export_qgc.
- Se añadieron tests y docs/hermes-planning.md.
- La entrada JSON continúa disponible.

### Verificación automatizada

- Compilación de los tres módulos modificados/nuevos: correcta.
- Suite ejecutada por Joel: 65 passed in 7.38s.
- git diff --check: sin errores.

### Caso aprobado

- Nombre: Prueba Hermes.
- Mission ID: prueba_hermes_001.
- Draft ID: ca4ab5d2-24e1-4845-8142-b214740e7f9d.
- Finalización: a709aaba-d25b-451c-a6f0-e2ff6ace018f.
- Vehículo: drone_01, ejecutado como v1.
- Batería declarada: 95 %; consumo configurado: 0.8 %/min.
- Reserva mínima: 20 %; viento configurado: 0 km/h.
- Tres waypoints navigate a 5 m, con regreso al lanzamiento.
- El operador proporcionó coordenadas y parámetros en lenguaje natural.
- Hermes creó el borrador, solicitó datos, lo completó y lo finalizó.
- Validación: FEASIBLE y APPROVED, sin errores.
- Se generaron JSON y QGC .plan.

### Ejecución simulada

Tras la autorización explícita del usuario, Hermes seleccionó
execute_approved_mission. El executor aplica internamente el execution gate.

- Resultado: COMPLETED.
- Waypoints completados: 3/3.
- Regreso y aterrizaje completados.
- Estado final: landed=true, armed=false, flying=false.
- Duración de la llamada MCP: 228.7 s.
  No constituye una medición independiente del tiempo de vuelo.

| Evento | Error horizontal (m) | Error vertical (m) |
|---|---:|---:|
| WP1 | 0.02740448 | 0.00000000 |
| WP2 | 0.22777375 | 0.04003906 |
| WP3 | 0.22611909 | 0.01000977 |
| Regreso | 0.00000000 | 0.00000000 |

Error vertical al aceptar el despegue: 0.65002441 m.
Son valores reportados por el executor; cero no implica precisión física absoluta.

### Caso bloqueado por batería

- Nombre: Prueba Hermes bateria insuficiente.
- Draft ID: d25acd5a-fd61-453c-a3ad-ea236c5c1f6b.
- Mission ID: prueba_hermes_001_bateria_baja.
- Misma ruta; batería inicial 10 % y reserva mínima 20 %.
- Resultado: NOT FEASIBLE y BLOCKED.
- Motivo: batería final prevista inferior a la reserva.
- Recomendación: iniciar con al menos 20.1 %, según el modelo actual.
- No se llamó a herramientas de arranque, parada ni ejecución de vuelo.

Hermes creó un borrador independiente y leyó posteriormente el JSON original.
No se realizó una comparación independiente de hashes de todos los originales.

### Evidencias conservadas

Directorio relativo a la raíz del repositorio:

simulation/ros2_gazebo/results/hermes_conversational_2026_10_17/

- approved_mission.json
- approved_mission.plan
- blocked_battery_mission.json
- blocked_battery_candidate.plan

Las cuatro copias se comprobaron mediante ls y tienen contenido.
El candidato bloqueado procede de la segunda exportación solicitada por Hermes.

Los originales permanecen en missions/generated/, ignorado por Git.
Las transcripciones se revisaron durante la sesión; no están incluidas
en estas cuatro evidencias. Este registro conserva los resultados principales.

### Incidencias y mejoras

- Readiness comprueba el backend, no la visibilidad de la GUI.
- Inicialmente solo estaba activo el servidor de Gazebo.
- Abrir la GUI por separado produjo una pantalla negra.
- Se realizó parada y arranque completos mediante MCP.
- El arranque posterior informó GUI activada y backend preparado.
- La causa exacta de la pantalla negra no quedó aislada.
- Hermes exploró archivos y recursos para entender operaciones habituales.
  Mejorar las descripciones MCP, incluido el comportamiento de la GUI.
- Hermes repitió validación/exportación después de finalize_mission_draft.
  Aclarar que la finalización ya realiza ambas operaciones.
- Algunas respuestas resumieron resultados en vez de mostrar el JSON pedido.
- cp -n emitió un aviso de portabilidad. Las copias existen.
  Para próximas copias se utilizará cp --update=none.

### Límites de la demostración

- La ruta fue aportada por el operador; no se generó desde un objetivo agrícola.
- Solo se ejecutó navigate; no se verificó seguimiento de speed_kmh.
- El executor consumió el JSON mediante ROS2/AP_DDS, no cargó el .plan.
- El regreso navega al lanzamiento y aterriza; no activa el modo RTL.
- La etiqueta candidate no impide cargar el archivo en otra aplicación.
- La autorización es conversacional, sin token ligado a una versión.
- No hay preflight formal con análisis y replanning.
- No se demostró replanning durante el vuelo ni coordinación de dos drones.
- No se probaron acciones agrícolas ni hardware real.
- Faltan eliminación de campos/waypoints y control de concurrencia.

### Próximos pasos

1. Guardar este incremento y sus evidencias en Git.
2. Mejorar instrucciones y descripciones MCP a partir de las incidencias.
3. Definir el primer workflow de preflight, análisis y replanning con estado.
4. Mantener trazabilidad entre misión validada, simulada y autorizada.
5. Incorporar evaluación y documentación durante cada incremento.