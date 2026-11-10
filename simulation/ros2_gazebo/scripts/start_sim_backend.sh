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

PROFILE="${TFG_SIM_PROFILE-two_drones}"
profile_field() {
    (cd "$PROJECT_DIR" && "$PROJECT_DIR/.venv/bin/python" -m tools.simulation_profiles --profile "$PROFILE" "$1")
}
LAUNCH_PACKAGE="$(profile_field launch-package)"
LAUNCH_FILE="$(profile_field launch-file)"
PORTS_JSON="$(profile_field ports-json)"
PROFILE_TOPICS="$(profile_field status-topics)"
mapfile -t STATUS_TOPICS <<< "$PROFILE_TOPICS"
HOST_LAUNCH="$SIM_DIR/launch/$LAUNCH_FILE"
CONTAINER_SOURCE_LAUNCH="/root/ardu_ws/src/ardupilot_gz/$LAUNCH_PACKAGE/launch/$LAUNCH_FILE"
CONTAINER_INSTALL_LAUNCH="/root/ardu_ws/install/$LAUNCH_PACKAGE/share/$LAUNCH_PACKAGE/launch/$LAUNCH_FILE"

ROVER_CONTEXT_ENV=()
if [[ "$PROFILE" == "two_drones_rover" && -z "${TFG_SIM_START_CONTEXT:-}" ]]; then
    echo "[ERROR] Missing protected rover environment reference."
    exit 1
fi
if [[ "$PROFILE" == "two_drones_rover" ]]; then
    ROVER_CONTEXT_ENV=(-e "TFG_SIM_START_CONTEXT=$TFG_SIM_START_CONTEXT")
fi

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

# Diagnostic selection was pinned under the inherited lifecycle lease. Bind all
# operations to that full container ID; never auto-start a stopped diagnostic env.
DIAGNOSTIC_ENV=(-e TFG_DIAGNOSTIC_AGENT= -e TFG_XRCE_TRACE=)
if [[ -n "${TFG_DIAGNOSTIC_AGENT:-}" ]]; then
    CONTAINER="$("$PROJECT_DIR/.venv/bin/python" -c 'import json,os; print(json.loads(os.environ["TFG_DIAGNOSTIC_AGENT"])["manifest"]["container_id"])')"
    [[ "$(docker inspect --format '{{.State.Running}}' "$CONTAINER")" == "true" ]] || exit 1
    # Validate the full helper set before copying or launching any process.
    HELPER_LAYOUT="$("$PROJECT_DIR/.venv/bin/python" -c 'from tools.rover_xrce_trace.selection import deployment; print("\n".join("\t".join(row) for row in deployment()))')"
    while IFS=$'\t' read -r source destination; do
        docker cp "$source" "$CONTAINER:$destination" >/dev/null
    done <<< "$HELPER_LAYOUT"
    DIAGNOSTIC_ENTRY="$("$PROJECT_DIR/.venv/bin/python" -c 'from tools.rover_xrce_trace.selection import HELPERS; print(HELPERS["selection.py"])')"
    DIAGNOSTIC_ENV=(-e "TFG_DIAGNOSTIC_AGENT=$TFG_DIAGNOSTIC_AGENT" -e TFG_XRCE_TRACE=)
    docker exec "${DIAGNOSTIC_ENV[@]}" "$CONTAINER" python3 "$DIAGNOSTIC_ENTRY" prepare
else
    echo "[1/6] Starting Docker container..."
    docker start "$CONTAINER" >/dev/null
fi

echo "[2/6] Stopping previous simulation processes..."

docker cp "$PROJECT_DIR/tools/simulation_profiles.py" "$CONTAINER:/tmp/tfg_simulation_profiles.py" >/dev/null
docker cp "$SCRIPT_DIR/sim_processes.py" "$CONTAINER:/tmp/tfg_sim_processes.py" >/dev/null
if [[ "$PROFILE" == "two_drones_rover" ]]; then
    docker cp "$PROJECT_DIR/tools/rover_environment_identity.py" "$CONTAINER:/tmp/tfg_rover_environment_identity.py" >/dev/null
    docker cp "$PROJECT_DIR/tools/rover_identity_worker.py" "$CONTAINER:/tmp/tfg_rover_identity_worker.py" >/dev/null
fi
docker exec -e TFG_SIM_PROFILE="${TFG_SIM_PROFILE-two_drones}" "$CONTAINER" python3 /tmp/tfg_sim_processes.py stop

echo "      Waiting for expected SITL ports $PORTS_JSON to be released..."

for i in $(seq 1 30); do

    PORT_STATUS="$(
        docker exec -e TFG_SIM_PORTS="$PORTS_JSON" -i "$CONTAINER" python3 - <<'PYPORT'
import json
import os
ports = set(json.loads(os.environ["TFG_SIM_PORTS"]))
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

echo "[3/6] Preparing scoped Gazebo resource lookup (no model rewriting)..."

echo "[4/6] Updating launch file inside Docker..."

docker exec "$CONTAINER" mkdir -p "${CONTAINER_SOURCE_LAUNCH%/*}" "${CONTAINER_INSTALL_LAUNCH%/*}"

docker cp \
"$HOST_LAUNCH" \
"$CONTAINER:$CONTAINER_SOURCE_LAUNCH" \
>/dev/null

docker cp \
"$HOST_LAUNCH" \
"$CONTAINER:$CONTAINER_INSTALL_LAUNCH" \
>/dev/null

echo "[5/6] Starting Gazebo + ArduPilot..."

docker exec -e TFG_SIM_GUI="${TFG_SIM_GUI:-true}" -e TFG_SIM_PROFILE="$PROFILE" "${ROVER_CONTEXT_ENV[@]}" "${DIAGNOSTIC_ENV[@]}" "$CONTAINER" bash -lc '
source /opt/ros/humble/setup.bash
source /root/ardu_ws/install/setup.bash

# package://ardupilot_gazebo/... includes the package name (URI authority).
# Search its share PARENT, not only its models directory. This environment is
# scoped to this launch and inherited by BOTH server and GUI via ros_gz_sim.
# Resolve inside the container; never embed a host workspace pathname.
PACKAGE_SHARE_PARENT="$(ros2 pkg prefix ardupilot_gazebo)/share"
[[ -d "$PACKAGE_SHARE_PARENT/ardupilot_gazebo/models" ]] || {
    echo "[ERROR] Missing ArduPilot package resources." >&2
    exit 1
}
case ":${GZ_SIM_RESOURCE_PATH-}:" in
    *":$PACKAGE_SHARE_PARENT:"*) ;;
    *) export GZ_SIM_RESOURCE_PATH="$PACKAGE_SHARE_PARENT${GZ_SIM_RESOURCE_PATH:+:$GZ_SIM_RESOURCE_PATH}" ;;
esac
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

    READY=1
    for TOPIC in "${STATUS_TOPICS[@]}"; do
        if ! echo "$TOPICS" | grep -qxF "$TOPIC"; then READY=0; fi
    done
    # A foreign process may acquire a port after the recovery observation.
    # Inspect only this launch log; failures propagate to lifecycle UNCONFIRMED.
    docker exec "$CONTAINER" python3 /tmp/tfg_sim_processes.py verify-start

    if [[ "$READY" -eq 1 ]]; then
        if [[ "$PROFILE" == "two_drones_rover" ]]; then
            # Keep original stdout/stderr and rc even on rejection. Never replay
            # or reconstruct the failed row from a later resource observation.
            (
                set -o noclobber
                RESULT_DIR="${TFG_LIFECYCLE_RESULT_DIR:?Missing protected result directory}"
                ACQUISITION_RC=0
                docker exec "${DIAGNOSTIC_ENV[@]}" "$CONTAINER" python3 /tmp/tfg_sim_processes.py verify-acquisition \
                    >"$RESULT_DIR/acquisition.stdout" 2>"$RESULT_DIR/acquisition.stderr" || ACQUISITION_RC=$?
                printf '%s\n' "$ACQUISITION_RC" >"$RESULT_DIR/acquisition.returncode"
                cat "$RESULT_DIR/acquisition.stdout"
                cat "$RESULT_DIR/acquisition.stderr" >&2
                exit "$ACQUISITION_RC"
            )
        fi

        echo
        echo "========================================"
        echo " SIMULATION READY"
        echo "========================================"
        echo
        for TOPIC in "${STATUS_TOPICS[@]}"; do echo "Infrastructure interface expected: ${TOPIC%/status}"; done
        echo "No movement authorization; rover mission execution unsupported."
        echo
        echo "Gazebo GUI requested: ${TFG_SIM_GUI:-true} (visual confirmation required)"
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
