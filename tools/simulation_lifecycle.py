"""One atomic simulator lifecycle transaction, shared with all flight admissions.

Only explicit calls run this module. A crash/timeout retains a durable restriction.
The backend scripts require a live inherited lease; no environment-only bypass.
"""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
from uuid import uuid4

from tools import vehicle_execution_lock as locks

SCRIPTS = locks.PROJECT_ROOT / "simulation/ros2_gazebo/scripts"


def verify_backend():
    lease = json.loads((locks.LOCK_ROOT / "lifecycle.json").read_text())
    expected = json.loads(os.environ["TFG_LIFECYCLE_PROCESS"])
    # Python verifier <- shell backend <- owning Python lifecycle process.
    fields = Path(f"/proc/{os.getppid()}/stat").read_text().rpartition(")")[2].split()
    descriptor = int(os.environ["TFG_LIFECYCLE_FD"])
    metadata = os.fstat(descriptor)
    registry = (locks.LOCK_ROOT / "registry.lock").stat()
    if (lease.get("process") != expected or not locks.identity_alive(expected)
            or int(fields[1]) != expected["pid"]
            or (metadata.st_dev, metadata.st_ino) != (registry.st_dev, registry.st_ino)):
        raise locks.VehicleBusy("Missing live lifecycle owner/registry descriptor")
    import fcntl
    fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)


def _backend(action, gui, descriptor, process, log_path):
    env = {**os.environ, "TFG_LIFECYCLE_PROCESS": json.dumps(process),
           "TFG_LIFECYCLE_FD": str(descriptor), "TFG_SIM_GUI": "true" if gui else "false"}
    with log_path.open("ab") as log:
        return subprocess.run(["bash", str(SCRIPTS / f"{action}_sim_backend.sh")],
                              cwd=locks.PROJECT_ROOT, env=env, pass_fds=(descriptor,),
                              stdout=log, stderr=subprocess.STDOUT,
                              timeout=180 if action == "start" else 60, check=False).returncode


def run_lifecycle(action, *, gui=True):
    if action not in {"start", "stop", "restart"} or type(gui) is not bool:
        return {"success": False, "status": "ERROR", "message": "Invalid action or GUI mode"}
    try:
        # Same order as executor/reconciliation. Even a damaged/missing durable
        # reservation cannot let lifecycle disrupt a still-running OS executor.
        with (locks.file_mutex(locks.LOCK_ROOT / "v1.execution.lock", blocking=False),
              locks.file_mutex(locks.LOCK_ROOT / "registry.lock", blocking=False) as registry):
            if locks.restriction() is not None:
                raise locks.VehicleBusy("Flight/lifecycle/reconciliation restriction remains; no simulator recovery")
            owner_id = str(uuid4())
            root = locks.LOCK_ROOT.parent / "simulation_lifecycle" / owner_id
            root.mkdir(parents=True)
            record = {"kind": "SIMULATION_LIFECYCLE", "owner_id": owner_id,
                      "state": "EXECUTING", "action": action, "gui": gui,
                      "process": locks.process_identity(), "started_at": locks.utc_now(),
                      "log_path": str(root / "backend.log")}
            locks.atomic_json(locks.LOCK_ROOT / "lifecycle.json", record)
            locks.atomic_json(root / "operation.json", record)
            try:
                for step in (["stop", "start"] if action == "restart" else [action]):
                    code = _backend(step, gui, registry.fileno(), record["process"], root/"backend.log")
                    if code != 0:
                        raise RuntimeError(f"{step} backend returned {code}; inspect before another lifecycle")
                final = {**record, "state": "FINISHED", "finished_at": locks.utc_now()}
                locks.atomic_json(root / "operation.json", final)
                (locks.LOCK_ROOT / "lifecycle.json").unlink()
                return {"success": True, "status": "SUCCESS", "operation": final,
                        "visual_confirmation": "OPERATOR_REQUIRED" if gui and action != "stop" else "NOT_REQUESTED"}
            except BaseException as exc:
                uncertain = {**record, "state": "UNCONFIRMED", "error": f"{type(exc).__name__}: {exc}"}
                locks.atomic_json(locks.LOCK_ROOT / "lifecycle.json", uncertain)
                locks.atomic_json(root / "operation.json", uncertain)
                if not isinstance(exc, Exception):
                    raise
                return {"success": False, "status": "UNCONFIRMED", "operation": uncertain}
    except (locks.VehicleBusy, OSError, ValueError) as exc:
        return {"success": False, "status": "BLOCKED", "message": str(exc)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("start", "stop", "restart", "verify"))
    parser.add_argument("--headless", action="store_true")
    args = parser.parse_args()
    if args.action == "verify":
        verify_backend()
        return 0
    result = run_lifecycle(args.action, gui=not args.headless)
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result["success"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
