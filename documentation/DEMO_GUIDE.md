> **Documento histórico (04–06/10/2026)**, restaurado de la rama `feature/ardupilot-ros2`. Describe la base de simulación y la primera capa agéntica de esa fecha; no se mantiene ni es una instrucción operativa vigente. La arquitectura actual está en [docs/integrated-architecture.md](../docs/integrated-architecture.md) y el índice en [docs/INDEX.md](../docs/INDEX.md).
>
> **No ejecutar los comandos de este documento.** Arrancan Gazebo y ArduPilot SITL, cambian el modo o arman vehículos directamente, sin las comprobaciones actuales. El simulador solo se arranca y se detiene mediante el ciclo de vida del proyecto ([tools/simulation_lifecycle.py](../tools/simulation_lifecycle.py); perfiles en [docs/simulation-profiles.md](../docs/simulation-profiles.md); reconciliación y exclusión en [docs/reconciliation-and-lifecycle.md](../docs/reconciliation-and-lifecycle.md)) y con autorización explícita del operador. Ningún armado, despegue, misión o movimiento sin esa autorización.

# TFG Simulation Demo Guide

## Objective

Demonstrate two independently controlled UAVs using:

- Gazebo Harmonic
- ArduPilot SITL
- ROS 2 Humble
- AP_DDS / micro-ROS

Vehicles:

- Drone 1 -> `/ap/v1`
- Drone 2 -> `/ap/v2`

The original 3-vehicle configuration with two drones and one rover is preserved and has also been validated.

---

## Demo

In VS Code:

`Ctrl + Shift + P`

Select:

`Tasks: Run Task`

### 1. Start

Run:

`TFG: Start Simulation`

Wait for:

```text
SIMULATION READY

Drone 1 -> /ap/v1
Drone 2 -> /ap/v2