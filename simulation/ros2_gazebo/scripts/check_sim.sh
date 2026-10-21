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

while read -r SITL_EXECUTABLE EXPECTED_COUNT; do
    SITL_COUNT="$(
        docker exec "$CONTAINER" bash -lc \
        'pgrep -x "$1" | wc -l' bash "$SITL_EXECUTABLE"
    )"
    if [[ "$SITL_COUNT" -ne "$EXPECTED_COUNT" ]]; then
        echo "[FAIL] Expected $EXPECTED_COUNT $SITL_EXECUTABLE processes."
        echo "       Found: $SITL_COUNT"
        exit 1
    fi
    echo "[PASS] $EXPECTED_COUNT $SITL_EXECUTABLE processes running."
done <<< "$PROCESS_CHECK"

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
        if echo "$TOPICS" | grep -qxF "$TOPIC"; then
            echo "TFG_READINESS_VEHICLE ${TOPIC%/status} status PASS"
        else
            echo "TFG_READINESS_VEHICLE ${TOPIC%/status} status FAIL"
            ALL_TOPICS=0
        fi
    done
    if [[ "$ALL_TOPICS" -eq 1 ]]; then
        READY=1
        break
    fi

    printf ".\n"
    sleep 2
done

echo

if [[ "$READY" -ne 1 ]]; then
    echo "[FAIL] ROS 2 vehicle topics not available."
    exit 1
fi

for TOPIC in "${STATUS_TOPICS[@]}"; do echo "[PASS] $TOPIC"; done

echo
echo "[5/5] Pre-arm checks..."

ARMABLE=0

for ATTEMPT in $(seq 1 18); do

    ALL_ARMABLE=1
    for SERVICE in "${PREARM_SERVICES[@]}"; do
        # Stream attempt/output/completion events directly: no command substitution
        # can hide the response body until the outer readiness timeout has expired.
        if (cd "$PROJECT_DIR" && "$PROJECT_DIR/.venv/bin/python" -u -m tools.prearm_diagnostics \
                --service "$SERVICE" --attempt "$ATTEMPT"); then
            echo "TFG_READINESS_VEHICLE ${SERVICE%/prearm_check} prearm PASS"
        else
            echo "TFG_READINESS_VEHICLE ${SERVICE%/prearm_check} prearm FAIL"
            ALL_ARMABLE=0
        fi
    done
    if [[ "$ALL_ARMABLE" -eq 1 ]]; then
        ARMABLE=1
        break
    fi

    printf ".\n"
    sleep 5
done

echo

if [[ "$ARMABLE" -ne 1 ]]; then
    echo "[FAIL] Vehicles did not become armable."
    echo
    exit 1
fi

for SERVICE in "${PREARM_SERVICES[@]}"; do echo "[PASS] ${SERVICE%/prearm_check} - Vehicle is Armable"; done

echo
echo "========================================"
echo " SIMULATION HEALTHY"
echo "========================================"
echo
for TOPIC in "${STATUS_TOPICS[@]}"; do echo "${TOPIC%/status} -> READY (infrastructure only; no movement authorization)"; done
