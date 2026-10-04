# Simulation Performance Tests

## Objective

Measure the computational cost of different simulated vehicle configurations and identify a configuration suitable for an interactive TFG demonstration.

## Metrics

The following metrics will be recorded:

- number of simulated vehicles;
- Docker CPU usage;
- Docker memory usage;
- Real Time Factor;
- pre-arm success;
- takeoff success;
- qualitative simulation responsiveness.

## Results

| Test | Drones | Rover | RViz | Gazebo GUI | CPU | RAM | RTF | Result |
|---|---:|---:|---|---|---:|---:|---:|---|
| Baseline A | 2 | 1 | OFF | ON | 448.26 % | 3.05 GiB | ~0.03-0.04 | PASS |
| Test B | 2 | 0 | OFF | ON | TBD | TBD | TBD | Pending |
| Test C | 1 | 0 | OFF | ON | TBD | TBD | TBD | Pending |

## Baseline A

Configuration:

```text
Drone 1
Drone 2
Rover 1
Gazebo GUI
RViz OFF
```

Docker statistics:

```text
CPU: 448.26 %
Memory: 3.05 GiB / 15.5 GiB
PIDs: 349
```

Measured simulation progression was approximately 3-4 % of real time.

## Interpretation

The three-vehicle architecture is functionally correct but too slow for a fluid interactive demonstration.

The next experiment removes the Rover while preserving both drones.

This will determine whether the Rover is a significant source of simulation overhead or whether the main bottleneck is caused by the two ArduCopter/Gazebo instances themselves.
