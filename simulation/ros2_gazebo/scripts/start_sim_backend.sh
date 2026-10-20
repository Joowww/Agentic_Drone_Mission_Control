#!/usr/bin/env bash

set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
(cd "$PROJECT_DIR" && "$PROJECT_DIR/.venv/bin/python" -m tools.simulation_lifecycle verify)

CONTAINER="tfg-ardupilot-gazebo"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SIM_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

# Serialize lifecycle operations against the same container, including callers
# whose MCP request has already timed out while the backend is still running.
exec 9>/tmp/tfg_simulation_control.lock
if ! flock -n 9; then
    echo "[ERROR] Another simulation lifecycle operation is in progress."
    exit 1
fi

HOST_LAUNCH="$SIM_DIR/launch/tfg_demo_2drones.launch.py"

CONTAINER_SOURCE_LAUNCH="/root/ardu_ws/src/ardupilot_gz/ardupilot_gz_bringup/launch/tfg_demo_2drones.launch.py"
CONTAINER_INSTALL_LAUNCH="/root/ardu_ws/install/ardupilot_gz_bringup/share/ardupilot_gz_bringup/launch/tfg_demo_2drones.launch.py"

echo "========================================"
echo " TFG - Start Drone Simulation"
echo "========================================"
echo

if ! docker inspect "$CONTAINER" >/dev/null 2>&1; then
    echo "[ERROR] Docker container '$CONTAINER' does not exist."
    exit 1
fi

if [[ ! -f "$HOST_LAUNCH" ]]; then
    echo "[ERROR] Launch file not found:"
    echo "$HOST_LAUNCH"
    exit 1
fi

echo "[1/6] Starting Docker container..."
docker start "$CONTAINER" >/dev/null

echo "[2/6] Stopping previous simulation processes..."

docker cp "$SCRIPT_DIR/sim_processes.py" "$CONTAINER:/tmp/tfg_sim_processes.py" >/dev/null
docker exec "$CONTAINER" python3 /tmp/tfg_sim_processes.py stop

echo "      Waiting for SITL ports 5760 and 5770 to be released..."

for i in $(seq 1 30); do

    PORT_STATUS="$(
        docker exec -i "$CONTAINER" python3 - <<'PYPORT'
ports = {5760, 5770}
busy = set()

for filename in ("/proc/net/tcp", "/proc/net/tcp6"):
    with open(filename) as f:
        next(f)

        for line in f:
            fields = line.split()
            port = int(fields[1].split(":")[1], 16)
            state = fields[3]

            if port in ports and state == "0A":
                busy.add(port)

print(" ".join(str(p) for p in sorted(busy)))
PYPORT
    )"

    if [[ -z "$PORT_STATUS" ]]; then
        echo "      SITL ports are free."
        break
    fi

    if [[ "$i" -eq 30 ]]; then
        echo "[ERROR] SITL ports still occupied: $PORT_STATUS"
        exit 1
    fi

    sleep 1
done

echo "[3/6] Applying Gazebo model compatibility fix..."

docker exec "$CONTAINER" bash -lc '
source /opt/ros/humble/setup.bash
source /root/ardu_ws/install/setup.bash

MODEL_ROOT="$(ros2 pkg prefix ardupilot_gazebo)/share/ardupilot_gazebo/models"
SDF="$MODEL_ROOT/iris_with_gimbal/model.sdf"

if grep -q "package://ardupilot_gazebo/models/iris_with_standoffs" "$SDF"; then

    if [[ ! -f "$SDF.before_tfg_fix" ]]; then
        cp "$SDF" "$SDF.before_tfg_fix"
    fi

    sed -i \
    "s|package://ardupilot_gazebo/models/iris_with_standoffs|file://$MODEL_ROOT/iris_with_standoffs|g" \
    "$SDF"

    sed -i \
    "s|package://ardupilot_gazebo/models/gimbal_small_3d|file://$MODEL_ROOT/gimbal_small_3d|g" \
    "$SDF"

    echo "      Model fix applied."
else
    echo "      Model fix already present."
fi
'

echo "[4/6] Updating launch file inside Docker..."

docker exec "$CONTAINER" bash -lc '
mkdir -p /root/ardu_ws/src/ardupilot_gz/ardupilot_gz_bringup/launch
mkdir -p /root/ardu_ws/install/ardupilot_gz_bringup/share/ardupilot_gz_bringup/launch
'

docker cp \
"$HOST_LAUNCH" \
"$CONTAINER:$CONTAINER_SOURCE_LAUNCH" \
>/dev/null

docker cp \
"$HOST_LAUNCH" \
"$CONTAINER:$CONTAINER_INSTALL_LAUNCH" \
>/dev/null

echo "[5/6] Starting Gazebo + ArduPilot..."

docker exec -e TFG_SIM_GUI="${TFG_SIM_GUI:-true}" "$CONTAINER" bash -lc '
source /opt/ros/humble/setup.bash
source /root/ardu_ws/install/setup.bash
exec python3 /tmp/tfg_sim_processes.py start
'

echo "[6/6] Waiting for AP_DDS..."

for i in $(seq 1 60); do

    TOPICS="$(
        docker exec "$CONTAINER" bash -lc '
        source /opt/ros/humble/setup.bash
        source /root/ardu_ws/install/setup.bash
        ros2 topic list 2>/dev/null || true
        '
    )"

    if echo "$TOPICS" | grep -qx "/ap/v1/status" && \
       echo "$TOPICS" | grep -qx "/ap/v2/status"; then

        echo
        echo "========================================"
        echo " SIMULATION READY"
        echo "========================================"
        echo
        echo "Drone 1 -> /ap/v1"
        echo "Drone 2 -> /ap/v2"
        echo
        echo "Gazebo GUI: ON"
        echo "RViz:       OFF"
        echo
        exit 0
    fi

    printf "."
    sleep 2
done

echo
echo
echo "[ERROR] Simulation did not become ready."
echo
echo "Last log lines:"
echo

docker exec "$CONTAINER" \
tail -n 80 /tmp/tfg_demo.log || true

exit 1
