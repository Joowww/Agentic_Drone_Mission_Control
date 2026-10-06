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