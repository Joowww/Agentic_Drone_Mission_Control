#!/usr/bin/env bash

set -euo pipefail

CONTAINER="tfg-ardupilot-gazebo"

echo "========================================"
echo " TFG - Two Drone Flight Demo"
echo "========================================"
echo

echo "[1/6] Checking simulation..."

if ! "$(dirname "$0")/check_sim.sh"; then
    echo
    echo "[ERROR] Simulation health check failed."
    exit 1
fi

echo
echo "[2/6] Switching both drones to GUIDED mode..."

for VEHICLE in v1 v2; do

    RESULT="$(
        docker exec "$CONTAINER" bash -lc "
        source /opt/ros/humble/setup.bash
        source /root/ardu_ws/install/setup.bash

        ros2 service call \
        /ap/$VEHICLE/mode_switch \
        ardupilot_msgs/srv/ModeSwitch \
        '{mode: 4}'
        " 2>&1
    )"

    echo "$RESULT"

    if ! echo "$RESULT" | grep -q "status=True"; then
        echo
        echo "[ERROR] Could not set $VEHICLE to GUIDED mode."
        exit 1
    fi

done

echo
echo "[PASS] Both drones in GUIDED mode."

echo
echo "[3/6] Arming motors..."

for VEHICLE in v1 v2; do

    RESULT="$(
        docker exec "$CONTAINER" bash -lc "
        source /opt/ros/humble/setup.bash
        source /root/ardu_ws/install/setup.bash

        ros2 service call \
        /ap/$VEHICLE/arm_motors \
        ardupilot_msgs/srv/ArmMotors \
        '{arm: true}'
        " 2>&1
    )"

    echo "$RESULT"

    if ! echo "$RESULT" | grep -q "result=True"; then
        echo
        echo "[ERROR] Could not arm $VEHICLE."
        exit 1
    fi

done

echo
echo "[PASS] Both drones armed."

echo
echo "[4/6] Sending takeoff commands..."

echo
echo "Drone 1 -> 5 metres"

D1="$(
    docker exec "$CONTAINER" bash -lc '
    source /opt/ros/humble/setup.bash
    source /root/ardu_ws/install/setup.bash

    ros2 service call \
    /ap/v1/experimental/takeoff \
    ardupilot_msgs/srv/Takeoff \
    "{alt: 5.0}"
    ' 2>&1
)"

echo "$D1"

if ! echo "$D1" | grep -q "status=True"; then
    echo "[ERROR] Drone 1 takeoff command failed."
    exit 1
fi

echo
echo "Drone 2 -> 7 metres"

D2="$(
    docker exec "$CONTAINER" bash -lc '
    source /opt/ros/humble/setup.bash
    source /root/ardu_ws/install/setup.bash

    ros2 service call \
    /ap/v2/experimental/takeoff \
    ardupilot_msgs/srv/Takeoff \
    "{alt: 7.0}"
    ' 2>&1
)"

echo "$D2"

if ! echo "$D2" | grep -q "status=True"; then
    echo "[ERROR] Drone 2 takeoff command failed."
    exit 1
fi

echo
echo "========================================"
echo " TAKEOFF COMMANDS ACCEPTED"
echo "========================================"
echo
echo "Drone 1 target altitude: 5 m"
echo "Drone 2 target altitude: 7 m"
echo
echo "The simulation runs slower than realtime."
echo "Wait until both drones reach their altitude."
echo
echo "Press ENTER when you want both drones to LAND."
read -r

echo
echo "[5/6] Landing both drones..."

for VEHICLE in v1 v2; do

    RESULT="$(
        docker exec "$CONTAINER" bash -lc "
        source /opt/ros/humble/setup.bash
        source /root/ardu_ws/install/setup.bash

        ros2 service call \
        /ap/$VEHICLE/mode_switch \
        ardupilot_msgs/srv/ModeSwitch \
        '{mode: 9}'
        " 2>&1
    )"

    echo "$RESULT"

    if ! echo "$RESULT" | grep -q "status=True"; then
        echo
        echo "[ERROR] LAND command failed for $VEHICLE."
        exit 1
    fi

done

echo
echo "[6/6] Demo sequence completed."

echo
echo "========================================"
echo " LAND COMMANDS ACCEPTED"
echo "========================================"
echo
echo "Drone 1 -> LAND"
echo "Drone 2 -> LAND"
echo
echo "Wait for automatic touchdown and disarm."
