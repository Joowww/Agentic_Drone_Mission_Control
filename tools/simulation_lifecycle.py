"""One atomic simulator lifecycle transaction, shared with all flight admissions.

Only explicit calls run this module. A crash/timeout retains a durable restriction.
The backend scripts require a live inherited lease; no environment-only bypass.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import stat
import sys
import threading
import time
from uuid import UUID, uuid4

from tools import vehicle_execution_lock as locks
from tools.simulation_profiles import get_profile, UnknownSimulationProfile

SCRIPTS = locks.PROJECT_ROOT / "simulation/ros2_gazebo/scripts"


def verify_backend():
    lease = json.loads((locks.LOCK_ROOT / "lifecycle.json").read_text())
    expected = json.loads(os.environ["TFG_LIFECYCLE_PROCESS"])
    selected = get_profile(os.environ.get("TFG_SIM_PROFILE", "two_drones"))
    if lease.get("profile") != selected.name:
        raise locks.VehicleBusy("Lifecycle/profile mismatch")
    diagnostic = json.loads(os.environ['TFG_DIAGNOSTIC_AGENT']) if os.environ.get('TFG_DIAGNOSTIC_AGENT') else None
    if diagnostic != lease.get('diagnostic_agent'):
        raise locks.VehicleBusy('Lifecycle/diagnostic selection mismatch')
    closing = json.loads(os.environ['TFG_DIAGNOSTIC_CLOSE_TARGET']) if os.environ.get('TFG_DIAGNOSTIC_CLOSE_TARGET') else None
    if closing != lease.get('diagnostic_close_target'):
        raise locks.VehicleBusy('Lifecycle/diagnostic close identity mismatch')
    expected_boot = lease.get('environment_execution', {}).get('container_boot_id') if lease.get('closing_failed_start') or lease.get('closing_ground_trial') or lease.get('closing_passive_session') or lease.get('closing_diagnostic_session') else None
    if os.environ.get('TFG_DIAGNOSTIC_CLOSE_BOOT_ID') != expected_boot:
        raise locks.VehicleBusy('Failed-start close boot fence mismatch')
    expected_passive=lease.get('passive_session_id') if lease.get('passive_session_id') else (lease.get('closing_passive_session') or {}).get('session_id')
    if os.environ.get('TFG_PASSIVE_SESSION_ID') != expected_passive:
        raise locks.VehicleBusy('Passive lifecycle session fence mismatch')
    expected_passive_boot=(lease.get('environment_execution') or {}).get('container_boot_id') if expected_passive else None
    if os.environ.get('TFG_PASSIVE_SESSION_BOOT_ID') != expected_passive_boot:
        raise locks.VehicleBusy('Passive lifecycle boot fence mismatch')
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
    if lease.get('environment_execution') is not None:
        assert_environment_execution(lease['environment_execution'])


def assert_environment_execution(expected):
    """Current-operation fence; never compares against a historical session PID."""
    from tools.reconciliation_environment import inspect_active_execution
    try:
        current=inspect_active_execution()
    except (OSError,ValueError,KeyError,TypeError,subprocess.SubprocessError) as exc:
        from tools.reconciliation_environment import ActiveExecutionReadError
        detail=(exc.diagnostic if isinstance(exc,ActiveExecutionReadError) else
                {'operation':'inspect_active_execution','source':'execution_reader',
                 'field':'observation','reason':'READ_FAILED_'+type(exc).__name__})
        failure=locks.VehicleBusy('Active lifecycle execution read failed: '+json.dumps(detail,separators=(',',':')))
        failure.diagnostic=detail
        raise failure from None  # untrusted exception text may contain raw transport data
    if not isinstance(expected,dict) or current!=expected:
        failure=locks.VehicleBusy('Active lifecycle container execution changed/unknown')
        failure.diagnostic={'operation':'compare_active_execution','source':'execution_reference',
                            'field':'environment_execution','reason':'CHANGED_OR_UNKNOWN'}
        raise failure


def _backend(action, gui, descriptor, process, log_path):
    selected = get_profile(json.loads((locks.LOCK_ROOT / "lifecycle.json").read_text())["profile"])
    lease = json.loads((locks.LOCK_ROOT / "lifecycle.json").read_text())
    clean = {k:v for k,v in os.environ.items() if k not in {'TFG_DIAGNOSTIC_AGENT','TFG_XRCE_TRACE','TFG_DIAGNOSTIC_CLOSE_TARGET','TFG_DIAGNOSTIC_CLOSE_BOOT_ID','TFG_PASSIVE_SESSION_ID','TFG_PASSIVE_SESSION_BOOT_ID'}}
    env = {**clean, "TFG_SIM_PROFILE": selected.name, "TFG_LIFECYCLE_PROCESS": json.dumps(process),
           "TFG_LIFECYCLE_FD": str(descriptor), "TFG_SIM_GUI": "true" if gui else "false",
           "TFG_LIFECYCLE_RESULT_DIR": str(log_path.parent)}
    if action == "start" and selected.name in {"two_drones_rover", "rover_only"}:
        # Bounded metadata reads, under the existing lifecycle exclusion. A failed
        # identity read cannot be replaced by a container name or a guessed ID.
        from tools.reconciliation_environment import inspect_environment
        observed = inspect_environment()
        if observed.get("status") not in {"ACTIVE", "STOPPED"}:
            raise locks.VehicleBusy("Rover identity bootstrap: environment metadata unavailable or ambiguous")
        lease = json.loads((locks.LOCK_ROOT / "lifecycle.json").read_text())
        identity = {key: observed[key] for key in ("engine_id", "container_id", "name", "created_at", "image_id")}
        context = {"lifecycle_id": lease["owner_id"], "profile": selected.name,
                   "environment": identity, "pre_start_state": observed["state"],
                   "launch_sha256": hashlib.sha256((SCRIPTS.parent/"launch"/selected.launch_file).read_bytes()).hexdigest()}
        locks.atomic_json(log_path.parent / "rover_environment_reference.json", context)
        env["TFG_SIM_START_CONTEXT"] = json.dumps(context)
        if action == 'start' and lease.get('diagnostic_agent'):
            from tools.rover_xrce_trace.selection import check_descriptor
            diagnostic = check_descriptor(lease['diagnostic_agent'])
            manifest = diagnostic['manifest']
            if (observed.get('status') != 'ACTIVE' or any(observed.get(k)!=manifest[k]
                    for k in ('engine_id','container_id','image_id'))):
                raise locks.VehicleBusy('Diagnostic agent requires the exact already-active environment')
            env['TFG_DIAGNOSTIC_AGENT'] = json.dumps(diagnostic)
    if lease.get('passive_session_id'):
        env['TFG_PASSIVE_SESSION_ID']=lease['passive_session_id']
        env['TFG_PASSIVE_SESSION_BOOT_ID']=lease['environment_execution']['container_boot_id']
    if action == 'stop' and lease.get('closing_passive_session'):
        env['TFG_PASSIVE_SESSION_ID']=lease['closing_passive_session']['session_id']
        env['TFG_PASSIVE_SESSION_BOOT_ID']=lease['environment_execution']['container_boot_id']
        env['TFG_DIAGNOSTIC_CLOSE_BOOT_ID'] = lease['environment_execution']['container_boot_id']
    if action == 'stop' and lease.get('diagnostic_close_target'):
        from tools.reconciliation_environment import inspect_environment
        from tools.rover_xrce_trace.selection import check_frozen_descriptor
        closing = check_frozen_descriptor(lease['diagnostic_close_target'])
        observed = inspect_environment()
        if observed.get('status') not in {'ACTIVE','STOPPED'} or any(
                observed.get(k)!=closing['manifest'][k] for k in ('engine_id','container_id','image_id')):
            raise locks.VehicleBusy('Diagnostic stop environment changed/unknown; no retargeting')
        env['TFG_DIAGNOSTIC_CLOSE_TARGET'] = json.dumps(closing)
        if lease.get('closing_failed_start') or lease.get('closing_ground_trial') or lease.get('closing_diagnostic_session'):
            env['TFG_DIAGNOSTIC_CLOSE_BOOT_ID'] = lease['environment_execution']['container_boot_id']
    if action == 'stop':
        # The pinned process reader selects exactly one session only with descriptor AND boot; a descriptor without
        # its boot degrades to the general project selection. Refuse it here, before any subprocess.
        if env.get('TFG_DIAGNOSTIC_CLOSE_TARGET') and not env.get('TFG_DIAGNOSTIC_CLOSE_BOOT_ID'):
            raise locks.VehicleBusy('Diagnostic close descriptor without its exact boot fence; no general selection')
        if env.get('TFG_PASSIVE_SESSION_ID') and env.get('TFG_DIAGNOSTIC_CLOSE_TARGET'):
            raise locks.VehicleBusy('Passive and diagnostic close are exclusive; ambiguous STOP owner')
    with log_path.open("ab") as log:
        return subprocess.run(["bash", str(SCRIPTS / f"{action}_sim_backend.sh")],
                              cwd=locks.PROJECT_ROOT, env=env, pass_fds=(descriptor,),
                              stdout=log, stderr=subprocess.STDOUT,
                              timeout=180 if action == "start" else 60, check=False).returncode


def failed_start_close(owner, action, selected, target, barrier):
    """Under both mutexes: replace only this failed start with its closing lease."""
    if (action != 'stop' or str(UUID(owner)) != owner or not target
            or target.get('state') != 'UNCONFIRMED' or not isinstance(barrier, dict)
            or barrier.get('kind') != 'SIMULATION_LIFECYCLE'
            or barrier.get('state') != 'UNCONFIRMED' or barrier.get('action') != 'start'
            or barrier.get('owner_id') != owner or barrier.get('profile') != selected.name
            or target['descriptor']['lifecycle_id'] != owner
            or barrier.get('diagnostic_agent') != target['descriptor']):
        raise locks.VehicleBusy('Failed-start close owner/profile/descriptor mismatch')
    original = locks.LOCK_ROOT.parent/'simulation_lifecycle'/owner/'operation.json'
    if (target.get('operation_path') != str(original)
            or json.loads(original.read_text()) != barrier
            or json.loads((locks.LOCK_ROOT/'lifecycle.json').read_text()) != barrier
            or locks.identity_alive(barrier.get('process'))):
        raise locks.VehicleBusy('Failed-start original changed or owner still alive')
    if ((locks.LOCK_ROOT/'reconciliation.json').exists()
            or any(locks.restriction(v) is not None for v in locks.RESERVATION_INTERFACES)
            or locks.sequence_restriction() is not None):
        raise locks.VehicleBusy('Other reservation/restriction prevents failed-start close')
    reference = barrier.get('environment_execution')
    assert_environment_execution(reference)
    return reference


def ground_close_reference(job):
    """Called under the existing worker exclusion, before any pulse controls."""
    from tools.rover_xrce_trace.selection import check_frozen_descriptor
    target=json.loads((locks.LOCK_ROOT.parent/'diagnostic_agent_session.json').read_text())
    descriptor=target['descriptor'];check_frozen_descriptor(descriptor)
    original=json.loads(Path(target['operation_path']).read_text())
    if (target['state'] not in {'STARTED','UNCONFIRMED'} or descriptor['lifecycle_id']!=job['session_id']
            or original.get('action')!='start' or original.get('owner_id')!=job['session_id']
            or original.get('diagnostic_agent')!=descriptor or original.get('profile')!='two_drones_rover'
            or original.get('state') not in {'FINISHED','UNCONFIRMED'}):
        raise locks.VehicleBusy('Ground close descriptor/start association differs')
    execution=original['environment_execution'];assert_environment_execution(execution)
    return {'input_sha256':job['input_sha256'],'target':target,'start_operation':original,'environment_execution':execution}


def ground_close(owner,action,selected,target,barrier):
    from tools import rover_ground_executor as ground
    from planning.artifact_store import fingerprint
    job,_,request,_=ground._checked(ground.directory(owner))
    reference=job.get('ground_close_reference')
    if (action!='stop' or selected.name!='two_drones_rover' or request.get('kind')!='ROVER_PULSE_V1'
            or request.get('infrastructure_close')!={'kind':'SAME_SESSION_INFRASTRUCTURE_V1'}
            or job['job_state']!='UNCONFIRMED' or not reference
            or fingerprint(reference)!=job.get('ground_close_reference_sha256')
            or barrier!=locks.restriction('v3') or not barrier or barrier['owner_id']!=owner
            or barrier.get('input_sha256')!=job['input_sha256'] or barrier['state']!='UNCONFIRMED'
            or locks.infrastructure_restriction() is not None or locks.sequence_restriction() is not None
            or any(locks.restriction(v) is not None for v in ('v1','v2'))
            or (locks.identity_alive(job.get('worker')) and job['worker']!=locks.process_identity())):
        raise locks.VehicleBusy('Ground close owner/reservation/scope differs or worker active')
    current=ground_close_reference(job)
    if current!=reference or current['target']!=target:
        raise locks.VehicleBusy('Ground close original descriptor/execution changed')
    return reference['environment_execution']


def ground_cleanup_receipt(record,log_path):
    """Consume this operation's original bounded backend stream, not SUCCESS alone."""
    from tools.virtual_preflight_jobs import read_mission_input
    raw=read_mission_input(log_path);rows=[]
    for line in raw.splitlines():
        if line.startswith(b'{'):
            value=json.loads(line)
            if isinstance(value,dict) and 'remaining' in value:rows.append(value)
    if len(rows)!=1:raise locks.VehicleBusy('Ground close original cleanup receipt absent/ambiguous')
    value=rows[0];descriptor=record['diagnostic_close_target'];diagnostic=value['diagnostic_agent']
    if (value.get('success') is not True or any(value.get(k)!=[] for k in
            ('remaining','errors','unattributed_auxiliaries','diagnostic_coordination_errors'))
            or not isinstance(value.get('signals'),list) or not isinstance(value.get('observed_processes'),list)
            or any(diagnostic['selection'].get(k)!=v for k,v in descriptor.items())
            or diagnostic['monitor']['lifecycle_id']!=descriptor['lifecycle_id']):
        raise locks.VehicleBusy('Ground cleanup partial/contradictory or belongs to another session')
    return {'source':'OWN_OPERATION_BACKEND_COMBINED_STREAM','sha256':hashlib.sha256(raw).hexdigest(),
        'observed_at':locks.utc_now(),'cleanup':value,'vehicle_stationary':None,'vehicle_disarmed':None}


START_CLOSE_KIND = 'ORDINARY_FAILED_START_CLOSE_V1'
START_CLOSE_AUTHORIZATION = 'AUTHORIZE_FAILED_START_CLOSE'
START_BACKEND_TIMEOUT_S = 180  # _backend() start budget; the launch must begin inside it
# Draft policy gate: remain disabled until the exact diff is reviewed and promoted.
PASSIVE_SCOPE_POLICY_ENABLED = False
PASSIVE_STOP_CONFIRMATION_WAIT_S = 15.0
PASSIVE_STOP_GUARD_S = 0.25
PASSIVE_SESSION_ROOT = locks.LOCK_ROOT.parent/'passive_rover_sessions'
PASSIVE_SCOPE_CLAIM_ROOT = locks.LOCK_ROOT/'passive_scope_claims'
CLOSE_ROLES = {'tools.virtual_preflight_worker', 'tools.preflight_sequence_worker', 'tools.simulation_lifecycle',
               'tools.simulation_mission_executor', 'tools.rover_ground_executor', 'tools.rover_identity_worker'}

# Same supervisor ownership rules as the stop backend, run read-only in the exact
# container. /tmp is on the path exactly as for /tmp/tfg_sim_processes.py, so the
# diagnostic helper resolves as it does during a real stop.
START_CLOSE_INVENTORY = r'''
import json, os, sys, types
from pathlib import Path
sys.path.insert(0, '/tmp')
v = json.load(sys.stdin)
p = types.ModuleType('tfg_simulation_profiles'); sys.modules[p.__name__] = p; exec(v['profiles'], p.__dict__)
m = types.ModuleType('readonly_start_close_supervisor'); sys.modules[m.__name__] = m; exec(v['supervisor'], m.__dict__)
result = m.readonly_inventory()
for row in result['owned']:
    try:
        env = (Path('/proc') / str(row['pid']) / 'environ').read_bytes().split(b'\0')
        row['profile_tag'] = next((e.split(b'=', 1)[1].decode() for e in env if e.startswith(b'TFG_SIM_PROFILE=')), None)
    except OSError:
        row['profile_tag'] = None
# Tick->wall conversion drifts on WSL; keep the realtime mtime of the launch state
# file (written right after spawning) and the container init ticks for ordering.
state = Path('/tmp/tfg_demo.processes.json')
result['launch_state_mtime'] = state.stat().st_mtime if state.exists() else None
result['container_init_ticks'] = int((Path('/proc/1/stat')).read_text().rpartition(')')[2].split()[19])
result['pid_file'] = Path('/tmp/tfg_demo.pid').read_text().strip() if Path('/tmp/tfg_demo.pid').exists() else None
result['installed_supervisor_sha256'] = __import__('hashlib').sha256(Path('/tmp/tfg_sim_processes.py').read_bytes()).hexdigest() if Path('/tmp/tfg_sim_processes.py').exists() else None
print(json.dumps(result))
'''


def read_container_inventory(container_id):
    """Bounded read-only supervisor inventory in the exact container; never signals."""
    payload = {'profiles': (locks.PROJECT_ROOT/'tools/simulation_profiles.py').read_text(),
               'supervisor': (SCRIPTS/'sim_processes.py').read_text()}
    result = subprocess.run(['docker', 'exec', '-i', container_id, 'python3', '-B', '-c', START_CLOSE_INVENTORY],
                            input=json.dumps(payload), capture_output=True, text=True, timeout=10, check=False)
    if result.returncode:
        raise locks.VehicleBusy('Container inventory failed; not absence: ' + result.stderr[-400:])
    return json.loads(result.stdout)


def host_role_processes():
    """Project role processes on the host. A process that exits while being read is gone; any other read error
    means its role cannot be ruled out, so the scan is refused rather than returning fewer processes."""
    found = []
    for path in Path('/proc').iterdir():
        if not path.name.isdigit() or int(path.name) == os.getpid():
            continue
        try:
            args = {a.decode(errors='replace') for a in (path/'cmdline').read_bytes().split(b'\0')}
        except (FileNotFoundError, ProcessLookupError):
            continue
        except OSError as exc:
            raise _unknown('host process '+path.name, f'cmdline unreadable ({type(exc).__name__})') from None
        if CLOSE_ROLES & args:
            found.append(locks.process_identity(int(path.name)))
    return found


def _wall(value):
    from datetime import datetime
    return datetime.fromisoformat(value).timestamp()


def assess_start_close(owner, lease_bytes, operation_bytes, inventory, *, host_boot_id, owner_alive,
                       vehicle_restrictions, other_guards, diagnostic_target, host_roles):
    """Pure eligibility decision for closing ONE ordinary UNCONFIRMED start. Raises VehicleBusy."""
    def require(condition, reason):
        if not condition:
            raise locks.VehicleBusy('Start close BLOCKED: ' + reason)
    require(str(UUID(owner)) == owner, 'owner is not a canonical UUID')
    lease, operation = json.loads(lease_bytes), json.loads(operation_bytes)
    require(lease == operation, 'lease differs from its original operation record')
    require(lease.get('kind') == 'SIMULATION_LIFECYCLE' and lease.get('owner_id') == owner
            and lease.get('action') == 'start' and lease.get('state') == 'UNCONFIRMED', 'not this UNCONFIRMED start')
    require(not any(k in lease for k in ('diagnostic_agent', 'diagnostic_close_target', 'closing_failed_start',
                                         'closing_ground_trial', 'closing_ordinary_start')),
            'diagnostic or closing lease; use its own procedure')
    require(lease.get('movement_authorized') is False and lease.get('scope') == 'SIMULATION_INFRASTRUCTURE_ONLY',
            'lease scope is not infrastructure-only')
    profile = get_profile(lease['profile'])
    process = lease.get('process') or {}
    require(process.get('boot_id') == host_boot_id, 'owner recorded on another host boot')
    require(owner_alive is False, 'original owner still alive or unknown')
    execution = lease.get('environment_execution')
    require(isinstance(execution, dict) and execution.get('container_boot_id') == host_boot_id,
            'container execution reference absent or bound to another boot')
    require(not any(vehicle_restrictions.values()), 'vehicle reservations present')
    require(not other_guards, 'other guards present: ' + ','.join(sorted(other_guards)))
    require(diagnostic_target is None or diagnostic_target.get('state') == 'CLOSED', 'diagnostic session not CLOSED')
    require(not host_roles, 'another project role process is running on the host')
    require(inventory.get('boot_id') == host_boot_id, 'container inventory from another boot')
    require(inventory.get('ambiguous') == [], 'processes of uncertain ownership present')
    state = json.loads(inventory['state_files'].get('/tmp/tfg_demo.processes.json', 'null'))
    require(isinstance(state, dict) and state.get('project') == 'Agentic_Drone_Mission_Control'
            and isinstance(state.get('identities'), list) and len(state['identities']) == 1,
            'launch state file absent or not exactly one recorded identity')
    root_pid, root_ticks = state['identities'][0]
    owned = {row['pid']: row for row in inventory['owned']}
    root = owned.get(root_pid)
    require(root is not None and root['start_ticks'] == root_ticks, 'recorded launch identity not alive (PID reuse or exit)')
    expected_argv = ['ros2', 'launch', profile.launch_package, profile.launch_file, *profile.fixed_launch_arguments,
                     'gui:=' + ('true' if lease.get('gui') else 'false')]
    argv = list(root['argv'])
    tail = argv[-len(expected_argv):]
    require(len(tail) == len(expected_argv) and Path(tail[0]).name == 'ros2' and tail[1:] == expected_argv[1:]
            and (len(argv) == len(expected_argv)
                 or len(argv) == len(expected_argv) + 1 and Path(argv[0]).name.startswith('python')),
            'launch root argv differs from the profile')
    started = _wall(lease['started_at'])
    mtime = inventory.get('launch_state_mtime')
    require(isinstance(mtime, (int, float)) and started - 2 <= mtime <= started + START_BACKEND_TIMEOUT_S + 2,
            'launch state was not written inside this operation window')
    require(type(inventory.get('container_init_ticks')) is int and root_ticks > inventory['container_init_ticks'],
            'launch root predates the current container execution')
    require(inventory.get('pid_file') == str(root_pid), 'compatibility PID file differs from the recorded launch')
    children = {root_pid}
    while True:
        added = {pid for pid, row in owned.items() if row['ppid'] in children} - children
        if not added:
            break
        children |= added
    require(set(owned) == children, 'owned processes outside the recorded launch tree')
    require(all(row.get('tagged') is True and row.get('profile_tag') == profile.name for row in owned.values()),
            'process without project/profile tag in the launch tree')
    require(all(a['pid'] in owned for a in inventory.get('agents', [])), 'micro_ros_agent outside the launch tree')
    processes = sorted([row['pid'], row['start_ticks'], row['argv'][:3]] for row in owned.values())
    return {'kind': START_CLOSE_KIND, 'owner_id': owner, 'profile': profile.name,
            'lease_sha256': hashlib.sha256(lease_bytes).hexdigest(),
            'operation_sha256': hashlib.sha256(operation_bytes).hexdigest(),
            'environment_execution': execution, 'host_boot_id': host_boot_id,
            'launch_identity': [root_pid, root_ticks], 'launch_state_mtime': mtime,
            'processes': processes, 'effects': ['STOP_RECORDED_LAUNCH_TREE_VIA_BACKEND',
                                                'RELEASE_LEASE_ONLY_AFTER_CONFIRMED_CLEANUP'],
            'movement_authorized': False}


def _start_close_scope(owner):
    """Fresh read under the CALLER's exclusion (both lifecycle mutexes held)."""
    lease_path = locks.LOCK_ROOT/'lifecycle.json'
    operation_path = locks.LOCK_ROOT.parent/'simulation_lifecycle'/owner/'operation.json'
    lease_bytes, operation_bytes = lease_path.read_bytes(), operation_path.read_bytes()
    lease = json.loads(lease_bytes)
    assert_environment_execution(lease.get('environment_execution'))
    protected = protected_session_state()
    if protected['passive_open']:
        raise locks.VehicleBusy('Start close BLOCKED: a passive rover session is open/uncertain')
    others = {n for n in _list_protected_dir(locks.LOCK_ROOT, 'lock root') or () if n.endswith('.json') and n != 'lifecycle.json'}
    inventory = read_container_inventory(lease['environment_execution']['persistent_identity']['container_id'])
    scope = assess_start_close(
        owner, lease_bytes, operation_bytes, inventory,
        host_boot_id=Path('/proc/sys/kernel/random/boot_id').read_text().strip(),
        owner_alive=locks.identity_alive(lease.get('process')),
        vehicle_restrictions={v: locks.restriction(v) for v in locks.RESERVATION_INTERFACES},
        other_guards=others, diagnostic_target=protected['diagnostic'],
        host_roles=host_role_processes())
    assert_environment_execution(lease['environment_execution'])
    return scope, inventory


def inspect_start_close(owner):
    """Phase A, read-only: same mutexes as lifecycle, no lease/state/backend change."""
    try:
        with (locks.file_mutex(locks.LOCK_ROOT / "v1.execution.lock", blocking=False),
              locks.file_mutex(locks.LOCK_ROOT / "registry.lock", blocking=False)):
            scope, inventory = _start_close_scope(owner)
    except (locks.VehicleBusy, OSError, ValueError, KeyError, TypeError) as exc:
        return {'status': 'BLOCKED', 'reason': str(exc), 'owner_id': owner, 'lease_changed': False}
    sha = hashlib.sha256(json.dumps(scope, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    return {'status': 'ELIGIBLE', 'owner_id': owner, 'scope': scope, 'scope_sha256': sha,
            'required_authorization': f'{START_CLOSE_AUTHORIZATION} {owner} {sha}',
            'inventory_owned': inventory['owned'], 'lease_changed': False}


def start_close(owner, scope_sha256, authorization):
    """Under both mutexes: recompute the exact reviewed scope; becomes the closing lease."""
    if authorization != f'{START_CLOSE_AUTHORIZATION} {owner} {scope_sha256}':
        raise locks.VehicleBusy('Exact failed-start close authorization required')
    scope, _ = _start_close_scope(owner)
    if hashlib.sha256(json.dumps(scope, sort_keys=True, separators=(',', ':')).encode()).hexdigest() != scope_sha256:
        raise locks.VehicleBusy('Failed-start close scope changed since review; inspect again')
    return scope


def completed_start_close(owner):
    """Idempotent query: a FINISHED closing operation for this owner, if any."""
    base = locks.LOCK_ROOT.parent/'simulation_lifecycle'
    for name in _list_protected_dir(base, 'lifecycle operations') or ():
        value = _read_protected_record(base/name/'operation.json', 'lifecycle operation '+name)
        if value is None:
            continue  # an operation directory whose record was never written holds no completed close
        closing = value.get('closing_ordinary_start') or {}
        if not isinstance(closing, dict):
            raise _unknown('lifecycle operation '+name, 'closing record malformed')
        if closing.get('scope', {}).get('owner_id') == owner:
            return value
    return None


def start_close_receipt(log_path, scope):
    """This operation's backend stream plus a post-stop inventory; never SUCCESS alone."""
    from tools.virtual_preflight_jobs import read_mission_input
    raw = read_mission_input(log_path)
    rows = [json.loads(line) for line in raw.splitlines() if line.startswith(b'{"success"')]
    if len(rows) != 1:
        raise locks.VehicleBusy('Close cleanup receipt absent or ambiguous')
    value = rows[0]
    if (value.get('success') is not True or any(value.get(k) != [] for k in
            ('remaining', 'errors', 'unattributed_auxiliaries', 'diagnostic_coordination_errors'))):
        raise locks.VehicleBusy('Close cleanup partial or contradictory')
    after = read_container_inventory(scope['environment_execution']['persistent_identity']['container_id'])
    if (after.get('owned') != [] or after.get('ambiguous') != [] or after.get('agents') != []
            or '/tmp/tfg_demo.processes.json' in after.get('state_files', {})):
        raise locks.VehicleBusy('Launch tree, agent or launch state still present after close')
    return {'source': 'OWN_OPERATION_BACKEND_STREAM', 'sha256': hashlib.sha256(raw).hexdigest(),
            'cleanup': value, 'post_close_inventory': {k: after.get(k) for k in ('owned', 'ambiguous', 'agents')},
            'observed_at': locks.utc_now()}


def _passive_session_path(owner):
    if not isinstance(owner,str) or str(UUID(owner))!=owner:
        raise locks.VehicleBusy('Passive session owner must be a canonical UUID')
    return PASSIVE_SESSION_ROOT/(owner+'.json')


class ProtectedStateUnknown(locks.VehicleBusy):
    """A protected-session source could not be shown absent or valid; every STOP and START blocks on it."""


def _unknown(source, reason):
    return ProtectedStateUnknown(f'PROTECTED_STATE_UNKNOWN {source}: {reason}')


def _real_directory(path, source):
    """lstat: True for a real directory, False only for FileNotFoundError; a link, another type or a read error
    raises."""
    try:
        st=os.lstat(path)
    except FileNotFoundError:
        return False
    except OSError as exc:
        raise _unknown(source, f'unreadable ({type(exc).__name__})') from None
    if stat.S_ISLNK(st.st_mode):raise _unknown(source, 'is a symbolic link')
    if not stat.S_ISDIR(st.st_mode):raise _unknown(source, 'is not a directory')
    return True


def _read_protected_record(path, source):
    """A protected JSON record: None ONLY when lstat reports FileNotFoundError; otherwise a dict or a refusal.

    A link (dangling or not), another file type, any read error, a file replaced while being read, invalid JSON or a
    value that is not an object (null, list, string, number) is never an absent record."""
    try:
        before=os.lstat(path)
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise _unknown(source, f'unreadable ({type(exc).__name__})') from None
    if stat.S_ISLNK(before.st_mode):raise _unknown(source, 'record is a symbolic link')
    if not stat.S_ISREG(before.st_mode):raise _unknown(source, 'record is not a regular file')
    try:
        descriptor=os.open(path, os.O_RDONLY|os.O_NOFOLLOW)
        with os.fdopen(descriptor,'rb') as handle:
            raw=handle.read();during=os.fstat(handle.fileno())
        after=os.lstat(path)
    except OSError as exc:
        raise _unknown(source, f'unreadable ({type(exc).__name__})') from None
    if len({(st.st_dev,st.st_ino) for st in (before,during,after)})!=1 or after.st_mtime_ns!=before.st_mtime_ns:
        raise _unknown(source, 'record changed while being read')
    try:
        value=json.loads(raw)
    except ValueError:
        raise _unknown(source, 'record is not valid JSON') from None
    if not isinstance(value,dict):
        raise _unknown(source, f'record is {type(value).__name__}, not an object')
    return value


def _list_protected_dir(path, source):
    """Entry names of a protected directory, or None ONLY when it does not exist. Enumeration errors propagate as
    refusals (os.scandir, never Path.glob, which suppresses them), and a directory that changes while it is listed
    is refused."""
    if not _real_directory(path, source):
        return None
    try:
        before=os.lstat(path)
        with os.scandir(path) as entries:
            names=sorted(entry.name for entry in entries)
        after=os.lstat(path)
    except OSError as exc:
        raise _unknown(source, f'cannot be listed ({type(exc).__name__})') from None
    if (before.st_dev,before.st_ino,before.st_mtime_ns)!=(after.st_dev,after.st_ino,after.st_mtime_ns):
        raise _unknown(source, 'changed while being listed')
    return names


PASSIVE_STATES={'OPENING','STARTED','STOPPING','CLOSED','CLOSED_INCOMPLETE','UNCONFIRMED'}
DIAGNOSTIC_STATES={'OPENING','STARTED','UNCONFIRMED','CLOSED'}
LOCK_RECORDS=('lifecycle.json','reconciliation.json','sequence.json',
              *(f'{v}.json' for v in locks.RESERVATION_INTERFACES))


def _valid_passive_record(value, owner):
    if (value.get('schema')!='tfg.rover.passive-session-state/1' or value.get('session_id')!=owner
            or value.get('state') not in PASSIVE_STATES):
        raise _unknown('passive session '+owner, 'malformed or unknown state')
    return value


def _read_passive_session(owner):
    value=_read_protected_record(_passive_session_path(owner), 'passive session '+owner)
    if value is None:
        raise locks.VehicleBusy('Passive session record absent/unsafe; no STOP retargeting')
    return _valid_passive_record(value, owner)


def _active_passive_sessions():
    """Open or uncertain passive sessions; [] only when the registry is shown absent or every record is closed."""
    names=_list_protected_dir(PASSIVE_SESSION_ROOT, 'passive session registry')
    if names is None:
        return []
    active=[]
    for name in names:
        owner=name[:-len('.json')] if name.endswith('.json') else None
        try:
            canonical=owner is not None and str(UUID(owner))==owner
        except ValueError:
            canonical=False
        if not canonical:
            # an interrupted atomic write, a foreign file or a renamed record: its session cannot be ruled out
            raise _unknown('passive session registry', f'unexpected entry {name!r}')
        value=_valid_passive_record(_read_protected_record(PASSIVE_SESSION_ROOT/name, 'passive session '+owner)
                                    or {}, owner)
        if value['state'] not in {'CLOSED','CLOSED_INCOMPLETE'}:active.append(value)
    return active


def _diagnostic_target():
    """The diagnostic session record: None only when shown absent; otherwise a valid record or a refusal."""
    value=_read_protected_record(locks.LOCK_ROOT.parent/'diagnostic_agent_session.json', 'diagnostic session')
    if value is None:
        return None
    if value.get('state') not in DIAGNOSTIC_STATES or not isinstance(value.get('descriptor'),dict):
        raise _unknown('diagnostic session', 'malformed or unknown state')
    from tools.rover_xrce_trace.selection import check_frozen_descriptor
    try:
        check_frozen_descriptor(value['descriptor'])
    except (ValueError,KeyError,TypeError):
        raise _unknown('diagnostic session', 'descriptor invalid') from None
    return value


def protected_session_state():
    """THE admission criterion for every lifecycle action, read under the caller's lifecycle mutexes.

    Returns {'passive_open': [...], 'diagnostic': record | None} only when every protected-session source was read
    completely: the passive session registry (each record valid), the diagnostic session record, and the type of
    every lock record (a link or another type is refused here; their contents are validated by locks.restriction).
    Any UNKNOWN, INVALID or changing source raises before a lease is written or a backend is called. An ordinary
    STOP is admitted only when this shows no open passive session and no open diagnostic session (and
    locks.restriction shows no reservation); a directed STOP additionally needs the compatible owner and identity."""
    for directory,source in ((locks.LOCK_ROOT.parent,'state root'),(locks.LOCK_ROOT,'lock root')):
        if not _real_directory(directory, source):
            if directory==locks.LOCK_ROOT:raise _unknown(source, 'missing under the held mutex')
    names=set(_list_protected_dir(locks.LOCK_ROOT, 'lock root') or ())
    for name in LOCK_RECORDS:
        if name in names:
            try:
                st=os.lstat(locks.LOCK_ROOT/name)
            except OSError as exc:
                raise _unknown('lock record '+name, f'unreadable ({type(exc).__name__})') from None
            if not stat.S_ISREG(st.st_mode):
                raise _unknown('lock record '+name, 'is a symbolic link or not a regular file')
    return {'passive_open':_active_passive_sessions(), 'diagnostic':_diagnostic_target()}


def _fresh_passive_precheck(expected_target):
    from tools.rover_xrce_trace.historical_disposition import diagnostic_precheck_locked
    return diagnostic_precheck_locked(expected_target=expected_target)


def _verify_passive_final_inventory(inventory, scope):
    if not isinstance(inventory,dict):raise locks.VehicleBusy('Final passive inventory malformed')
    expected=scope['environment_execution']
    if inventory.get('boot_id')!=expected.get('container_boot_id'):
        raise locks.VehicleBusy('Final inventory container boot differs')
    for key in ('owned','ambiguous','agents'):
        if not isinstance(inventory.get(key),list) or inventory[key]:
            raise locks.VehicleBusy('Final inventory reports active/ambiguous '+key)
    state_files=inventory.get('state_files')
    if not isinstance(state_files,dict) or any(k in state_files for k in ('/tmp/tfg_demo.processes.json','/tmp/tfg_demo.pid')):
        raise locks.VehicleBusy('Final inventory retains launch state/PID evidence')
    return {'schema':'tfg.rover.passive-final-inventory/1','status':'COMPLETE',
            'container_id':expected['persistent_identity']['container_id'],
            'container_boot_id':expected['container_boot_id'],
            'inventory_sha256':hashlib.sha256(json.dumps(inventory,sort_keys=True,separators=(',',':')).encode()).hexdigest(),
            'observed_at_utc':locks.utc_now(),'owned':0,'ambiguous':0,'agents':0,
            'movement_authorized':False}


def run_lifecycle(action, *, gui=True, profile="two_drones", diagnostic_agent_manifest=None,
                  close_owner=None, ground_owner=None, start_close_request=None,
                  passive_scope=None, passive_scope_sha256=None, passive_authorization=None,
                  passive_session_owner=None):
    if action not in {"start", "stop", "restart"} or type(gui) is not bool:
        return {"success": False, "status": "ERROR", "message": "Invalid action or GUI mode"}
    try:
        selected = get_profile(profile)  # before mutex files, leases or subprocesses
        passive_args=(passive_scope is not None or passive_scope_sha256 is not None or passive_authorization is not None
                      or passive_session_owner is not None)
        if selected.name=='rover_only' and action=='restart':
            raise ValueError('rover_only restart is not admitted; use one scoped START and its same-session STOP')
        if selected.name=='rover_only' and action=='start':
            if not PASSIVE_SCOPE_POLICY_ENABLED:
                raise ValueError('Passive rover START promotion gate is disabled pending protected review')
            if not isinstance(passive_scope,dict) or not passive_scope_sha256 or not passive_authorization:
                raise ValueError('Exact passive scope, hash and human declaration required for rover_only START')
            if passive_session_owner is not None:raise ValueError('STOP owner is invalid for START')
        elif (selected.name=='rover_only' and action=='stop' and close_owner is None and ground_owner is None and start_close_request is None):
            if passive_scope is not None or passive_scope_sha256 is not None or passive_authorization is not None:
                raise ValueError('STOP consumes the recorded session scope; it does not accept a new scope')
            if not passive_session_owner:raise ValueError('Same-session owner required for protected rover_only STOP')
        elif passive_args:
            raise ValueError('Passive scope arguments only apply to protected rover_only START/STOP')
        if ground_owner is not None and (action!='stop' or close_owner is not None):raise ValueError('Ground owner only permits its own stop')
        if start_close_request is not None and (action != 'stop' or close_owner is not None or ground_owner is not None
                                                or diagnostic_agent_manifest is not None):
            raise ValueError('Failed-start close permits only its own stop')
        if close_owner is not None and action != 'stop':
            raise ValueError('Explicit close owner supports stop only')
        manifest = None
        if diagnostic_agent_manifest is not None:
            if action != 'start' or selected.name != 'two_drones_rover':
                raise ValueError('Diagnostic selection supports one explicit rover-profile start only')
            from tools.rover_xrce_trace.selection import load_manifest
            manifest = load_manifest(diagnostic_agent_manifest)
    except (UnknownSimulationProfile, ValueError, OSError, TypeError) as exc:
        return {"success": False, "status": "BLOCKED", "message": str(exc)}
    try:
        # Same order as executor/reconciliation. Even a damaged/missing durable
        # reservation cannot let lifecycle disrupt a still-running OS executor.
        with (locks.file_mutex(locks.LOCK_ROOT / "v1.execution.lock", blocking=False),
              locks.file_mutex(locks.LOCK_ROOT / "registry.lock", blocking=False) as registry):
            barrier = locks.restriction()
            target_path = locks.LOCK_ROOT.parent/'diagnostic_agent_session.json'
            protected = protected_session_state()  # every protected source read completely, or BLOCKED here
            target = protected['diagnostic']
            execution_reference=None
            passive_context=None
            active_passive=protected['passive_open']
            if action in {'start','restart'} and active_passive:
                raise locks.VehicleBusy('A passive rover session is open/uncertain; no second lifecycle')
            # STOP close modes are exclusive: PASSIVE (its own owner, rover_only), DIAGNOSTIC (an open diagnostic
            # target, closed only with its exact descriptor and boot) or ORDINARY (no protected session open or
            # uncertain). Anything else has an unknown, ambiguous or incompatible owner and is refused here.
            passive_stop=(selected.name=='rover_only' and action=='stop' and close_owner is None
                          and ground_owner is None and start_close_request is None)
            open_target=bool(target) and target.get('state')!='CLOSED'
            if action=='stop' and active_passive and not passive_stop:
                raise locks.VehicleBusy('A passive rover session is open/uncertain; only its own STOP is admitted')
            if action=='stop' and passive_stop and open_target:
                raise locks.VehicleBusy('Passive and diagnostic sessions both open; ambiguous STOP owner')
            diagnostic_stop=(action=='stop' and open_target and not passive_stop and close_owner is None
                             and ground_owner is None and start_close_request is None)
            if action=='stop' and open_target and start_close_request is not None:
                raise locks.VehicleBusy('Ordinary-start close cannot close an open diagnostic session')
            if selected.name=='rover_only' and action=='start':
                fresh=_fresh_passive_precheck(target)
                host_identity=locks.process_identity()
                if not host_identity or not host_identity.get('boot_id'):
                    raise locks.VehicleBusy('Current host boot identity unknown')
                from tools.rover_passive_scope import validate_scope, consume_once
                reasons=validate_scope(passive_scope,supplied_sha256=passive_scope_sha256,
                    authorization=passive_authorization,fresh_precheck=fresh,host_boot_id=host_identity['boot_id'],
                    profile=selected.name)
                if reasons:raise locks.VehicleBusy('Passive scope BLOCKED: '+','.join(reasons))
                execution_reference=fresh['current_environment_execution']
                assert_environment_execution(execution_reference)
                passive_context={'scope':passive_scope,'scope_sha256':passive_scope_sha256,
                                 'authorization':passive_authorization,'precheck':fresh,
                                 'session_id':passive_scope['session_id']}
            elif (selected.name=='rover_only' and action=='stop' and close_owner is None and ground_owner is None and start_close_request is None):
                if len(active_passive)!=1 or active_passive[0].get('session_id')!=passive_session_owner:
                    raise locks.VehicleBusy('STOP owner does not name the unique active passive session')
                passive_context=active_passive[0]
                if passive_context.get('state')!='STARTED':
                    raise locks.VehicleBusy('Passive session is not confirmed STARTED; no STOP replay')
                execution_reference=passive_context.get('environment_execution')
                if not isinstance(execution_reference,dict):
                    raise locks.VehicleBusy('Passive session environment execution unknown')
                assert_environment_execution(execution_reference)
            if ground_owner is not None:
                execution_reference=ground_close(ground_owner,action,selected,target,barrier)
            elif close_owner is not None:
                execution_reference=failed_start_close(close_owner, action, selected, target, barrier)
            elif start_close_request is not None:
                start_owner, start_scope_sha256, start_authorization = start_close_request
                done = completed_start_close(start_owner)
                if barrier is None and done is not None and done.get('state') == 'FINISHED':
                    return {"success": True, "status": "SUCCESS", "already_completed": True, "operation": done}
                if barrier is None or barrier.get('owner_id') != start_owner:
                    raise locks.VehicleBusy('No retained UNCONFIRMED start for this owner; query only, no replay')
                start_scope = start_close(start_owner, start_scope_sha256, start_authorization)
                if start_scope['profile'] != selected.name:
                    raise locks.VehicleBusy('Failed-start close profile differs from the reviewed scope')
                execution_reference = start_scope['environment_execution']
            elif barrier is not None:
                raise locks.VehicleBusy("Flight/lifecycle/reconciliation restriction remains; no simulator recovery")
            if diagnostic_stop:
                if selected.name!='two_drones_rover':
                    raise locks.VehicleBusy('Open diagnostic session belongs to two_drones_rover; no STOP from another profile')
                execution_reference=target.get('environment_execution')
                if not isinstance(execution_reference,dict) or not execution_reference.get('container_boot_id'):
                    raise locks.VehicleBusy('Diagnostic session has no recorded execution/boot; protected close required')
                assert_environment_execution(execution_reference)
                manifest_ids=target['descriptor'].get('manifest') or {}
                if any(execution_reference['persistent_identity'].get(k)!=manifest_ids.get(k)
                       for k in ('engine_id','container_id','image_id')):
                    raise locks.VehicleBusy('Diagnostic session execution differs from its descriptor')
            if target and target.get('state') != 'CLOSED' and action != 'stop':
                raise locks.VehicleBusy('Diagnostic session not explicitly closed; inspect or protected stop first')
            # A CLOSED target is not itself proof that an expired diagnostic
            # monitor completed. Consume only the reviewed audit, with fresh reads
            # under THESE locks, before leases or any stop/start side effects.
            if action in {'start','restart'} and target and selected.name!='rover_only':
                from tools.rover_xrce_trace.historical_disposition import diagnostic_precheck_locked
                decision = diagnostic_precheck_locked(expected_target=target)
                if decision.get('precheck_satisfied') is not True:
                    raise locks.VehicleBusy('Historical diagnostic precheck blocked: '+decision.get('reason','unknown'))
                execution_reference=decision.get('current_environment_execution')
                if not isinstance(execution_reference,dict):
                    raise locks.VehicleBusy('Current execution reference absent after historical precheck')
                assert_environment_execution(execution_reference)
            if manifest is not None and execution_reference is None:
                # The diagnostic session's own execution (container identity, start and boot), so its later STOP
                # can build the exact descriptor/boot pair instead of a general project selection.
                # Read through the lifecycle's fence, which turns any read failure into a refusal.
                from tools.reconciliation_environment import inspect_active_execution
                try:
                    execution_reference=inspect_active_execution()
                except Exception as exc:  # noqa: BLE001 - any read failure is UNKNOWN, never an execution
                    raise locks.VehicleBusy('Diagnostic START execution unreadable: '+type(exc).__name__) from None
                if any(execution_reference['persistent_identity'].get(k)!=manifest.get(k)
                       for k in ('engine_id','container_id','image_id')):
                    raise locks.VehicleBusy('Diagnostic agent requires the exact already-active environment')
            owner_id = passive_context['session_id'] if passive_context and action=='start' else str(uuid4())
            passive_started_monotonic = time.monotonic() if passive_context and action=='start' else None
            root = locks.LOCK_ROOT.parent / "simulation_lifecycle" / owner_id
            if root.exists():raise locks.VehicleBusy('Lifecycle owner directory already exists; no replay')
            if passive_context and action=='start':
                from tools.rover_passive_scope import consume_once
                claim=consume_once(passive_context['scope'],supplied_sha256=passive_context['scope_sha256'],
                    authorization=passive_context['authorization'],fresh_precheck=passive_context['precheck'],
                    host_boot_id=locks.process_identity()['boot_id'],claim_root=PASSIVE_SCOPE_CLAIM_ROOT,
                    lifecycle_owner=owner_id)
            root.mkdir(parents=True)
            record = {"kind": "SIMULATION_LIFECYCLE", "owner_id": owner_id,
                      "state": "EXECUTING", "action": action, "gui": gui, "profile": selected.name,
                      "scope": "SIMULATION_INFRASTRUCTURE_ONLY", "movement_authorized": False,
                      "process": locks.process_identity(), "started_at": locks.utc_now(),
                      "log_path": str(root / "backend.log")}
            if passive_context and action=='start':
                record.update(passive_session_id=owner_id,passive_scope=passive_context['scope'],
                              passive_scope_sha256=passive_context['scope_sha256'],
                              passive_claim=claim,environment_execution=execution_reference)
            if passive_context and action=='stop':
                record.update(passive_session_id=passive_context['session_id'],
                              passive_scope_sha256=passive_context['scope_sha256'],
                              closing_passive_session=passive_context)
            if execution_reference is not None:
                record['environment_execution']=execution_reference
                locks.atomic_json(root/'environment_execution_reference.json',execution_reference)
            if close_owner is not None:
                record['closing_failed_start'] = barrier
            if ground_owner is not None:record['closing_ground_trial']=barrier
            if start_close_request is not None:
                record['closing_ordinary_start'] = {'scope': start_scope, 'scope_sha256': start_close_request[1],
                                                    'original_lease': barrier}
            if manifest is not None:
                from tools.rover_xrce_trace.selection import descriptor
                record['diagnostic_agent'] = descriptor(manifest, owner_id)
            if diagnostic_stop:
                record['closing_diagnostic_session'] = True
            if action == 'stop' and target and target.get('state') != 'CLOSED':
                record['diagnostic_close_target'] = target['descriptor']
            locks.atomic_json(locks.LOCK_ROOT / "lifecycle.json", record)
            locks.atomic_json(root / "operation.json", record)
            passive_state_path=None
            if passive_context and action=='start':
                PASSIVE_SESSION_ROOT.mkdir(parents=True,exist_ok=True,mode=0o700)
                passive_state_path=_passive_session_path(owner_id)
                host_boot_id=locks.process_identity()['boot_id']
                locks.atomic_json(passive_state_path,{'schema':'tfg.rover.passive-session-state/1',
                    'session_id':owner_id,'state':'OPENING','host_boot_id':host_boot_id,
                    'started_host_monotonic_s':passive_started_monotonic,
                    'deadline_host_monotonic_s':passive_started_monotonic+passive_context['scope']['max_session_duration_s'],
                    'scope':passive_context['scope'],
                    'scope_sha256':passive_context['scope_sha256'],'environment_execution':execution_reference,
                    'phase_journal':_new_passive_phase_journal(passive_context['scope'],passive_context['scope_sha256'],owner_id,host_boot_id,execution_reference,passive_started_monotonic,passive_started_monotonic+passive_context['scope']['max_session_duration_s']),
                    'start_operation':str(root/'operation.json'),'updated_at':locks.utc_now(),
                    'movement_authorized':False})
            elif passive_context and action=='stop':
                passive_state_path=_passive_session_path(passive_context['session_id'])
                locks.atomic_json(passive_state_path,{**passive_context,'state':'STOPPING',
                    'stop_operation':str(root/'operation.json'),'updated_at':locks.utc_now(),
                    'movement_authorized':False})
            try:
                fence_phase='prepare_target'
                if manifest is not None:
                    target={'descriptor':record['diagnostic_agent'],'state':'OPENING',
                            'operation_path':str(root/'operation.json'),
                            'environment_execution':record['environment_execution']}
                    locks.atomic_json(target_path,target)
                for step in (["stop", "start"] if action == "restart" else [action]):
                    fence_phase='before_backend'
                    if execution_reference is not None:assert_environment_execution(execution_reference)
                    code = _backend(step, gui, registry.fileno(), record["process"], root/"backend.log")
                    fence_phase='after_backend'
                    if execution_reference is not None:assert_environment_execution(execution_reference)
                    if code != 0:
                        raise RuntimeError(f"{step} backend returned {code}; inspect before another lifecycle")
                if manifest is not None:
                    locks.atomic_json(target_path,{**target,'state':'STARTED'})
                if ground_owner is not None:
                    record['cleanup_receipt']=ground_cleanup_receipt(record,root/'backend.log')
                    locks.atomic_json(root/'cleanup-receipt.json',record['cleanup_receipt'])
                if start_close_request is not None:
                    record['cleanup_receipt'] = start_close_receipt(root/'backend.log', start_scope)
                    locks.atomic_json(root/'cleanup-receipt.json', record['cleanup_receipt'])
                if passive_context and action=='stop':
                    stop_monotonic=time.monotonic()
                    from tools.rover_passive_scope import remaining_session_seconds
                    remaining=remaining_session_seconds(passive_context,current_host_boot_id=locks.process_identity()['boot_id'],
                                                        now_monotonic=stop_monotonic)
                    record['passive_session_timing']={'started_host_monotonic_s':passive_context['started_host_monotonic_s'],
                        'stopped_host_monotonic_s':stop_monotonic,
                        'elapsed_host_monotonic_s':stop_monotonic-passive_context['started_host_monotonic_s'],
                        'deadline_status':'WITHIN_300S' if remaining>0 else 'EXPIRED',
                        'remaining_host_seconds_at_stop':remaining,'clock':'HOST_MONOTONIC_S'}
                    inventory=read_container_inventory(execution_reference['persistent_identity']['container_id'])
                    receipt=_verify_passive_final_inventory(inventory,passive_context['scope'])
                    (locks.LOCK_ROOT/'lifecycle.json').unlink()
                    post_precheck=_fresh_passive_precheck(target)
                    if post_precheck.get('status')!='SATISFIED' or post_precheck.get('precheck_satisfied') is not True:
                        raise locks.VehicleBusy('Final passive precheck BLOCKED: '+str(post_precheck.get('reason','unknown')))
                    if post_precheck.get('current_environment_execution')!=execution_reference:
                        raise locks.VehicleBusy('Final precheck execution identity changed')
                    record['final_inventory']=receipt
                    record['post_stop_precheck']=post_precheck
                    current_state=json.loads(passive_state_path.read_text()); journal=current_state.get('phase_journal')
                    if not isinstance(journal,dict): raise locks.VehicleBusy('Passive phase journal missing after STOP')
                    _append_passive_phase(journal,'STOP',{'backend_action':'stop','backend_returncode':0,'cleanup_confirmed':True},monotonic_now=stop_monotonic)
                    _append_passive_phase(journal,'FINAL_INVENTORY',{'status':'COMPLETE','inventory_sha256':receipt['inventory_sha256'],'post_stop_precheck_satisfied':True},monotonic_now=time.monotonic())
                    from tools.rover_passive_phases import verify as verify_passive_phases
                    phase_report=verify_passive_phases(journal); record['passive_phase_verification']=phase_report
                    closure_state='CLOSED' if phase_report['complete'] else 'CLOSED_INCOMPLETE'
                    locks.atomic_json(passive_state_path,{**current_state,'state':closure_state,'phase_journal':journal,'phase_verification':phase_report,
                        'final_inventory':receipt,'post_stop_precheck':post_precheck,'stop_operation':str(root/'operation.json'),
                        'updated_at':locks.utc_now(),'movement_authorized':False})
                if passive_context and action=='start':
                    opening=json.loads(passive_state_path.read_text())
                    journal=opening['phase_journal']
                    _append_passive_phase(journal,'START',{'backend_action':'start','backend_returncode':0,'start_confirmed':True},monotonic_now=time.monotonic())
                    locks.atomic_json(passive_state_path,{'schema':'tfg.rover.passive-session-state/1',
                        'session_id':owner_id,'state':'STARTED','host_boot_id':locks.process_identity()['boot_id'],
                        'started_host_monotonic_s':passive_started_monotonic,
                        'deadline_host_monotonic_s':passive_started_monotonic+passive_context['scope']['max_session_duration_s'],
                        'scope':passive_context['scope'],
                        'scope_sha256':passive_context['scope_sha256'],'environment_execution':execution_reference,
                        'phase_journal':journal,'start_operation':str(root/'operation.json'),'started_at':locks.utc_now(),
                        'movement_authorized':False})
                if record.get('diagnostic_close_target'):
                    locks.atomic_json(target_path,{**target,'state':'CLOSED','closed_by':owner_id})
                final = {**record, "state": "FINISHED", "finished_at": locks.utc_now()}
                locks.atomic_json(root / "operation.json", final)
                if (locks.LOCK_ROOT / "lifecycle.json").exists():
                    (locks.LOCK_ROOT / "lifecycle.json").unlink()
                return {"success": True, "status": "SUCCESS", "operation": final,
                        "visual_confirmation": "OPERATOR_REQUIRED" if gui and action != "stop" else "NOT_REQUESTED"}
            except BaseException as exc:
                if target and (manifest is not None or record.get('diagnostic_close_target')):
                    locks.atomic_json(target_path,{**target,'state':'UNCONFIRMED'})
                uncertain = {**record, "state": "UNCONFIRMED", "error": f"{type(exc).__name__}: {exc}"}
                if passive_state_path is not None:
                    try:
                        current_state=json.loads(passive_state_path.read_text())
                        locks.atomic_json(passive_state_path,{**current_state,'state':'UNCONFIRMED',
                            'uncertainty':f'{type(exc).__name__}: {exc}','updated_at':locks.utc_now(),
                            'movement_authorized':False})
                    except Exception:
                        # Existing lifecycle UNCONFIRMED lease is the durable blocker.
                        pass
                if isinstance(exc,locks.VehicleBusy) and hasattr(exc,'diagnostic'):
                    uncertain['admission_failure']={'operation':action,'phase':fence_phase,**{
                        'reader_'+k:v for k,v in exc.diagnostic.items()}}
                locks.atomic_json(locks.LOCK_ROOT / "lifecycle.json", uncertain)
                locks.atomic_json(root / "operation.json", uncertain)
                if not isinstance(exc, Exception):
                    raise
                return {"success": False, "status": "UNCONFIRMED", "operation": uncertain}
    except (locks.VehicleBusy, OSError, ValueError,KeyError,TypeError) as exc:
        return {"success": False, "status": "BLOCKED", "message": str(exc)}



def _new_passive_phase_journal(scope, digest, owner, host_boot, execution, started, deadline):
    return {"schema":"tfg.rover.passive-phase-journal/1", "identity":{"scope_sha256":digest,
        "owner_id":owner,"lifecycle_id":owner,"host_boot_id":host_boot,"container_boot_id":execution["container_boot_id"],
        "container_id":execution["persistent_identity"]["container_id"],"vehicle_id":scope["vehicle"]["vehicle_id"]},"deadline":{"started_host_monotonic_s":started,
        "deadline_host_monotonic_s":deadline},"receipts":[]}

def _append_passive_phase(journal, phase, evidence, *, monotonic_now=None):
    from tools.rover_passive_phases import receipt_sha256
    from tools.rover_passive_scope import canonical_json
    now=time.monotonic() if monotonic_now is None else monotonic_now
    previous=journal["receipts"][-1]["receipt_sha256"] if journal["receipts"] else None
    receipt={**journal["identity"],"phase":phase,"operation":"PASSIVE_"+phase,"status":"CONFIRMED","result":"OK",
        "timestamp_host_monotonic_s":now,"previous_receipt_sha256":previous,"evidence":evidence,
        "evidence_sha256":hashlib.sha256(canonical_json(evidence).encode()).hexdigest(),"commands_sent":0,"movement_authorized":False}
    receipt["receipt_sha256"]=receipt_sha256(receipt); journal["receipts"].append(receipt); return receipt

def _validate_passive_phase(phase,evidence,journal):
    from tools.rover_passive_phases import PHASES
    from tools.rover_parameter_correlation import REQUIRED
    if not isinstance(evidence,dict): raise locks.VehicleBusy("Phase evidence must be an object")
    receipts=journal["receipts"]; expected=PHASES[len(receipts)] if len(receipts)<len(PHASES) else None
    if phase!=expected: raise locks.VehicleBusy("Phase out of order, duplicated or complete")
    if phase=="READY_ARMABLE" and (evidence.get("armed") is not False or evidence.get("armable") is not True): raise locks.VehicleBusy("READY not confirmed disarmed/armable")
    if phase=="MOTION_BINDING_V2":
        ident=journal["identity"]
        for k,v in (("binding_schema","tfg.rover.motion-binding/2"),("verdict","BOUND"),("lifecycle_id",ident["lifecycle_id"]),("host_boot_id",ident["host_boot_id"]),("container_boot_id",ident["container_boot_id"]),("vehicle_id",ident["vehicle_id"])):
            if evidence.get(k)!=v: raise locks.VehicleBusy("MotionBinding identity/verdict mismatch: "+k)
        if not evidence.get("status_publisher_gid") or not evidence.get("odometry_publisher_gid"): raise locks.VehicleBusy("MotionBinding publisher identity absent")
    if phase=="PARAMETERS_READ":
        a=evidence.get("ros_values"); b=evidence.get("mavlink_values")
        if evidence.get("parameter_write_count")!=0 or not isinstance(a,dict) or not isinstance(b,dict) or any(k not in a or k not in b or a[k]!=b[k] for k in REQUIRED): raise locks.VehicleBusy("Parameter evidence incomplete or disagreeing")
    if phase=="WORKER_OPEN":
        bind=next(r["evidence"] for r in receipts if r["phase"]=="MOTION_BINDING_V2")
        if (evidence.get("mode")!="PASSIVE" or not evidence.get("worker_id")
                or evidence.get("reservation_id")!=journal.get("worker_reservation_id")
                or journal.get("worker_reservation_consumed") is not True
                or evidence.get("container_id")!=journal["identity"]["container_id"]
                or any(evidence.get(k)!=bind.get(k) for k in ("status_publisher_gid","odometry_publisher_gid"))):
            raise locks.VehicleBusy("Worker must consume the unique PASSIVE reservation and match MotionBinding")
    if phase=="OBSERVATIONS":
        rows=evidence.get("records")
        if evidence.get("observation_count")!=100 or not isinstance(rows,list) or len(rows)!=100 or evidence.get("commands_sent")!=0 or evidence.get("movement_authorized") is not False:
            raise locks.VehicleBusy("Capture must contain exactly 100 passive observations")
        from tools.rover_passive_scope import canonical_json
        capture={"capture_complete":True,"records":rows,"movement_authorized":False,"commands_sent":0}
        digest=hashlib.sha256(canonical_json(capture).encode()).hexdigest()
        if evidence.get("capture_sha256")!=digest: raise locks.VehicleBusy("Capture digest does not match the 100 observations")
    if phase=="OBSERVATIONS_VALIDATED":
        capture=next(r["evidence"] for r in receipts if r["phase"]=="OBSERVATIONS")
        if evidence.get("capture_sha256")!=capture.get("capture_sha256"): raise locks.VehicleBusy("Analysis references another capture")
        report=_passive_stationarity_report(journal,capture,worker_closed=False)
        evidence={**evidence,"verdict":"STATIONARY_OBSERVED","positions_and_velocities_validated":True,"analysis":report}
    if phase=="WORKER_CLOSE":
        opened=next(r["evidence"] for r in receipts if r["phase"]=="WORKER_OPEN")
        if evidence.get("worker_id")!=opened.get("worker_id") or evidence.get("closed") is not True: raise locks.VehicleBusy("Worker close not confirmed")
        capture=next(r["evidence"] for r in receipts if r["phase"]=="OBSERVATIONS")
        report=_passive_stationarity_report(journal,capture,worker_closed=True)
        if report.get("verdict")!="STATIONARY_OBSERVED": raise locks.VehicleBusy("Closed capture failed stationarity verification")
    return evidence

def _passive_stationarity_report(journal,capture_evidence,*,worker_closed):
    from tools.rover_stationarity import analyze, StationarityThresholds
    bind=next(r["evidence"] for r in journal["receipts"] if r["phase"]=="MOTION_BINDING_V2")
    capture={"capture_complete":True,"records":capture_evidence["records"],"movement_authorized":False,"commands_sent":0}
    report=analyze(capture,expected_lifecycle=journal["identity"]["lifecycle_id"],
        expected_boot_id=journal["identity"]["host_boot_id"],expected_status_gid=bind["status_publisher_gid"],
        expected_odometry_gid=bind["odometry_publisher_gid"],
        thresholds=StationarityThresholds(minimum_observations=100,minimum_duration_s=30.0),worker_closed=worker_closed)
    if worker_closed:
        if report["verdict"]!="STATIONARY_OBSERVED": raise locks.VehicleBusy("Stationarity analysis failed: "+str(report["reasons"]))
    else:
        reasons=[r for r in report["reasons"] if r!="WORKER_CLOSE_UNCONFIRMED"]
        if reasons: raise locks.VehicleBusy("Observation analysis failed before worker close: "+str(reasons))
    return report

def reserve_passive_worker(owner):
    # Reserve the single worker slot before the worker process is spawned.
    path=_passive_session_path(owner)
    with (locks.file_mutex(locks.LOCK_ROOT/"v1.execution.lock",blocking=False), locks.file_mutex(locks.LOCK_ROOT/"registry.lock",blocking=False)):
        state=_read_passive_session(owner)
        if state.get("state")!="STARTED" or locks.process_identity().get("boot_id")!=state.get("host_boot_id"):
            raise locks.VehicleBusy("Passive owner/boot is not current")
        if time.monotonic()>=state.get("deadline_host_monotonic_s",0): raise locks.VehicleBusy("300-second host deadline expired")
        journal=state.get("phase_journal")
        if not isinstance(journal,dict): raise locks.VehicleBusy("Passive phase journal missing")
        if journal.get("worker_reservation_id") is not None:
            raise locks.VehicleBusy("Passive worker slot already reserved; duplicate spawn blocked")
        if len(journal.get("receipts",[]))!=4:
            raise locks.VehicleBusy("Worker reservation is out of phase")
        token=str(uuid4()); journal["worker_reservation_id"]=token; journal["worker_reservation_consumed"]=False
        state["phase_journal"]=journal; state["updated_at"]=locks.utc_now()
        locks.atomic_json(path,state); return token

def consume_passive_worker_reservation(owner, reservation_id, container_id):
    # Consume the single-use worker slot atomically before process creation.
    path=_passive_session_path(owner)
    with (locks.file_mutex(locks.LOCK_ROOT/"v1.execution.lock",blocking=False), locks.file_mutex(locks.LOCK_ROOT/"registry.lock",blocking=False)):
        state=_read_passive_session(owner); journal=state.get("phase_journal") or {}
        if (state.get("state")!="STARTED" or locks.process_identity().get("boot_id")!=state.get("host_boot_id")
                or time.monotonic()>=state.get("deadline_host_monotonic_s",0)
                or reservation_id!=journal.get("worker_reservation_id")
                or container_id!=journal.get("identity",{}).get("container_id")
                or journal.get("worker_reservation_consumed") is not False):
            raise locks.VehicleBusy("Worker reservation/owner/boot/container invalid or already consumed")
        journal["worker_reservation_consumed"]=True; journal["worker_spawn_claimed_host_monotonic_s"]=time.monotonic()
        state["phase_journal"]=journal; state["updated_at"]=locks.utc_now()
        locks.atomic_json(path,state); return {"owner":owner,"reservation_id":reservation_id,"container_id":container_id}

def record_passive_phase(owner, phase, evidence):
    path=_passive_session_path(owner)
    with (locks.file_mutex(locks.LOCK_ROOT/"v1.execution.lock",blocking=False), locks.file_mutex(locks.LOCK_ROOT/"registry.lock",blocking=False)):
        if os.path.lexists(locks.LOCK_ROOT/"lifecycle.json"): raise locks.VehicleBusy("Lifecycle operation active")
        state=_read_passive_session(owner)
        if state.get("state")!="STARTED": raise locks.VehicleBusy("Passive lifecycle not confirmed STARTED")
        if locks.process_identity().get("boot_id")!=state.get("host_boot_id"): raise locks.VehicleBusy("Host boot changed")
        now=time.monotonic()
        if now>=state.get("deadline_host_monotonic_s",0): raise locks.VehicleBusy("300-second host deadline expired")
        journal=state.get("phase_journal")
        if not isinstance(journal,dict) or journal["identity"].get("owner_id")!=owner or journal["identity"].get("scope_sha256")!=state.get("scope_sha256"): raise locks.VehicleBusy("Phase journal owner/scope mismatch")
        evidence=_validate_passive_phase(phase,evidence,journal)
        receipt=_append_passive_phase(journal,phase,evidence,monotonic_now=now)
        state["phase_journal"]=journal; state["movement_authorized"]=False; state["updated_at"]=locks.utc_now()
        if phase=="WORKER_OPEN": state["worker_id"]=evidence["worker_id"]
        if phase=="WORKER_CLOSE": state["worker_closed"]=True
        locks.atomic_json(path,state); return receipt



def run_passive_sequence(scope, scope_sha256, authorization, operations, *, gui=False):
    # Injected providers make this route testable offline. Each provider must use
    # a finite transport deadline; a host-monotonic supervisor requests protected STOP.
    required=("ready","motion_binding","parameters","open_worker","observe","close_worker")
    if not isinstance(operations,dict) or any(not callable(operations.get(k)) for k in required):
        return {"status":"BLOCKED","reason":"PASSIVE_OPERATION_PROVIDER_INCOMPLETE","movement_authorized":False}
    started=run_lifecycle("start",gui=gui,profile="rover_only",passive_scope=scope,
        passive_scope_sha256=scope_sha256,passive_authorization=authorization)
    if started.get("status")!="SUCCESS":
        return {"status":started.get("status","UNCONFIRMED"),"start":started,"stop":None,"movement_authorized":False}
    owner=scope["session_id"]; context={"session_id":owner,"scope":scope,"start":started}
    state=_read_passive_session(owner); deadline=state["deadline_host_monotonic_s"]
    failures=[]; worker_id=None; stop_result={}; stop_lock=threading.Lock(); stop_event=threading.Event(); stop_started=[False]
    def request_protected_stop():
        # Keep an opaque synchronous backend call off the coordinator thread.
        # Missing confirmation remains UNCONFIRMED and is never retried.
        with stop_lock:
            if stop_started[0]: return
            stop_started[0]=True
        def stop_target():
            try: result=run_lifecycle("stop",gui=False,profile="rover_only",passive_session_owner=owner)
            except Exception as exc: result={"status":"UNCONFIRMED","error":type(exc).__name__+":"+str(exc)}
            with stop_lock: stop_result.update(result)
            stop_event.set()
        threading.Thread(target=stop_target,name="rover-passive-protected-stop",daemon=True).start()
    # Start slightly before the hard boundary so the existing protected STOP path
    # receives a request before the scope limit. No signal or process kill is used.
    timer=threading.Timer(max(0.0,deadline-time.monotonic()-PASSIVE_STOP_GUARD_S),request_protected_stop)
    timer.daemon=True; timer.start()
    phase_operations=(("READY_ARMABLE","ready"),("MOTION_BINDING_V2","motion_binding"),
        ("PARAMETERS_READ","parameters"),("WORKER_OPEN","open_worker"),("OBSERVATIONS","observe"))
    try:
        for phase,name in phase_operations:
            if time.monotonic()>=deadline:
                failures.append("SESSION_DEADLINE_EXPIRED"); break
            if phase=="WORKER_OPEN":
                reservation=reserve_passive_worker(owner)
                context={**context,"worker_reservation_id":reservation}
            evidence=operations[name](context)
            if phase=="WORKER_OPEN" and isinstance(evidence,dict): worker_id=evidence.get("worker_id")
            record_passive_phase(owner,phase,evidence)
        if not failures and worker_id is not None:
            if time.monotonic()>=deadline: failures.append("SESSION_DEADLINE_EXPIRED")
            else:
                state=_read_passive_session(owner)
                capture=next(r["evidence"] for r in state["phase_journal"]["receipts"] if r["phase"]=="OBSERVATIONS")
                record_passive_phase(owner,"OBSERVATIONS_VALIDATED",{"capture_sha256":capture["capture_sha256"]})
    except Exception as exc:
        failures.append(type(exc).__name__+":"+str(exc))
    finally:
        with stop_lock: stop_already_running=stop_started[0]
        if worker_id is not None and not stop_already_running:
            try:
                close_evidence=operations["close_worker"]({**context,"worker_id":worker_id})

                record_passive_phase(owner,"WORKER_CLOSE",close_evidence)
            except Exception as exc:
                failures.append("WORKER_CLOSE:"+type(exc).__name__+":"+str(exc))
        elif worker_id is not None:
            failures.append("WORKER_CLOSE_UNCONFIRMED_AFTER_SUPERVISOR_STOP")
        timer.cancel()
        with stop_lock: already_started=stop_started[0]
        if not already_started: request_protected_stop()
        if not stop_event.is_set(): stop_event.wait(PASSIVE_STOP_CONFIRMATION_WAIT_S)
    if not stop_result: stop_result.update({"status":"UNCONFIRMED","reason":"PROTECTED_STOP_RESULT_UNKNOWN"})
    state=_read_passive_session(owner); report=state.get("phase_verification")
    status="COMPLETE" if stop_result.get("status")=="SUCCESS" and isinstance(report,dict) and report.get("complete") is True else stop_result.get("status","CLOSED_INCOMPLETE")
    if status=="SUCCESS": status="CLOSED_INCOMPLETE"
    if status=="COMPLETE" and failures: status="CLOSED_INCOMPLETE"
    return {"status":status,"start":started,"stop":stop_result,"phase_verification":report,
        "failures":failures,"session_state":state.get("state"),"movement_authorized":False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("start", "stop", "restart", "verify", "inspect-start-close"))
    parser.add_argument("--headless", action="store_true")
    parser.add_argument("--profile", default="two_drones")
    parser.add_argument('--diagnostic-agent-manifest', type=Path,
                        help='Explicit pinned host manifest; start/two_drones_rover only')
    parser.add_argument('--close-owner', help='Close only this retained UNCONFIRMED diagnostic start')
    parser.add_argument('--start-close-owner', help='Ordinary UNCONFIRMED start to inspect or close')
    parser.add_argument('--scope-sha256', help='Reviewed failed-start close scope')
    parser.add_argument('--authorization', help='Exact operator declaration for that scope')
    parser.add_argument('--passive-scope-file', type=Path, help='Exact versioned passive rover scope JSON')
    parser.add_argument('--passive-session-owner', help='Same-session owner UUID required for protected rover_only STOP')
    args = parser.parse_args()
    if args.action == "verify":
        get_profile(args.profile)
        verify_backend()
        return 0
    if args.action == "inspect-start-close":
        result = inspect_start_close(args.start_close_owner)
        print(json.dumps(result, ensure_ascii=False))
        return 0 if result["status"] == "ELIGIBLE" else 1
    start_request = None
    if args.start_close_owner is not None:
        start_request = (args.start_close_owner, args.scope_sha256, args.authorization)
    passive_scope=None
    if args.passive_scope_file is not None:
        passive_scope=json.loads(args.passive_scope_file.read_text())
    result = run_lifecycle(args.action, gui=not args.headless, profile=args.profile,
                           diagnostic_agent_manifest=args.diagnostic_agent_manifest,
                           close_owner=args.close_owner, start_close_request=start_request,
                           passive_scope=passive_scope,passive_scope_sha256=args.scope_sha256,
                           passive_authorization=args.authorization,passive_session_owner=args.passive_session_owner)
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result["success"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
