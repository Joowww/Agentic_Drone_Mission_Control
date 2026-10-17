"""v1 ownership wrapper for the existing interactive two-drone shell demo."""
import argparse
import os
from pathlib import Path
import subprocess
from uuid import uuid4

from tools.vehicle_execution_lock import (
    PROJECT_ROOT, VehicleBusy, execution_scope, identity_alive, mark_uncertain,
    process_identity, release, reserve, restriction,
)


def verify_child():
    record = restriction()
    if not record or record["owner_id"] != os.environ.get("TFG_V1_DEMO_OWNER"):
        return False
    # The verifier may be under a Bash subshell. Require the live reservation
    # owner somewhere in its ancestry, not an environment flag alone.
    if record["state"] != "EXECUTING" or not identity_alive(record["process"]):
        return False
    pid = os.getppid()
    for _ in range(16):
        if record["process"] == process_identity(pid):
            return True
        fields = Path(f"/proc/{pid}/stat").read_text().rpartition(")")[2].split()
        pid = int(fields[1])
        if pid <= 1:
            break
    return False


def run_demo():
    owner_id = str(uuid4())
    try:
        reserve(owner_id, "interactive_demo")
    except VehicleBusy as exc:
        print(str(exc))
        return 1
    try:
        with execution_scope(owner_id):
            result = subprocess.run(
                ["bash", str(PROJECT_ROOT / "simulation/ros2_gazebo/scripts/run_demo.sh")],
                env={**os.environ, "TFG_V1_DEMO_OWNER": owner_id}, cwd=PROJECT_ROOT, check=False,
            )
            # The shell demo only confirms LAND acceptance. Keep ownership until
            # v1's actual landed/disarmed state is observed, even if the script failed.
            from tools.simulation_mission_executor import _wait_for_landing
            landing = _wait_for_landing(vehicle="v1")
        if landing.get("landed") is True and landing.get("armed") is False and landing.get("flying") is False:
            release(owner_id)
        else:
            mark_uncertain(owner_id)
            return 1
        return result.returncode
    except BaseException:
        mark_uncertain(owner_id)
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--verify-child", action="store_true")
    args = parser.parse_args()
    return (0 if verify_child() else 1) if args.verify_child else run_demo()


if __name__ == "__main__":
    raise SystemExit(main())
