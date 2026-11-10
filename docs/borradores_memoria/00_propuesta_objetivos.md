# Propuesta de objetivos del TFG (BORRADOR para consolidar el alcance con Toni)

Preparado el 30/10/2026 a partir de la revisión de alcance del mismo día. **No es un documento acordado.**
- **OA6, dataset de telemetría:** tiene una **confirmación explícita y reciente** de Toni, comunicada por Joel el 30/10/2026.
- **Los demás objetivos:** proceden de la **dirección previa del proyecto** (orquestación de drones y rover en agricultura de precisión). Hay que **consolidar su alcance** con Toni. No se consideran inexistentes ni rechazados; solo falta fijar hasta dónde llega cada uno.

Convenciones:
- **[DEMOSTRADO-SITL]**, **[DEMOSTRADO-OFFLINE]**, **[PARCIAL]**, **[PENDIENTE]** y **[OPCIONAL]**: estado a la fecha de la evidencia citada. No describen el estado actual del sistema.
- **Sintético** significa con dobles de prueba. **SITL** es simulación con ArduPilot y Gazebo. El hardware físico **no** es requisito.

## Objetivo general (dirección del proyecto)

Diseñar, implementar y evaluar un **sistema de control de misiones con un agente** para **agricultura de precisión**. El sistema debe:
- **planificar** misiones con un agente LLM (Hermes) que solo usa herramientas restringidas;
- **validarlas** de forma determinista y someter cualquier efecto a la **autorización explícita del operador**, que es distinta de la validación;
- **ejecutarlas en simulación** (ArduPilot SITL, ROS 2 con AP_DDS y Gazebo);
- **coordinar** drones y un rover en un escenario agrícola;
- dejar **evidencia trazable** y un **dataset de telemetría** de cada ejecución.

**Objetivo final frente a hitos intermedios.** El objetivo final es la **coordinación aire–suelo**: los drones visitan puntos de interés y el rover visita un punto ya alcanzado por un dron, según dependencias **observadas**. Los hitos del rover no lo demuestran por sí solos:
- la identidad del rover;
- **un pulso de control**;
- la navegación hasta un punto.

En concreto, **un pulso del rover no demuestra navegación ni coordinación.**

## 1. Objetivos académicos y cómo se comprobaría cada uno

| Id | Objetivo | Cómo se comprobaría | Evidencia existente (fecha) | Estado |
| --- | --- | --- | --- | --- |
| OA1 | **Planificación asistida por LLM con herramientas restringidas:** Hermes y servidor MCP producen misiones estructuradas a partir de una petición | (a) Casos con especificación completa → misión validada (transcripción). (b) Evaluación con un protocolo fijado, casos y denominadores, y **revisión humana** de las explicaciones. Hay que distinguir siempre transcripción de planificación autónoma | H1 `BOUND` (24/10); ejecución en contenedor r2 idéntica a H1 (28/10); H3 `NOT_VALIDATED`; H3b validado con explicación sin revisar; piloto 1/2 y 5/8 tras la enmienda | [PARCIAL]: (a) hecho; (b) [PENDIENTE] |
| OA2 | **Validación determinista y seguridad operativa.** Se separan tres cosas: (i) la **viabilidad** de la misión (`mission_status`, p. ej. FEASIBLE); (ii) el estado **APPROVED** del software (`execution_status`: el validador acepta la misión según sus reglas, lo que **no es un permiso operativo**); (iii) la **autorización explícita del operador**, por operación y con alcance concreto (una declaración, no una autenticación). Además: lifecycle, exclusión y reconciliación antes de cualquier efecto | Pruebas offline de cada regla y bloqueo, más casos reales en los que el sistema bloqueó o rechazó (p. ej. H3 detectado como no validado) | Validador, compuertas y registros documentados. Suites que pasan, que **no** equivalen a demostración operacional | [DEMOSTRADO-OFFLINE] en reglas; operativo en las sesiones citadas |
| OA3-G | **Ejecución aérea por el ejecutor (vía G, GUIDED):** misión validada → ejecutor del proyecto → SITL | Secuencia de dos drones con criterios de aceptación (tolerancias 1,0 m en horizontal y 0,75 m en altura) y registro conservado | H2 `6628bc51` PASSED en los dos drones (24/10); runs previos con FAILED y ERROR conservados | [DEMOSTRADO-SITL] (sesión histórica) |
| OA3-M | **Ejecución aérea por misión importada (vía M):** `.plan` → QGC → carga → lectura de vuelta → AUTO | Prueba **independiente** de la vía G, en tres pasos con criterio propio: (1) QGC abre y guarda sin cambios semánticos; (2) la carga y la lectura de vuelta en SITL coinciden con el archivo ítem a ítem; (3) la ejecución en AUTO cumple los criterios de aceptación | (1) hecho el 27/10 y el 30/10 | [PARCIAL]: (2) y (3) [PENDIENTE] |
| OA4 | **Coordinación aire–suelo** en el escenario agrícola (**objetivo final**) | Ensayo integrado en SITL: secuencia aérea, y R1 (rover al POI_A1 alcanzado por drone_01) completado por evidencia, con las dependencias del coordinador | Coordinación aérea real (H2); R1 `VERIFIED_SYNTHETIC` con doble; R1 real `BLOCKED_PENDING` | [PARCIAL]. Hitos del rover según los informes del subsistema rover (no verificados de forma independiente): identidad parcial, primer pulso **bloqueado** |
| OA5 | **Referencias geográficas y escenarios:** emplazamiento, flota y plantillas; marcos y altitudes explícitos | Validación del emplazamiento; correspondencia de las misiones derivadas; en un ensayo, observar el lanzamiento frente al despegue planificado | Validador y paquetes sintéticos; correspondencia comprobada (30/10) | [DEMOSTRADO-OFFLINE]; la correspondencia spawn↔emplazamiento está [PENDIENTE] |
| OA6 | **Dataset de telemetría** (confirmado por Toni): cada ejecución enlazada con su misión y su resultado | Importación reproducible desde fuentes selladas, validador, procedencia hasta el campo y separación por familia. **Sin entrenamiento ni afirmaciones de predicción** en esta fase | Piloto 0.1 y revisiones 0.2 y 0.2.1 (5 ejecuciones SITL) | [PARCIAL]: crece con ejecuciones nuevas tras la fase 1 del registro |
| OA7 | **Evaluación con evidencia:** resultados con denominadores, limitaciones y separación entre sintético, SITL y hardware | Tablas reproducibles generadas desde las evidencias; cada afirmación con su fuente | Comparación experimental de Hermes (26/10); consultas del dataset | [PARCIAL] |

## 2. Objetivos de distribución para estudiantes

Propuesta: anexo o capítulo práctico, no núcleo académico.

| Id | Objetivo | Comprobación | Estado |
| --- | --- | --- | --- |
| OD1 | Entrega parcial reproducible: app offline, QGC y Hermes, solo con Hermes | Hashes, carga de imágenes y recorrido aislado | [PARCIAL]: 12/12 en el mismo equipo (`2026.10.30`) |
| OD2 | Entrega completa con simulador | Receta reproducible del simulador (subsistema rover) e independencia del equipo de Joel | [PENDIENTE] |
| OD3 | Prueba en un segundo ordenador | El mismo recorrido desde cero en otro equipo | [PENDIENTE] |
| OD4 | Licencia, versionado y publicación | Decisión y repositorio etiquetado | [PENDIENTE]: decisión de Joel y Toni |

## 3. Ampliaciones opcionales

No son requisitos; solo entran si sobra tiempo o lo pide Toni.
- **Registro persistente denso** (fase 2 del traspaso de telemetría) y **PlotJuggler** para la inspección visual.
- **Métricas de trayectoria** avanzadas sobre series densas.
- **Viento controlado en SITL** para estudiar la robustez.
- **Modelos de duración o energía.** La batería simulada de SITL puede estudiarse como **salida de un modelo**. No acredita consumo físico sin una validación frente a datos reales.
- **Web de misión de solo lectura**, citada como «objetivo aceptado» en un documento interno, sin requisito escrito. Grafana y paneles de Opik.
- **Hardware físico.**

## 4. Decisiones pendientes de Toni

1. **Objetivo final de coordinación (OA4).** ¿Debe la memoria demostrar R1 completo, es decir el rover navega hasta el punto alcanzado por el dron, o basta con un hito intermedio declarado (identidad o navegación aislada) más la coordinación aérea y R1 sintético?
2. **Vía M (OA3-M).** ¿Es obligatoria la ejecución en AUTO del `.plan`, o basta con exportar, importar en QGC y cargar y leer de vuelta en SITL?
3. **Hardware físico.** Propuesta: fuera de alcance. ¿De acuerdo?
4. **Evaluación de Hermes (OA1 y OA7).** ¿Número mínimo de casos, si la revisión humana de las explicaciones es obligatoria, y si basta un único modelo o proveedor?
5. **Dataset (OA6).** ¿Qué se espera para el TFG: diseño, método y piloto con N ejecuciones nuevas? ¿Cuál sería N? ¿Hay que publicarlo?
6. **Distribución.** ¿Es un objetivo evaluable o un anexo?
7. **Web de misión.** ¿Dentro o fuera del alcance?
8. **Licencia y publicación** del código y del dataset.
9. **Formato de la memoria:** plantilla, idioma, extensión y normas de citación.
