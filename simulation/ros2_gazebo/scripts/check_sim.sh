#!/usr/bin/env bash

set -euo pipefail

CONTAINER="tfg-ardupilot-gazebo"

echo "========================================"
echo " TFG - Simulation Check"
echo "========================================"
echo

echo "[1/5] Docker container..."

if [[ "$(docker inspect -f '{{.State.Running}}' "$CONTAINER" 2>/dev/null || true)" != "true" ]]; then
    echo "[FAIL] Container is not running."
    exit 1
fi

echo "[PASS] Container running."

echo
echo "[2/5] Gazebo server..."

if ! docker exec "$CONTAINER" bash -lc \
    'pgrep -f "[g]z sim.*runway.sdf" >/dev/null'; then
    echo "[FAIL] Gazebo runway world is not running."
    exit 1
fi

echo "[PASS] Gazebo runway world running."

echo
echo "[3/5] ArduPilot processes..."

ARDUCOPTER_COUNT="$(
    docker exec "$CONTAINER" bash -lc \
    'pgrep -x arducopter | wc -l'
)"

if [[ "$ARDUCOPTER_COUNT" -ne 2 ]]; then
    echo "[FAIL] Expected 2 ArduCopter processes."
    echo "       Found: $ARDUCOPTER_COUNT"
    exit 1
fi

echo "[PASS] 2 ArduCopter processes running."

echo
echo "[4/5] ROS 2 vehicle interfaces..."

READY=0

for i in $(seq 1 15); do

    TOPICS="$(
        docker exec "$CONTAINER" bash -lc '
        source /opt/ros/humble/setup.bash
        source /root/ardu_ws/install/setup.bash
        ros2 topic list 2>/dev/null || true
        '
    )"

    if echo "$TOPICS" | grep -qx "/ap/v1/status" && \
       echo "$TOPICS" | grep -qx "/ap/v2/status"; then
        READY=1
        break
    fi

    printf "."
    sleep 2
done

echo

if [[ "$READY" -ne 1 ]]; then
    echo "[FAIL] ROS 2 vehicle topics not available."
    exit 1
fi

echo "[PASS] /ap/v1/status"
echo "[PASS] /ap/v2/status"

echo
echo "[5/5] Pre-arm checks..."

ARMABLE=0

for ATTEMPT in $(seq 1 18); do

    D1="$(
        docker exec "$CONTAINER" bash -lc '
        source /opt/ros/humble/setup.bash
        source /root/ardu_ws/install/setup.bash

        timeout 30 ros2 service call \
        /ap/v1/prearm_check \
        std_srvs/srv/Trigger \
        "{}"
        ' 2>&1 || true
    )"

    D2="$(
        docker exec "$CONTAINER" bash -lc '
        source /opt/ros/humble/setup.bash
        source /root/ardu_ws/install/setup.bash

        timeout 30 ros2 service call \
        /ap/v2/prearm_check \
        std_srvs/srv/Trigger \
        "{}"
        ' 2>&1 || true
    )"

    if echo "$D1" | grep -q "success=True" && \
       echo "$D2" | grep -q "success=True"; then

        ARMABLE=1
        break
    fi

    printf "."
    sleep 5
done

echo

if [[ "$ARMABLE" -ne 1 ]]; then
    echo "[FAIL] Vehicles did not become armable."
    echo
    echo "Drone 1:"
    echo "$D1"
    echo
    echo "Drone 2:"
    echo "$D2"
    exit 1
fi

echo "[PASS] /ap/v1 - Vehicle is Armable"
echo "[PASS] /ap/v2 - Vehicle is Armable"

echo
echo "========================================"
echo " SIMULATION HEALTHY"
echo "========================================"
echo
echo "Drone 1 -> READY"
echo "Drone 2 -> READY"
