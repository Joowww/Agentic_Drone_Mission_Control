#!/usr/bin/env bash

set -euo pipefail

CONTAINER="tfg-ardupilot-gazebo"
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
PROFILE="${TFG_SIM_PROFILE-two_drones}"
profile_field() {
    (cd "$PROJECT_DIR" && "$PROJECT_DIR/.venv/bin/python" -m tools.simulation_profiles --profile "$PROFILE" "$1")
}
WORLD="$(profile_field world)"
PROCESS_CHECK="$(profile_field process-check)"
read -r SITL_EXECUTABLE EXPECTED_COUNT <<< "$PROCESS_CHECK"
PROFILE_TOPICS="$(profile_field status-topics)"
PROFILE_SERVICES="$(profile_field prearm-services)"
mapfile -t STATUS_TOPICS <<< "$PROFILE_TOPICS"
mapfile -t PREARM_SERVICES <<< "$PROFILE_SERVICES"

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
    'pgrep -f "[g]z sim.*${1}.sdf" >/dev/null' bash "$WORLD"; then
    echo "[FAIL] Gazebo runway world is not running."
    exit 1
fi

echo "[PASS] Gazebo runway world running."

echo
echo "[3/5] ArduPilot processes..."

SITL_COUNT="$(
    docker exec "$CONTAINER" bash -lc \
    'pgrep -x "$1" | wc -l' bash "$SITL_EXECUTABLE"
)"

if [[ "$SITL_COUNT" -ne "$EXPECTED_COUNT" ]]; then
    echo "[FAIL] Expected 2 ArduCopter processes."
    echo "       Found: $SITL_COUNT"
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

    ALL_TOPICS=1
    for TOPIC in "${STATUS_TOPICS[@]}"; do
        if ! echo "$TOPICS" | grep -qxF "$TOPIC"; then ALL_TOPICS=0; fi
    done
    if [[ "$ALL_TOPICS" -eq 1 ]]; then
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

    ALL_ARMABLE=1
    PREARM_OUTPUTS=()
    for SERVICE in "${PREARM_SERVICES[@]}"; do
        OUTPUT="$(
            docker exec "$CONTAINER" bash -lc '
            source /opt/ros/humble/setup.bash
            source /root/ardu_ws/install/setup.bash
            timeout 30 ros2 service call "$1" std_srvs/srv/Trigger "{}"
            ' bash "$SERVICE" 2>&1 || true
        )"
        PREARM_OUTPUTS+=("$OUTPUT")
        if ! echo "$OUTPUT" | grep -q "success=True"; then ALL_ARMABLE=0; fi
    done
    if [[ "$ALL_ARMABLE" -eq 1 ]]; then
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
    printf '%s\n' "${PREARM_OUTPUTS[@]}"
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
