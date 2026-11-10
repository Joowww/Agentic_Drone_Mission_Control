# Protocolo de rendimiento: dos drones y futura incorporación de rover

Fecha: 20/10/2026. **PROPUESTO — NO AUTORIZADO — NO EJECUTADO.**

Este documento prepara una campaña futura; no concede permiso para arrancar,
detener, reiniciar, consultar servicios ni controlar vehículos. No contiene resultados
nuevos. La campaña propuesta mide infraestructura en reposo: vehículos sin armar,
sin desplazamientos, misiones, preflight ni vuelos. No evalúa coordinación,
separación, agricultura ni rendimiento durante una misión.

## 1. Datos históricos y alcance de la comparación

Fuente: [registro histórico de rendimiento](../simulation/ros2_gazebo/results/performance_tests.md).
Se conserva sin modificar; sus valores no son mediciones repetidas con este protocolo.

| Configuración histórica | Valores disponibles | Información ausente en ese registro |
| --- | --- | --- |
| Dos drones + rover; GUI ON; RViz OFF | CPU 448,26 %; RAM 3,05 GiB de 15,5 GiB; PIDs 349; RTF aproximado 0,03–0,04 | Series brutas, warm-up, ventana, frecuencia, repeticiones, dispersión y método exacto de RTF |
| Dos drones; GUI ON; RViz OFF | Test B marcado TBD/Pending | CPU, RAM y RTF sistemáticos |
| Dos drones o dos drones + rover; headless | Sin resultados en la tabla | Mediciones comparables de todas las métricas |

El PASS histórico es funcional; el propio registro considera insuficiente la
fluidez. CPU 448,26 % no equivale a 448,26 % de capacidad total del equipo: falta
fijar la convención y los recursos disponibles antes de normalizarlo. PIDs no
equivale necesariamente a número de procesos, pues puede incluir hilos/tareas.
La apertura GUI correcta posterior no sustituye una campaña de rendimiento.

## 2. Estado de integración y dependencias de seguridad

La entrada activa usa [tfg_demo_2drones.launch.py](../simulation/ros2_gazebo/launch/tfg_demo_2drones.launch.py):
drone1 y drone2. El [supervisor](../simulation/ros2_gazebo/scripts/sim_processes.py)
selecciona ese launch; el [backend](../simulation/ros2_gazebo/scripts/start_sim_backend.sh)
copia esa versión y espera los puertos de los dos SITL. GUI/headless ya se transmite
desde [lifecycle](../tools/simulation_lifecycle.py); no hace falta reimplementarlo.

Existe el launch histórico [tfg_demo.launch.py](../simulation/ros2_gazebo/launch/tfg_demo.launch.py)
con drone1, drone2 y rover1, pero su existencia no habilita el rover en el control
actual. El [readiness actual](../simulation/ros2_gazebo/scripts/check_sim.sh)
comprueba dos ArduCopter e interfaces/prearm v1 y v2; no acredita readiness del rover.
El perfil `two_drones` de [simulation_profiles.py](../tools/simulation_profiles.py)
ya se consume en lifecycle, arranque y readiness; conserva el launch de dos drones.
No integra un perfil de rover. Sus pruebas usan dobles y no son evidencia operativa;
véanse [alcance y regresión pendiente](simulation-profiles.md).

Antes de autorizar B1/B2 se requiere otro incremento revisado que permita seleccionar
el perfil por la entrada protegida, con readiness específico del rover y revisión
de procesos, limpieza, puertos, interfaces, exclusión y reconciliación para esa
topología. No asumir soporte de ejecución v3 a partir del launch histórico.
Comparar ambos launches y sus dependencias instaladas: la diferencia experimental
debe ser el rover y sus componentes necesarios, sin cambios inadvertidos en los drones.

Reglas comunes para cualquier futura corrida:

- Revisar identidad actual del entorno y reservas; una ejecución activa, estado
  UNCONFIRMED/APPLYING, propietario ambiguo o identidad dudosa bloquea el lifecycle.
- Arranque y parada sólo mediante controles protegidos del proyecto. No recurrir
  a launch directo, Docker, señales o borrado de guard para eludir un bloqueo.
- No reanudar secuencias históricas ni usar este documento como consentimiento.
  Toda recuperación de una corrida incierta necesita su procedimiento separado.
- Separar readiness del backend de la confirmación visual del operador.
  Véanse [límites de lifecycle/reconciliación](reconciliation-and-lifecycle.md)
  y [diagnóstico de GUI negra](gazebo-black-gui-diagnostic.md).

## 3. Matriz y parámetros propuestos

**Recomendaciones pendientes de acuerdo, no valores medidos ni requisitos vigentes.**

| Caso | Vehículos | GUI | RViz | Repeticiones propuestas |
| --- | --- | --- | --- | ---: |
| A1 | Dos drones | ON | OFF | 3 |
| A2 | Dos drones | Headless | OFF | 3 |
| B1 | Dos drones + rover | ON | OFF | 3 |
| B2 | Dos drones + rover | Headless | OFF | 3 |

Total: 12 corridas, todas sin armar ni mover vehículos. Tres bloques con una corrida
de cada caso por bloque; aleatorizar y registrar orden y semilla. Tres repeticiones
permiten una primera comparación, no conclusiones estadísticas fuertes.

| Fase | Parámetro propuesto |
| --- | --- |
| Arranque | Registrar intervalo completo y resultado; separado de la ventana de medición |
| Readiness inicial | Guardar controles reales, salida, tiempos y retorno; incluye servicios prearm, no es lectura pasiva de logs |
| Warm-up | 120 s de pared desde readiness satisfactorio; recoger datos, pero excluirlos del resumen principal |
| Medición | 600 s de pared después del warm-up, sin interacción o cambios de configuración |
| Readiness final | Fuera de la ventana; registrar degradación o fallo aunque el inicial pasara |
| Cierre | Parada protegida y confirmación de limpieza antes del siguiente caso; conservar cualquier resultado incierto |

No aumentar timeouts de seguridad ni reintentar automáticamente para completar la
matriz. Una corrida fallida permanece registrada; repetirla requiere una decisión
explícita y otro run_id, sin ocultarla en los agregados.

Mantener constantes imagen y versiones, mundo, modelos de drones, sensores/cámaras,
bridges, parámetros físicos, speedup y límites CPU/RAM de WSL/Docker. Registrar carga
externa y política de cachés/reinicio; no llamar «frío» a un arranque sin definirlo.
Mantener alimentación y condiciones de carga del equipo comparables. Antes de la
campaña, decidir un intervalo fijo entre corridas y qué variaciones externas invalidan
la comparación. No introducir optimizaciones entre casos.

En GUI, fijar cámara, tamaño de ventana y estado visible, sin manipularla durante
la medición; guardar confirmación de escena al principio y final. Si aparece negra,
conservarla como incidencia: no tratarla como GUI correcta ni reiniciar para ocultarla.
Headless elimina la ventana, pero sensores pueden seguir necesitando renderizado;
no desactivar cámaras sólo en ese caso.

## 4. Métricas y captura propuestas

| Métrica | Frecuencia objetivo | Datos y resumen |
| --- | --- | --- |
| CPU contenedor | 1 Hz | Serie bruta, convención, CPU disponibles/cuota; media, mediana y p95; porcentaje normalizado por capacidad asignada |
| RAM contenedor | 1 Hz | Uso/límite y definición de caché incluida/excluida; mediana, p95, máximo y tendencia |
| PIDs/hilos y procesos reales | Cada 5 s | Contadores separados e inventario de procesos identificados por PID/start/boot cuando esté disponible |
| CPU/RAM por componente | Cada 5 s | Servidor, GUI, cada SITL, bridges y agente DDS; declarar métrica RSS/PSS y no sumar RSS como memoria física exclusiva |
| RTF | Objetivo 1 Hz | Factor informado por Gazebo, contadores sim/real y pausas/saltos/muestras ausentes; mediana, percentil bajo y distribución |
| Readiness | Antes/después de ventana | Resultado, controles por perfil, errores y duración |
| Visualización | Antes/después en GUI | Respuesta literal, hora y captura si se autoriza; headless: no aplicable |

Instrumentación pendiente de verificar: usar lectores persistentes y acotados
cuando sea posible, evitando lanzar procesos de consulta cada segundo. Aplicar el
mismo instrumental en los cuatro casos y registrar su sobrecarga. Identificar el
mundo/stream correcto de estadísticas antes de calcular RTF; si no está disponible,
registrar dato ausente, no reemplazarlo por una estimación no declarada.

Conservar el RTF informado por el simulador separado del cociente de incremento de
tiempo simulado respecto a pared monotónica del observador. Declarar denominador,
intervalo y fuente. Los timestamps ROS no se restan del reloj del PC para inferir
edad absoluta de mensajes. Registrar tiempo de pared y simulado por separado;
los intervalos de arranque, readiness y medición no son tiempo en vuelo.

Guardar cada futura corrida en una carpeta nueva `run_id/caso/repeticion`, sin
sobrescribir logs ni evidencias anteriores. Estructura sugerida, aún no creada:

- `metadata.json`: caso, bloque/orden/semilla, HEAD y estado del árbol, hashes de
  launches/mundo/modelos/configuración; imagen, contexto/endpoint, motor/contenedor,
  versiones, recursos asignados, carga externa, modo GUI y parámetros efectivos.
- `phases.json`: inicio/fin UTC y duraciones monotónicas; política de warm-up,
  cachés, separación entre corridas y desviaciones del protocolo.
- `samples/`: series brutas con unidad, fuente, timestamps de origen/recepción,
  errores, huecos y frecuencia efectiva; no interpolar silenciosamente datos ausentes.
- `logs/`: lifecycle, servidor, GUI/OGRE, readiness y colectores separados, con
  comando/retorno/timeout y fechas de copia. Archivar antes de otra apertura: algunos
  logs gráficos se reutilizan. El hash identifica bytes capturados, no una captura
  atómica de todos los logs vivos.
- `visual/` y `summary.json`: declaración/captura autorizada, estado de la corrida,
  agregados y método reproducible de cálculo. Diferenciar omisión de fallo.
- `manifest.json`: rutas, tamaños y SHA-256 de copias/metadatos, con exclusión del
  propio manifiesto declarada. No recopilar credenciales ni todo el entorno personal.

## 5. Criterios provisionales para revisar antes de ejecutar

Son criterios experimentales propuestos, no límites de vuelo ni resultados obtenidos.
No modificar gates, tolerancias o timeouts para alcanzar estos objetivos.

| Señal | Interpretación propuesta |
| --- | --- |
| Crash, readiness fallido, reset de reloj o perfil/configuración discordante | Excluir de comparación nominal; conservar y contar como fallo experimental |
| Más del 5 % de muestras esperadas ausentes en una métrica esencial | Corrida insuficiente para ese agregado; investigar instrumental, no rellenar sin advertencia |
| RTF mediano ≥0,8 | Objetivo provisional de interacción; no garantiza seguridad o respuesta de control |
| RTF mediano <0,5 / <0,1 | Degradación importante / fluidez claramente insuficiente para demo interactiva, respectivamente |
| Caída repetida de RTF >20 % al añadir rover, frente a dos drones en el mismo modo GUI | Investigar coste añadido usando repeticiones por bloque, sin atribuir causalidad a una sola muestra |
| CPU normalizada >90 % o memoria >85 % del límite durante más de 30 s | Señal de presión de recursos; analizar conjuntamente RTF y capacidad de respuesta |
| Crecimiento persistente de memoria, OOM o pérdida de respuesta | Conservar fallo y detener continuación ordinaria hasta revisión; sin limpieza/reinicio automático |

CPU alta por sí sola no demuestra que el caso sea inutilizable. Los umbrales deben
acordarse antes de medir y no cambiarse retrospectivamente para obtener PASS.
Presentar cada repetición y la variación entre corridas, no tratar las muestras
temporales correlacionadas como repeticiones independientes.

## 6. Decisiones pendientes y autorización futura

1. Revisar integración segura del perfil rover y sus comprobaciones; B1/B2 quedan
   pendientes hasta entonces. No añadir control de rover o simultaneidad a este ensayo.
2. Acordar objetivos de fluidez, umbrales, intervalo entre corridas, política de
   cachés/carga externa, warm-up y duración. Registrar cualquier cambio de protocolo.
3. Seleccionar/verificar colectores, fuente de RTF, unidades, normalización y coste
   de muestreo; comprobar disponibilidad sin instalar utilidades automáticamente.
4. Revisar estado actual y obtener autorización explícita de la campaña/operaciones
   de lifecycle antes de ejecutar. Autorizaciones de aperturas anteriores no valen
   para estas doce corridas. Este documento no admite trabajos ni reserva vehículos.
5. Conservar fallos y evidencia visual; ante incertidumbre de ejecución o reservas,
   bloquear la continuación y seguir el procedimiento de seguridad correspondiente.

No se ha ejecutado ninguna fase de esta campaña al crear el protocolo. La propuesta
no demuestra rendimiento aceptable del rover ni identifica la causa de GUI negra.
