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

# Close modes are exclusive and checked before any inspection, copy or signal:
#   PASSIVE    (TFG_PASSIVE_SESSION_*): always refused. The pinned process reader cannot attribute processes to a
#              passive session (the pinned start path does not mark them), so ownership cannot be verified, even
#              when a diagnostic descriptor is also present. The lifecycle records the close as UNCONFIRMED and keeps
#              its restrictions. Closing a passive session needs a reviewed reader revision.
#   DIAGNOSTIC (descriptor AND boot): the pinned reader selects exactly that session. A descriptor without its
#              boot would degrade to the general project selection, and a boot without descriptor is malformed.
#   ORDINARY   (none of them): the project's general cleanup; the lifecycle admits it only with no protected
#              session open or uncertain.
if [[ -n "${TFG_PASSIVE_SESSION_ID:-}" || -n "${TFG_PASSIVE_SESSION_BOOT_ID:-}" ]]; then
    echo "[BLOCKED] PASSIVE_STOP_OWNERSHIP_UNVERIFIABLE: no process signalled; passive session state UNKNOWN." >&2
    exit 3
fi
if [[ -n "${TFG_DIAGNOSTIC_CLOSE_BOOT_ID:-}" && -z "${TFG_DIAGNOSTIC_CLOSE_TARGET:-}" ]]; then
    echo "[BLOCKED] CLOSE_DESCRIPTOR_MISSING: boot fence given without its close descriptor; nothing signalled." >&2
    exit 3
fi
if [[ -n "${TFG_DIAGNOSTIC_CLOSE_TARGET:-}" && -z "${TFG_DIAGNOSTIC_CLOSE_BOOT_ID:-}" ]]; then
    echo "[BLOCKED] CLOSE_BOOT_MISSING: diagnostic descriptor without its boot fence; no general selection, nothing signalled." >&2
    exit 3
fi

if [[ -n "${TFG_DIAGNOSTIC_CLOSE_TARGET:-}" ]]; then
    CONTAINER="$("$PROJECT_DIR/.venv/bin/python" -c 'import json,os; print(json.loads(os.environ["TFG_DIAGNOSTIC_CLOSE_TARGET"])["manifest"]["container_id"])')"
    # An inspection failure is UNKNOWN, never evidence of a stopped container.
    RUNNING="$(docker inspect -f '{{.State.Running}}' "$CONTAINER")"
    if [[ "$RUNNING" == "false" ]]; then
        echo "[INFO] Exact diagnostic container is stopped; no process cleanup run."
        exit 0
    fi
    [[ "$RUNNING" == "true" ]] || exit 1
fi

if [[ -z "${TFG_DIAGNOSTIC_CLOSE_TARGET:-}" ]]; then
    # An inspection failure is UNKNOWN, never evidence of a stopped container.
    if ! RUNNING="$(docker inspect -f '{{.State.Running}}' "$CONTAINER")"; then
        echo "[ERROR] Container state could not be inspected; stop result UNKNOWN." >&2
        exit 1
    fi
    if [[ "$RUNNING" == "false" ]]; then
        echo "[INFO] Container is not running."
        exit 0
    fi
    [[ "$RUNNING" == "true" ]] || { echo "[ERROR] Unexpected container state '$RUNNING'; stop result UNKNOWN." >&2; exit 1; }
fi

# Share exactly the same project ownership, shutdown and final verification as
# start_sim.sh. Includes all launch supervisors and their auxiliary processes.
docker cp "$PROJECT_DIR/tools/simulation_profiles.py" "$CONTAINER:/tmp/tfg_simulation_profiles.py" >/dev/null
docker cp "$SCRIPT_DIR/sim_processes.py" "$CONTAINER:/tmp/tfg_sim_processes.py" >/dev/null
docker exec -e TFG_SIM_PROFILE="${TFG_SIM_PROFILE-two_drones}" \
    -e "TFG_DIAGNOSTIC_CLOSE_TARGET=${TFG_DIAGNOSTIC_CLOSE_TARGET:-}" \
    -e "TFG_DIAGNOSTIC_CLOSE_BOOT_ID=${TFG_DIAGNOSTIC_CLOSE_BOOT_ID:-}" \
    "$CONTAINER" python3 /tmp/tfg_sim_processes.py stop

echo "SIMULATION STOPPED: no live processes attributable to the project remain."
