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
DIAGNOSTIC_STATE = Path("/tmp/tfg_demo.diagnostic.json")

LAUNCHES = {"tfg_demo.launch.py", "tfg_demo_2drones.launch.py"}


@dataclass(frozen=True)
class Process:
    pid: int
    ppid: int
    start_ticks: int
    argv: tuple[str, ...]
    tagged: bool = False
    zombie: bool = False
    diagnostic_selection_sha256: str | None = None

    @property
    def identity(self):
        return self.pid, self.start_ticks


def read_process(pid: int, proc_root=Path("/proc")) -> Process | None:
    try:
        directory = proc_root / str(pid)
        fields = (directory / "stat").read_text().rpartition(")")[2].split()
        argv = tuple(arg.decode(errors="replace") for arg in
                     (directory / "cmdline").read_bytes().split(b"\0") if arg)
        environment = (directory / "environ").read_bytes().split(b"\0")
        tagged = f"{MARKER}={PROJECT}".encode() in environment
        selection = None
        for item in environment:
            if item.startswith(b'TFG_DIAGNOSTIC_AGENT='):
                try:selection = diagnostic_api().digest(json.loads(item.split(b'=',1)[1]))
                except (ValueError,TypeError):pass
        return Process(pid, int(fields[1]), int(fields[19]), argv, tagged, fields[0] == "Z", selection)
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


def select_session_owned(table, selection_sha256, remembered=()):
    """Exact inherited descriptor or descendants of identities established here."""
    def compatible(p):return p.diagnostic_selection_sha256 in (None,selection_sha256)
    owned={pid:p for pid,p in table.items() if compatible(p) and (p.diagnostic_selection_sha256==selection_sha256 or p.identity in remembered)}
    while True:
        children={pid:p for pid,p in table.items() if p.ppid in owned and compatible(p)}
        added=children.keys()-owned.keys();owned.update(children)
        if not added:return owned


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
            and executable.startswith(("/opt/ros/humble/lib/", "/root/ardu_ws/install/", "/tmp/tfg_diagnostic_agents/"))
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
        diagnostic_monitor = name == 'monitor.py' and Path(executable).is_relative_to('/tmp/tfg_diagnostic_agents')
        if namespaced or sitl or rover_defaults or diagnostic_monitor:
            candidates.append(process)
    return candidates


def readonly_inventory(files=()):
    """Public metadata-only reuse of shutdown ownership rules; never cleans state."""
    table=snapshot(); owned=select_owned(table,remembered_identities())
    result={'boot_id':Path('/proc/sys/kernel/random/boot_id').read_text().strip(),
            'owned':[asdict(p) for p in owned.values()],
            'ambiguous':[asdict(p) for p in unattributed_auxiliaries(table,owned)],
            'agents':[asdict(p) for p in table.values() if not p.zombie and p.argv
                      and Path(p.argv[0]).name=='micro_ros_agent'],
            'state_files':{str(p):p.read_text() for p in (STATE,PID_FILE,DIAGNOSTIC_STATE) if p.exists()},
            'files':{}}
    for name in files:
        p=Path(name)
        if p.is_symlink() or not p.is_file() or p.stat().st_size>2097152:
            raise ValueError('Required inventory record absent/unsafe/too large')
        result['files'][name]=p.read_text()
    return result


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
    boot_fence = os.environ.get('TFG_DIAGNOSTIC_CLOSE_BOOT_ID')
    selection_fence = None
    if boot_fence:
        if Path('/proc/sys/kernel/random/boot_id').read_text().strip() != boot_fence:
            raise ValueError('Failed-start close boot changed; no signals')
        selection_fence = diagnostic_api().digest(json.loads(os.environ['TFG_DIAGNOSTIC_CLOSE_TARGET']))
    sent = []
    observed = {}
    errors = []
    # Diagnostic observers drain until vehicle/server cleanup finishes. Their
    # exit is then observed inside the SAME 12+5+3 second total cleanup budget.
    coordination=begin_diagnostic_closure(read=read)
    observers=coordination['observers'] if coordination else set()
    total_deadline=monotonic()+20.0

    def discover():
        table = scan()
        if selection_fence:
            # Exact inherited session descriptor, or descendants/identities first
            # established in THIS cleanup. Generic project tags are insufficient.
            owned = select_session_owned(table,selection_fence,scoped_remembered)
            scoped_remembered.update(p.identity for p in owned.values())
        else:owned = select_owned(table, remembered)
        observed.update({p.identity:asdict(p) for p in owned.values()})
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
        if selection_fence and (Path('/proc/sys/kernel/random/boot_id').read_text().strip()!=boot_fence
                or current.argv!=process.argv or current.diagnostic_selection_sha256!=process.diagnostic_selection_sha256):
            errors.append('Close process/session context changed; no signal')
            return
        try:
            send(process.pid, sig)
            sent.append({"pid": process.pid, "start_ticks": process.start_ticks, "signal": sig.name,
                         "process":asdict(current),"boot_id":boot_fence})
        except ProcessLookupError:
            pass
        except PermissionError as exc:
            errors.append(str(exc))

    scoped_remembered=set()
    for sig, grace in ((signal.SIGINT, 12.0), (signal.SIGTERM, 5.0), (signal.SIGKILL, 3.0)):
        table, owned = discover()
        infrastructure={pid:p for pid,p in owned.items() if p.identity not in observers}
        if not infrastructure:
            break
        protected = protected_pids(table)
        # Give all project supervisors a chance to shut their own children down.
        # Orphans (no live project ancestor) get SIGINT as well.
        roots = {pid: p for pid, p in infrastructure.items() if p.ppid not in infrastructure or is_project_launch(p)}
        targets = roots if sig == signal.SIGINT else infrastructure
        for process in targets.values():
            signal_one(process, sig, protected)
        deadline = min(total_deadline,monotonic() + grace)
        while monotonic() < deadline:
            _, owned = discover()
            if not any(p.identity not in observers for p in owned.values()):
                break
            sleep(0.25)
    if coordination:
        table,owned=discover()
        infrastructure=[p for p in owned.values() if p.identity not in observers]
        ambiguous=unattributed_auxiliaries(table,owned) if selection_fence else unattributed_auxiliaries(table,select_owned(table,remembered))
        finish_diagnostic_closure(coordination,success=not infrastructure and not errors and not ambiguous)
        while monotonic()<total_deadline:
            _,owned=discover()
            if not any(p.identity in observers for p in owned.values()):break
            sleep(0.1)
    final_table, remaining = discover()
    ambiguous = unattributed_auxiliaries(final_table, remaining) if selection_fence else unattributed_auxiliaries(final_table, select_owned(final_table, remembered))
    if selection_fence:
        # Other project sessions must never be signaled or cleared incidentally.
        ambiguous = list({p.pid:p for p in [*ambiguous,*select_owned(final_table,remembered).values()]
                          if p.pid not in remaining and not p.zombie}.values())
    if not remaining and not ambiguous:
        STATE.unlink(missing_ok=True)
        PID_FILE.unlink(missing_ok=True)
    return {"success": not remaining and not ambiguous and not errors, "signals": sent, "errors": errors,
            "diagnostic_coordination_errors":coordination['observer_errors'] if coordination else [],
            "unattributed_auxiliaries": [asdict(p) for p in ambiguous],
            "remaining": [asdict(p) for p in remaining.values()],
            "observed_processes":list(observed.values()),
            "diagnostic_agent": diagnostic_summary()}


def begin_diagnostic_closure(*,read=read_process):
    """Only the protected explicit close path; no historical-pointer inference."""
    raw=os.environ.get('TFG_DIAGNOSTIC_CLOSE_TARGET')
    if not raw:return None
    value=json.loads(raw);diagnostic_api().check_frozen_descriptor(value)
    if json.loads(DIAGNOSTIC_STATE.read_text())!={**value,'status':'BLOCKED','source_association_verified':False,'movement_authorized':False}:
        raise ValueError('Diagnostic close pointer differs')
    prefix=Path(value['prefix']);monitor=json.loads((prefix/'capture/monitor.json').read_text())
    if monitor.get('cleanup_protocol')!='DEFERRED_OBSERVER_SHUTDOWN_V1':return None
    parent=json.loads((prefix/'capture/monitor_supervisor.json').read_text())
    identities=[monitor['monitor']]
    observer_errors=[]
    if parent.get('supervisor'):identities.append(parent['supervisor'])
    else:observer_errors.append('Retained diagnostic parent identity unavailable')
    boot=Path('/proc/sys/kernel/random/boot_id').read_text().strip();current=read(os.getpid())
    if current is None or any(i['boot_id']!=boot for i in identities):raise ValueError('Closure owner/monitor identity unknown')
    observers=set()
    for i in identities:
        p=read(i['pid'])
        if p is None or p.start_ticks!=i['start_ticks'] or str(prefix/'monitor.py') not in p.argv:
            observer_errors.append('Diagnostic observer missing/changed before cleanup')
            continue
        observers.add(p.identity)
    payload={'lifecycle_id':value['lifecycle_id'],'selection_sha256':value['selection_sha256'],
        'cleanup_owner':{'pid':current.pid,'start_ticks':current.start_ticks,'boot_id':boot},
        'source':'PROTECTED_PROCESS_CLEANUP','observer_errors':observer_errors,
        'requested_at_utc':datetime.now(timezone.utc).isoformat()}
    target=prefix/'capture/closure-request.json'
    if target.exists():raise ValueError('Prior cleanup request exists; inspect without replay')
    diagnostic_api().atomic_record(target,payload)
    return {'prefix':prefix,'request':payload,'observers':observers,'observer_errors':observer_errors}


def finish_diagnostic_closure(value,*,success):
    diagnostic_api().atomic_record(value['prefix']/'capture/cleanup-finished.json',
        {**value['request'],'infrastructure_cleanup_complete':success,
         'finished_at_utc':datetime.now(timezone.utc).isoformat()})


def diagnostic_api():
    try:
        from tools.rover_xrce_trace import selection
    except ModuleNotFoundError as exc:
        if exc.name not in {'tools','tools.rover_xrce_trace'}: raise
        import tfg_diagnostic_agent as selection
    return selection


def diagnostic_summary():
    if not DIAGNOSTIC_STATE.exists(): return None
    try:
        pointer=json.loads(DIAGNOSTIC_STATE.read_text())
        prefix=Path(pointer['prefix'])
        return {'selection':pointer,'monitor':json.loads((prefix/'capture/monitor.json').read_text()),
                'monitor_exit':json.loads((prefix/'capture/monitor_exit.json').read_text()) if (prefix/'capture/monitor_exit.json').exists() else
                    {'state':'UNKNOWN','return_code':None,'reason':'NO_PARENT_WAIT_STATUS_AVAILABLE'},
                'monitor_supervisor':json.loads((prefix/'capture/monitor_supervisor.json').read_text()) if (prefix/'capture/monitor_supervisor.json').exists() else
                    {'phase':'UNKNOWN','reason':'NO_RETAINED_PARENT_RECORD'},
                'scope':'LAST_DIAGNOSTIC_SESSION_NOT_A_RESERVATION_OR_IDENTITY_APPROVAL'}
    except (OSError,ValueError,KeyError) as exc:
        return {'capture_complete':False,'error':str(exc),'status':'BLOCKED'}


def record_monitor_exit(child, return_code, prefix, identity):
    """Only actual Popen parent wait status; never inferred from a receipt/PID absence.

    Once this short-lived supervisor exits there is no retained wait handle;
    subsequent summaries explicitly report UNKNOWN unless this record exists.
    """
    if child.pid!=identity.pid or type(return_code) is not int:
        raise ValueError('Monitor wait identity/status mismatch')
    # A retained monitor parent may already have recorded its child's real rc.
    # This startup poll concerns the parent; do not overwrite the child's record.
    retained_parent=('--supervise' in getattr(child,'args',()) or '--supervise' in getattr(identity,'argv',()))
    path=prefix/('capture/monitor_supervisor_exit.json' if retained_parent or (prefix/'capture/monitor_exit.json').exists()
                 else 'capture/monitor_exit.json')
    diagnostic_api().atomic_record(path,
        {'state':'PARENT_WAIT_STATUS_OBSERVED','return_code':return_code,
         'pid':identity.pid,'start_ticks':identity.start_ticks,
         'observed_monotonic':time.monotonic(),'observed_at_utc':datetime.now(timezone.utc).isoformat(),
         'source':'SUPERVISOR_POPEN_POLL_NOT_MONITOR_RECEIPT'})


def verify_start_log():
    """Read only this launch's bounded log; fail closed on acquisition errors.

    This is a late guard, not a promise that project locks exclude foreign binds.
    """
    with LOG_FILE.open('rb') as stream:data=stream.read(2*1024*1024+1)
    if len(data)>2*1024*1024:raise RuntimeError('Startup log coverage budget exceeded')
    import re
    if re.search(rb'address already in use|eaddrinuse|(?:bind|binding)[^\r\n]{0,80}(?:fail|error)|(?:fail|unable)[^\r\n]{0,80}bind',data,re.I):
        raise RuntimeError('Startup resource acquisition/bind failure reported; no automatic retry')
    return {'success':True,'scope':'CURRENT_LAUNCH_LOG_ACQUISITION_ERRORS_ONLY'}


def verify_acquisition():
    """At readiness, require actual fixed endpoints owned by this launch tree."""
    import sys
    sys.path.insert(0,'/workspace/tfg')
    from tools.rover_xrce_trace import present_resources as resources
    result={'success':False,'scope':'FIXED_ENDPOINTS_ACQUIRED_BY_CURRENT_PROJECT_TREE',
            'observed_at_utc':datetime.now(timezone.utc).isoformat(),
            'resource_observation':None,'decision':None}
    try:
        verify_start_log()
        config=resources.read_config()
        scope=resources.scope(INSTALLED_ROVER_LAUNCH.read_text(),config)
        table=snapshot()
        if os.environ.get('TFG_DIAGNOSTIC_AGENT'):
            selected=json.loads(os.environ['TFG_DIAGNOSTIC_AGENT'])
            diagnostic_api().check_frozen_descriptor(selected)
            pointer=json.loads(DIAGNOSTIC_STATE.read_text())
            if pointer!={**selected,'status':'BLOCKED','source_association_verified':False,'movement_authorized':False}:
                raise ValueError('Acquisition diagnostic pointer/session differs')
            sha=diagnostic_api().digest(selected)
            owned=select_session_owned(table,sha)
            result['ownership_context']={'lifecycle_id':selected['lifecycle_id'],
                                         'descriptor_sha256':sha,'basis':'EXACT_SESSION_AND_DESCENDANTS'}
        else:owned=select_owned(table,remembered_identities())
        result['known_processes']=[{'pid':p.pid,'start_ticks':p.start_ticks} for p in owned.values()]
        observation=resources.collect(scope,known_processes={p.identity for p in owned.values()})
        result['resource_observation']=observation
        result['resource_serialized_bytes']=len(json.dumps(observation).encode())
        result['resource_byte_limit']=resources.s.MAX_BYTES
        result['decision']=resources.acquisition_decision(observation)
        resources.require_acquired(observation)
        result['success']=True
    except Exception as exc:
        result['error']=type(exc).__name__+': '+str(exc)
    return result


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
    diagnostic = None
    if environment.get('TFG_DIAGNOSTIC_AGENT'):
        if selected.name != 'two_drones_rover':raise ValueError('Diagnostic selection/profile mismatch')
        environment, diagnostic = diagnostic_api().configure(environment)
    else:
        environment.pop('TFG_XRCE_TRACE',None)
    # Background shell/nohup SIGINT inheritance must not disable graceful shutdown.
    signal.signal(signal.SIGINT, signal.SIG_DFL)
    watcher = None
    with LOG_FILE.open("wb") as log:
        if diagnostic:
            prefix=Path(diagnostic['prefix'])
            diagnostic_api().atomic_record(DIAGNOSTIC_STATE,diagnostic)
            with (prefix/'capture/supervisor.log').open('xb') as watcher_log:
                watcher=subprocess.Popen(['/usr/bin/python3',str(prefix/'monitor.py'),'--supervise',str(prefix)],
                    env=environment,cwd='/',start_new_session=True,stdin=subprocess.DEVNULL,
                    stdout=watcher_log,stderr=subprocess.STDOUT)
            observed_watcher=read_process(watcher.pid)
            if observed_watcher is None:raise RuntimeError('Diagnostic monitor disappeared before launch')
            save_state({observed_watcher.identity})
        child = subprocess.Popen(
            ["ros2", "launch", selected.launch_package, selected.launch_file,
             *selected.fixed_launch_arguments, "gui:=" + ("false" if os.environ.get("TFG_SIM_GUI") == "false" else "true")],
            env=environment, cwd="/", start_new_session=True, stdin=subprocess.DEVNULL,
            stdout=log, stderr=subprocess.STDOUT,
        )
    process = read_process(child.pid)
    if process is None:
        raise RuntimeError("Launch exited before its identity could be saved; inspect /tmp/tfg_demo.log")
    if diagnostic:
        diagnostic_api().atomic_record(Path(diagnostic['prefix'])/'launch.json',
            {'process':{'pid':process.pid,'start_ticks':process.start_ticks,
                        'boot_id':Path('/proc/sys/kernel/random/boot_id').read_text().strip()}})
    save_state({process.identity} | ({observed_watcher.identity} if watcher else set()))
    PID_FILE.write_text(str(child.pid))  # compatibility only; never used to select a victim
    rover_identity = start_rover_identity(process, environment) if selected.name == "two_drones_rover" else None
    if diagnostic:
        deadline=time.monotonic()+10
        while time.monotonic()<deadline:
            verify_start_log()
            report=diagnostic_summary()
            monitor_rc=watcher.poll()
            if monitor_rc is not None:
                record_monitor_exit(watcher,monitor_rc,Path(diagnostic['prefix']),observed_watcher)
            if monitor_rc is not None or report and report.get('monitor',{}).get('phase') in {'FAILED','INCOMPLETE'}:
                raise RuntimeError('Diagnostic monitor/agent startup failed; inspect retained evidence')
            if report and report.get('monitor',{}).get('phase')=='OBSERVING':break
            time.sleep(.1)
        else:raise RuntimeError('Diagnostic agent/library identity not confirmed; no retry')
    return {"success": True, "pid": child.pid, "start_ticks": process.start_ticks,
            "log_path": str(LOG_FILE), "rover_identity_worker": rover_identity,
            "diagnostic_agent": diagnostic_summary() if diagnostic else None}



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
    save_state(remembered_identities() | {launch_process.identity, identity.identity})
    return {'pid': identity.pid, 'start_ticks': identity.start_ticks,
            'context_path': str(context_path), 'record_path': str(root/'worker.json'),
            'log_path': str(root/'worker.log'), 'scope': 'READ_ONLY_IDENTITY_NOT_MOVEMENT'}

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("start", "stop", "verify-start", "verify-acquisition"))
    parser.add_argument("--profile", default=os.environ.get("TFG_SIM_PROFILE", "two_drones"))
    args = parser.parse_args()
    try:
        selected = get_profile(args.profile)
        result = verify_acquisition() if args.action=="verify-acquisition" else verify_start_log() if args.action=="verify-start" else start(selected.name) if args.action == "start" else shutdown()
    except Exception as exc:
        result = {"success": False, "error": f"{type(exc).__name__}: {exc}"}
    print(json.dumps(result))
    return 0 if result["success"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
