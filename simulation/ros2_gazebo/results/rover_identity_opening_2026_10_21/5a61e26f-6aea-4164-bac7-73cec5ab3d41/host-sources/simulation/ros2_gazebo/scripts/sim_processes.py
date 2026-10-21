#!/usr/bin/env python3
"""Container-side ownership and bounded shutdown of this project's launch tree.

Standard library only. No substring pkill, no process-group-wide signals, and no
trust in a PID file without a process identity. Imported by offline tests.
"""
from __future__ import annotations

import argparse
import hashlib
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import signal
import subprocess
import time
from uuid import UUID, uuid4

try:
    from tools.simulation_profiles import get_profile
except ModuleNotFoundError as exc:
    if exc.name not in {"tools", "tools.simulation_profiles"}:
        raise
    # Copied next to this standalone helper by the protected backend.
    from tfg_simulation_profiles import get_profile

PROJECT = "Agentic_Drone_Mission_Control"
MARKER = "TFG_SIM_PROJECT"
STATE = Path("/tmp/tfg_demo.processes.json")
PID_FILE = Path("/tmp/tfg_demo.pid")
LOG_FILE = Path("/tmp/tfg_demo.log")
ROVER_IDENTITY_ROOT = Path('/tmp/tfg_rover_identity')
INSTALLED_ROVER_LAUNCH = Path('/root/ardu_ws/install/ardupilot_gz_bringup/share/ardupilot_gz_bringup/launch/tfg_demo.launch.py')
LAUNCHES = {"tfg_demo.launch.py", "tfg_demo_2drones.launch.py"}


@dataclass(frozen=True)
class Process:
    pid: int
    ppid: int
    start_ticks: int
    argv: tuple[str, ...]
    tagged: bool = False
    zombie: bool = False

    @property
    def identity(self):
        return self.pid, self.start_ticks


def read_process(pid: int, proc_root=Path("/proc")) -> Process | None:
    try:
        directory = proc_root / str(pid)
        fields = (directory / "stat").read_text().rpartition(")")[2].split()
        argv = tuple(arg.decode(errors="replace") for arg in
                     (directory / "cmdline").read_bytes().split(b"\0") if arg)
        tagged = f"{MARKER}={PROJECT}".encode() in (directory / "environ").read_bytes().split(b"\0")
        return Process(pid, int(fields[1]), int(fields[19]), argv, tagged, fields[0] == "Z")
    except (FileNotFoundError, ProcessLookupError):
        return None


def snapshot() -> dict[int, Process]:
    return {p.pid: p for entry in Path("/proc").iterdir() if entry.name.isdigit()
            if (p := read_process(int(entry.name))) is not None}


def is_project_launch(process: Process) -> bool:
    args = process.argv
    # Exact argv tokens; a bash -c string or a different launch is never a root.
    offset = 1 if args and Path(args[0]).name.startswith("python") else 0
    return (len(args) >= offset + 4 and Path(args[offset]).name == "ros2"
            and args[offset + 1] == "launch" and args[offset + 2] == "ardupilot_gz_bringup"
            and args[offset + 3] in LAUNCHES)


def select_owned(table: dict[int, Process], remembered: set[tuple[int, int]]) -> dict[int, Process]:
    owned = {pid: p for pid, p in table.items()
             if p.tagged or is_project_launch(p) or p.identity in remembered}
    # Include every descendant, including shells, bridges, TF relays, spawn/create,
    # RSP, Gazebo GUI/server wrappers, SITL, MAVProxy and the micro-ROS agent.
    while True:
        children = {pid: p for pid, p in table.items() if p.ppid in owned}
        added = children.keys() - owned.keys()
        owned.update(children)
        if not added:
            return owned


def unattributed_auxiliaries(table, owned):
    """Conservative blockers, never targets: legacy orphans lack ownership proof.

    Only exact ROS namespaces/known SITL defaults identify these candidates;
    an executable name alone does not establish that it belongs to this project.
    """
    candidates = []
    for pid, process in table.items():
        if pid in owned or process.zombie or not process.argv:
            continue
        args = process.argv
        offset = 1 if Path(args[0]).name.startswith("python") and len(args) > 1 else 0
        executable = args[offset]
        name = Path(executable).name
        namespaced = (
            name in {"parameter_bridge", "robot_state_publisher", "relay", "create", "rviz2", "micro_ros_agent"}
            and executable.startswith(("/opt/ros/humble/lib/", "/root/ardu_ws/install/"))
            and any(arg in {"__ns:=/drone1", "__ns:=/drone2", "__ns:=/rover1"} for arg in args)
        )
        sitl = name in {"arducopter", "ardurover"} and any(
            "/root/ardu_ws/install/ardupilot_gazebo/share/ardupilot_gazebo/config/" in arg for arg in args
        )
        rover_defaults = name == "ardurover" and any(
            item.endswith("/ardupilot_sitl/config/default_params/" + default)
            for arg in args for item in arg.split(",")
            for default in ("rover.parm", "rover-skid.parm")
        )
        if namespaced or sitl or rover_defaults:
            candidates.append(process)
    return candidates


def protected_pids(table: dict[int, Process]) -> set[int]:
    protected = {1, os.getpid()}
    current = os.getpid()
    while current in table and table[current].ppid not in protected:
        current = table[current].ppid
        protected.add(current)
    return protected


def save_state(identities: set[tuple[int, int]]) -> None:
    temporary = STATE.with_suffix(".tmp")
    temporary.write_text(json.dumps({"project": PROJECT, "identities": sorted(identities)}))
    temporary.replace(STATE)


def remembered_identities() -> set[tuple[int, int]]:
    if not STATE.exists():
        return set()
    data = json.loads(STATE.read_text())
    if data.get("project") != PROJECT:
        raise ValueError("Process state belongs to another project")
    return {tuple(identity) for identity in data["identities"]}


def shutdown(*, scan=snapshot, send=os.kill, read=read_process,
             monotonic=time.monotonic, sleep=time.sleep) -> dict:
    remembered = remembered_identities()
    sent = []
    errors = []

    def discover():
        table = scan()
        owned = select_owned(table, remembered)
        remembered.update(p.identity for p in owned.values())
        # Retain ownership across parent exit, reparenting, or interrupted cleanup.
        save_state(remembered)
        return table, {pid: p for pid, p in owned.items() if not p.zombie}

    def signal_one(process, sig, protected):
        if process.pid in protected:
            errors.append(f"Refusing to signal own shell/ancestor PID {process.pid}")
            return
        current = read(process.pid)
        if current is None or current.identity != process.identity:
            return  # PID exited or was reused; never signal its replacement.
        try:
            send(process.pid, sig)
            sent.append({"pid": process.pid, "start_ticks": process.start_ticks, "signal": sig.name})
        except ProcessLookupError:
            pass
        except PermissionError as exc:
            errors.append(str(exc))

    for sig, grace in ((signal.SIGINT, 12.0), (signal.SIGTERM, 5.0), (signal.SIGKILL, 3.0)):
        table, owned = discover()
        if not owned:
            break
        protected = protected_pids(table)
        # Give all project supervisors a chance to shut their own children down.
        # Orphans (no live project ancestor) get SIGINT as well.
        roots = {pid: p for pid, p in owned.items() if p.ppid not in owned or is_project_launch(p)}
        targets = roots if sig == signal.SIGINT else owned
        for process in targets.values():
            signal_one(process, sig, protected)
        deadline = monotonic() + grace
        while monotonic() < deadline:
            _, owned = discover()
            if not owned:
                break
            sleep(0.25)
    final_table, remaining = discover()
    ambiguous = unattributed_auxiliaries(final_table, select_owned(final_table, remembered))
    if not remaining and not ambiguous:
        STATE.unlink(missing_ok=True)
        PID_FILE.unlink(missing_ok=True)
    return {"success": not remaining and not ambiguous and not errors, "signals": sent, "errors": errors,
            "unattributed_auxiliaries": [asdict(p) for p in ambiguous],
            "remaining": [asdict(p) for p in remaining.values()]}


def start(profile="two_drones") -> dict:
    selected = get_profile(profile)
    table = snapshot()
    owned = select_owned(table, remembered_identities())
    if owned or unattributed_auxiliaries(table, owned):
        raise RuntimeError("Project processes remain; refusing a second launch")
    if LOG_FILE.exists():
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
        LOG_FILE.rename(LOG_FILE.with_name(f"tfg_demo.{timestamp}.{uuid4().hex[:8]}.log"))
    environment = {**os.environ, MARKER: PROJECT}
    # Background shell/nohup SIGINT inheritance must not disable graceful shutdown.
    signal.signal(signal.SIGINT, signal.SIG_DFL)
    with LOG_FILE.open("wb") as log:
        child = subprocess.Popen(
            ["ros2", "launch", selected.launch_package, selected.launch_file,
             *selected.fixed_launch_arguments, "gui:=" + ("false" if os.environ.get("TFG_SIM_GUI") == "false" else "true")],
            env=environment, cwd="/", start_new_session=True, stdin=subprocess.DEVNULL,
            stdout=log, stderr=subprocess.STDOUT,
        )
    process = read_process(child.pid)
    if process is None:
        raise RuntimeError("Launch exited before its identity could be saved; inspect /tmp/tfg_demo.log")
    save_state({process.identity})
    PID_FILE.write_text(str(child.pid))  # compatibility only; never used to select a victim
    rover_identity = start_rover_identity(process, environment) if selected.name == "two_drones_rover" else None
    return {"success": True, "pid": child.pid, "start_ticks": process.start_ticks,
            "log_path": str(LOG_FILE), "rover_identity_worker": rover_identity}



def start_rover_identity(launch_process, environment):
    """Start ONE passive child. It owns no execution reservation or command API."""
    try:
        from tools.rover_identity_worker import publish_record
    except ModuleNotFoundError as exc:
        if exc.name not in {"tools", "tools.rover_identity_worker"}:
            raise
        from tfg_rover_identity_worker import publish_record
    context = json.loads(environment.get("TFG_SIM_START_CONTEXT", "{}"))
    identifier = context["lifecycle_id"]
    if str(UUID(identifier)) != identifier or context["profile"] != "two_drones_rover":
        raise ValueError("Wrong protected lifecycle/profile context")
    installed = INSTALLED_ROVER_LAUNCH
    if hashlib.sha256(installed.read_bytes()).hexdigest() != context['launch_sha256']:
        raise ValueError('Installed launch differs from protected host launch')
    root = ROVER_IDENTITY_ROOT / identifier
    root.mkdir(parents=True, exist_ok=False)  # never overwrite/restart a previous worker
    context.update(vehicle_id='rover_01', interface='v3', namespace='/rover1',
                   launch_process={'pid': launch_process.pid, 'start_ticks': launch_process.start_ticks,
                                   'boot_id': Path('/proc/sys/kernel/random/boot_id').read_text().strip()})
    context_path = root/'context.json'
    publish_record(context_path, context)
    with (root/'worker.log').open('xb') as log:
        worker = subprocess.Popen(['python3', '/tmp/tfg_rover_identity_worker.py', '--context', str(context_path)],
            env=environment, cwd='/', start_new_session=True, stdin=subprocess.DEVNULL,
            stdout=log, stderr=subprocess.STDOUT)
    identity = read_process(worker.pid)
    if identity is None:
        raise RuntimeError('Passive worker disappeared at start; no automatic restart')
    save_state({launch_process.identity, identity.identity})
    return {'pid': identity.pid, 'start_ticks': identity.start_ticks,
            'context_path': str(context_path), 'record_path': str(root/'worker.json'),
            'log_path': str(root/'worker.log'), 'scope': 'READ_ONLY_IDENTITY_NOT_MOVEMENT'}

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("start", "stop"))
    parser.add_argument("--profile", default=os.environ.get("TFG_SIM_PROFILE", "two_drones"))
    args = parser.parse_args()
    try:
        selected = get_profile(args.profile)
        result = start(selected.name) if args.action == "start" else shutdown()
    except Exception as exc:
        result = {"success": False, "error": f"{type(exc).__name__}: {exc}"}
    print(json.dumps(result))
    return 0 if result["success"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
