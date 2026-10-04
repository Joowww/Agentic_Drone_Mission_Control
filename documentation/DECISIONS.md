# Technical Decision Log

## D001 — ArduPilot SITL

Use ArduPilot SITL as the simulated autopilot.

Reason:

SITL executes ArduPilot autopilot software without requiring physical hardware and facilitates later transfer to real vehicles.

---

## D002 — ROS 2 Humble

Use ROS 2 as the robotics communication layer.

Reason:

ROS 2 provides distributed communication, topics, services, standard message types and multi-robot support.

---

## D003 — Native ArduPilot DDS integration

Use AP_DDS / micro-ROS as the primary ROS 2 interface.

Reason:

It provides a direct ROS 2 interface to ArduPilot without requiring MAVROS in the current architecture.

---

## D004 — Gazebo Harmonic

Use Gazebo Harmonic as the physics simulator.

Reason:

Gazebo provides vehicle dynamics, simulated sensors, environments and multi-vehicle support.

---

## D005 — Docker

Run the simulation environment inside Docker.

Reason:

Docker improves dependency isolation, reproducibility, portability and future teaching reuse.

---

## D006 — Separate AI and simulation during development

Do not immediately connect LangGraph to the simulator.

Reason:

Independent validation makes debugging easier and isolates failures between reasoning/orchestration and vehicle control.

---

## D007 — Reduced multi-vehicle launch

Create `tfg_demo.launch.py` from the upstream ArduPilot multiagent example.

The current configuration keeps:

- Drone 1;
- Drone 2;
- Rover.

The plane is removed because it is not required for the current TFG scenario.

RViz is disabled during performance tests.

---

## D008 — Preserve a stable baseline

Do not modify the validated `tfg_demo.launch.py` when experimenting.

New experiments must use separate files, for example:

```text
tfg_demo_2drones.launch.py
```
