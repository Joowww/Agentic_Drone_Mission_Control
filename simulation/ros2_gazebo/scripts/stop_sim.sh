#!/usr/bin/env bash

set -euo pipefail

CONTAINER="tfg-ardupilot-gazebo"

echo "========================================"
echo " TFG - Stop Simulation"
echo "========================================"
echo

if [[ "$(docker inspect -f '{{.State.Running}}' "$CONTAINER" 2>/dev/null || true)" != "true" ]]; then
    echo "[INFO] Container is not running."
    echo
    echo "========================================"
    echo " SIMULATION STOPPED"
    echo "========================================"
    exit 0
fi

echo "[1/3] Stopping ROS 2 launch process..."

docker exec "$CONTAINER" bash -lc '
if [[ -f /tmp/tfg_demo.pid ]]; then

    PID="$(cat /tmp/tfg_demo.pid 2>/dev/null || true)"

    if [[ -n "$PID" ]] && kill -0 "$PID" 2>/dev/null; then
        echo "      Sending SIGINT to launch PID $PID..."
        kill -INT "$PID" 2>/dev/null || true
    else
        echo "      Saved launch PID is no longer running."
    fi

else
    echo "      No saved launch PID found."
fi
'

echo
echo "[2/3] Waiting for normal shutdown..."

for i in $(seq 1 10); do

    RUNNING="$(
        docker exec "$CONTAINER" bash -lc '
        FOUND=0

        pgrep -x arducopter >/dev/null 2>&1 && FOUND=1
        pgrep -x ardurover >/dev/null 2>&1 && FOUND=1
        pgrep -x micro_ros_agent >/dev/null 2>&1 && FOUND=1
        pgrep -f "[m]avproxy.py" >/dev/null 2>&1 && FOUND=1
        pgrep -f "[g]z sim" >/dev/null 2>&1 && FOUND=1

        echo "$FOUND"
        '
    )"

    if [[ "$RUNNING" == "0" ]]; then
        echo "      All simulation processes stopped normally."
        break
    fi

    printf "."
    sleep 1
done

echo
echo
echo "[3/3] Cleaning remaining processes if necessary..."

docker exec "$CONTAINER" bash -lc '
pkill -TERM -x arducopter 2>/dev/null || true
pkill -TERM -x ardurover 2>/dev/null || true
pkill -TERM -x micro_ros_agent 2>/dev/null || true
pkill -TERM -f "[m]avproxy.py" 2>/dev/null || true
pkill -TERM -f "[g]z sim" 2>/dev/null || true

sleep 2

pkill -KILL -x arducopter 2>/dev/null || true
pkill -KILL -x ardurover 2>/dev/null || true
pkill -KILL -x micro_ros_agent 2>/dev/null || true
pkill -KILL -f "[m]avproxy.py" 2>/dev/null || true
pkill -KILL -f "[g]z sim" 2>/dev/null || true

rm -f /tmp/tfg_demo.pid
'

sleep 1

ARDUCOPTERS="$(docker exec "$CONTAINER" bash -lc 'pgrep -x arducopter 2>/dev/null | wc -l')"
ARDUROVERS="$(docker exec "$CONTAINER" bash -lc 'pgrep -x ardurover 2>/dev/null | wc -l')"
MICROROS="$(docker exec "$CONTAINER" bash -lc 'pgrep -x micro_ros_agent 2>/dev/null | wc -l')"
GAZEBO="$(docker exec "$CONTAINER" bash -lc 'pgrep -f "[g]z sim" 2>/dev/null | wc -l')"
MAVPROXY="$(docker exec "$CONTAINER" bash -lc 'pgrep -f "[m]avproxy.py" 2>/dev/null | wc -l')"

if [[ "$ARDUCOPTERS" != "0" ]] || \
   [[ "$ARDUROVERS" != "0" ]] || \
   [[ "$MICROROS" != "0" ]] || \
   [[ "$GAZEBO" != "0" ]] || \
   [[ "$MAVPROXY" != "0" ]]; then

    echo
    echo "[ERROR] Some simulation processes are still running."
    echo "ArduCopter:      $ARDUCOPTERS"
    echo "ArduRover:       $ARDUROVERS"
    echo "micro_ros_agent: $MICROROS"
    echo "Gazebo:          $GAZEBO"
    echo "MAVProxy:        $MAVPROXY"
    exit 1
fi

echo
echo "========================================"
echo " SIMULATION STOPPED"
echo "========================================"
