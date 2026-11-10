#!/usr/bin/env bash

set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
(cd "$PROJECT_DIR" && "$PROJECT_DIR/.venv/bin/python" -m tools.simulation_lifecycle verify)

CONTAINER="tfg-ardupilot-gazebo"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

exec 9>/tmp/tfg_simulation_control.lock
if ! flock -n 9; then
    echo "[ERROR] Another simulation lifecycle operation is in progress."
    exit 1
fi

if [[ "$(docker inspect -f '{{.State.Running}}' "$CONTAINER" 2>/dev/null || true)" != "true" ]]; then
    echo "[INFO] Container is not running."
    exit 0
fi

# Share exactly the same project ownership, shutdown and final verification as
# start_sim.sh. Includes all launch supervisors and their auxiliary processes.
docker cp "$PROJECT_DIR/tools/simulation_profiles.py" "$CONTAINER:/tmp/tfg_simulation_profiles.py" >/dev/null
docker cp "$SCRIPT_DIR/sim_processes.py" "$CONTAINER:/tmp/tfg_sim_processes.py" >/dev/null
docker exec -e TFG_SIM_PROFILE="${TFG_SIM_PROFILE-two_drones}" "$CONTAINER" python3 /tmp/tfg_sim_processes.py stop

echo "SIMULATION STOPPED: no live processes attributable to the project remain."
