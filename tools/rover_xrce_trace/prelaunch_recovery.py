"""Case-pinned pre-launch recovery. Never runs on import; no flight/stop commands.

Not a generic unlock: the reviewed frozen trial establishes the synchronous
bootstrap failure before cleanup/launch. Fresh process absence is necessary but
not sufficient. No MCP exposure or automatic application/restart.
"""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time
from uuid import uuid4

from tools import vehicle_execution_lock as locks
from tools.reconciliation_environment import inspect_environment, environment_identity

TRIAL = '5d541497-25cb-4b23-af81-07808ade6eab'
OWNER = '39fb9601-6691-4fd8-8987-21a81d4a34ee'
MANIFEST_SHA = 'be201cdc09f608abe2bb890c079e3a293ea1c84ef33e32c512d23c273c7be6f8'
EVIDENCE = locks.PROJECT_ROOT/'simulation/ros2_gazebo/results/rover_xrce_trial_2026_10_22'/TRIAL
TTL = 120


def sha(data):
    return hashlib.sha256(data).hexdigest()


def boot():
    return Path('/proc/sys/kernel/random/boot_id').read_text().strip()


def root():
    return locks.LOCK_ROOT.parent/'prelaunch_recovery'


def generated_relative(original):
    """Path below missions/generated of a runtime file recorded by the reviewed trial.

    The sealed index records the absolute path of the checkout that ran the trial. The file's place inside
    missions/generated is derived from that recorded path itself, so the check works from any installation path;
    the record is never rewritten. A recorded path that is relative, has no or several missions/generated
    segments, or climbs with '..' is refused. Which bytes the file must hold is still checked separately."""
    recorded = Path(original)
    parts = recorded.parts
    hits = [i for i in range(len(parts) - 1) if parts[i:i + 2] == ('missions', 'generated')]
    if not recorded.is_absolute() or len(hits) != 1:
        raise ValueError('Recorded runtime path is not below exactly one missions/generated')
    relative = Path(*parts[hits[0] + 2:]) if len(parts) > hits[0] + 2 else None
    if relative is None or '..' in relative.parts:
        raise ValueError('Recorded runtime path does not name a file below missions/generated')
    return relative


def proof():
    raw = (EVIDENCE/'manifest.json').read_bytes()
    if sha(raw) != MANIFEST_SHA:
        raise ValueError('Reviewed trial manifest changed; no recovery')
    for item in json.loads(raw)['files']:
        path = EVIDENCE/item['path']
        if path.is_symlink() or not path.resolve().is_relative_to(EVIDENCE.resolve()):
            raise ValueError('Evidence path changed')
        data = path.read_bytes()
        if len(data) != item['size_bytes'] or sha(data) != item['sha256']:
            raise ValueError('Reviewed pre-launch evidence changed')
    # MANIFEST_SHA pins the reviewed backend control flow, exact exception/log,
    # synchronous prepare return, operation, owner and pre/post inventories.
    index = json.loads((EVIDENCE/'runtime_copy_index.json').read_bytes())
    originals = {}
    for item in index:
        relative = generated_relative(item['original_path'])
        path = locks.LOCK_ROOT.parent/relative
        originals[str(path)] = (EVIDENCE/item['copy']).read_bytes()
    return originals


def local_snapshot(originals, *, marker=None):
    guards = {p.name for p in locks.LOCK_ROOT.glob('*.json')}
    allowed = {'lifecycle.json'} | ({'reconciliation.json'} if marker else set())
    if guards != allowed:
        raise ValueError('Unexpected/missing reservation or concurrent reconciliation')
    for name, content in originals.items():
        path = Path(name)
        if path.is_symlink() or path.read_bytes() != content:
            raise ValueError('Original owner/version/operation/target/log changed')
    lease = json.loads((locks.LOCK_ROOT/'lifecycle.json').read_bytes())
    if lease['owner_id'] != OWNER or lease['state'] != 'UNCONFIRMED' or lease['action'] != 'start':
        raise ValueError('Not the reviewed failed pre-launch owner')
    if boot() != lease['process']['boot_id']:
        raise ValueError('Original worker host boot changed; no historical process inference')
    # Reject even a recycled PID: its relationship must not be guessed.
    if locks.process_identity(lease['process']['pid']) is not None:
        raise ValueError('Original PID alive or recycled')
    if marker is not None and (locks.LOCK_ROOT/'reconciliation.json').read_bytes() != marker:
        raise ValueError('Recovery marker changed')
    roles = {'tools.virtual_preflight_worker', 'tools.preflight_sequence_worker',
             'tools.simulation_lifecycle', 'tools.simulation_mission_executor', 'tools.rover_execution'}
    for directory in Path('/proc').iterdir():
        if not directory.name.isdigit():
            continue
        try:
            args = (directory/'cmdline').read_bytes().split(b'\0')
            decoded = [arg.decode(errors='replace') for arg in args if arg]
            basenames = {role.rsplit('.', 1)[-1]+'.py' for role in roles} | {'rover_passive_collector', 'tfg_rover_identity_worker.py'}
            if (roles.intersection(decoded) or basenames.intersection(Path(arg).name for arg in decoded)):
                raise ValueError('Relevant host worker/coordinator/executor/lifecycle present')
        except (FileNotFoundError, ProcessLookupError):
            pass
    return {name: sha(content) for name, content in originals.items()}


def observe(context=None):
    """Bounded metadata reads only. No ROS imports, services, signals or writes."""
    environment = inspect_environment()
    if context is not None:
        context['environment'] = environment
        context['environment_observed_at_utc'] = locks.utc_now()
    expected = json.loads((EVIDENCE/'environment_before.json').read_bytes())
    if (environment.get('status') != 'ACTIVE'
            or environment_identity(environment) != environment_identity(expected)):
        raise ValueError('Environment unknown, replaced, stopped or incarnation/state changed')
    # Execute the frozen reviewed inventory definitions, not a mutable helper in
    # /tmp. Its top-level definitions are stdlib-only and never call start/stop.
    supervisor = (EVIDENCE/'source_snapshots/simulation/ros2_gazebo/scripts/sim_processes.py').read_text()
    data = {'supervisor': supervisor,
            'prefix': '/tmp/tfg_diagnostic_agents/'+OWNER,
            'worker': '/tmp/tfg_rover_identity/'+OWNER}
    script = '''import json,sys,types
from pathlib import Path
v=json.loads(sys.stdin.read())
p=types.ModuleType('tfg_simulation_profiles');sys.modules[p.__name__]=p
def forbidden_profile(*args,**kwargs):raise RuntimeError('Inventory must not select/start a profile')
p.get_profile=forbidden_profile
m=types.ModuleType('readonly_recovery_inventory');sys.modules[m.__name__]=m
exec(v['supervisor'],m.__dict__)
t=m.snapshot();owned=m.select_owned(t,m.remembered_identities())
blocked=bool(owned or m.unattributed_auxiliaries(t,owned) or any(
 p.argv and (Path(p.argv[0]).name in {'micro_ros_agent','arducopter','ardurover','gz','gzserver','gzclient','gazebo'}
 or any(Path(a).name in {'monitor.py','tfg_rover_identity_worker.py','rover_passive_collector'} for a in p.argv))
 for p in t.values() if not p.zombie))
print(json.dumps({'processes_clear':not blocked,'prefix_exists':Path(v['prefix']).exists(),
 'worker_exists':Path(v['worker']).exists(),'boot_id':Path('/proc/sys/kernel/random/boot_id').read_text().strip(),
 'state_files':{str(p):p.read_text() for p in (m.STATE,m.PID_FILE,m.DIAGNOSTIC_STATE) if p.exists()}}))
'''
    result = subprocess.run(['docker', 'exec', '-i', environment['container_id'], 'python3', '-c', script],
                            input=json.dumps(data), capture_output=True, text=True, timeout=8, check=False)
    if context is not None:
        context['inventory_return_code'] = result.returncode
        context['inventory_received_at_utc'] = locks.utc_now()
    if result.returncode:
        raise ValueError('Container inventory failed; no closure evidence')
    inventory = json.loads(result.stdout)
    if context is not None:
        context['inventory'] = inventory
    if (inventory.get('processes_clear') is not True or inventory.get('prefix_exists') is not False
            or inventory.get('worker_exists') is not False or inventory.get('state_files') != {}
            or not inventory.get('boot_id')):
        raise ValueError('Processes, session artifacts or inventory uncertain')
    return {'environment': environment_identity(environment), 'inventory': inventory}


def prepare(*, review_scope=None, review_reference=None):
    """Future explicit inspection: writes a separate audit only, never restrictions."""
    with locks.file_mutex(locks.LOCK_ROOT/'v1.execution.lock', blocking=False):
        with locks.file_mutex(locks.LOCK_ROOT/'registry.lock', blocking=False):
            originals = proof()
            versions = local_snapshot(originals)
            observed = observe()
            if local_snapshot(originals) != versions:
                raise ValueError('State changed during inspection')
            if review_scope is not None and recovery_scope(originals, observed) != review_scope:
                raise ValueError('Reviewed scope changed; human review required, no automatic renewal')
            record = {'schema': 'tfg.prelaunch-recovery/1', 'preparation_id': str(uuid4()),
                      'owner_id': OWNER, 'trial_id': TRIAL, 'proof_manifest_sha256': MANIFEST_SHA,
                      'boot_id': boot(), 'monotonic': time.monotonic(), 'ttl_seconds': TTL,
                      'versions': versions, 'observed': observed, 'status': 'PREPARED_NOT_APPLIED',
                      'movement_authorized': False, 'ground_contact': 'NOT_ASSERTED', 'review_reference': review_reference}
            directory = root()/record['preparation_id']; directory.mkdir(parents=True)
            locks.atomic_json(directory/'preparation.json', record)
            return {**record, 'preparation_sha256': sha((directory/'preparation.json').read_bytes())}


def apply(preparation_id, preparation_sha256, authorization):
    """Explicit local application only; no inherited authorization or new prepare.

    A partial I/O failure leaves reconciliation.json blocking all admissions.
    Repeated completed application is read-only. Partial application is NOT resumed.
    """
    from uuid import UUID
    if str(UUID(preparation_id)) != preparation_id:
        raise ValueError('Canonical preparation ID required')
    if authorization != f'RECOVER_PRELAUNCH {OWNER} {preparation_id} {preparation_sha256}':
        raise ValueError('New exact authorization required; no substituted preparation')
    directory = root()/preparation_id
    if directory.is_symlink() or (directory/'preparation.json').is_symlink():
        raise ValueError('Preparation paths must not be symlinks')
    raw = (directory/'preparation.json').read_bytes()
    if sha(raw) != preparation_sha256:
        raise ValueError('Preparation hash changed')
    record = json.loads(raw)
    with locks.file_mutex(locks.LOCK_ROOT/'v1.execution.lock', blocking=False):
        with locks.file_mutex(locks.LOCK_ROOT/'registry.lock', blocking=False):
            prior_path = directory/'application.json'
            if prior_path.exists():
                prior = json.loads(prior_path.read_bytes())
                if ((locks.LOCK_ROOT/'reconciliation.json').exists()
                        or prior.get('authorization') != authorization or prior.get('status') != 'APPLIED'):
                    raise ValueError('Partial transaction requires explicit audit; no automatic resume')
                return {**prior, 'replayed': True}
            if (record['preparation_id'] != preparation_id or record['owner_id'] != OWNER
                    or record['proof_manifest_sha256'] != MANIFEST_SHA or record['boot_id'] != boot()
                    or not 0 <= time.monotonic()-record['monotonic'] <= TTL):
                raise ValueError('Wrong owner, boot or expired preparation; no automatic prepare')
            originals = proof()
            if local_snapshot(originals) != record['versions'] or observe() != record['observed']:
                raise ValueError('Owners, versions, processes or environment changed')
            if local_snapshot(originals) != record['versions'] or time.monotonic()-record['monotonic'] > TTL:
                raise ValueError('State changed or preparation expired during revalidation')
            # Archive ALL originals durably before the first runtime transition.
            archive = directory/'originals'; archive.mkdir()
            for index, (name, data) in enumerate(originals.items()):
                with (archive/str(index)).open('xb') as file:
                    file.write(data); file.flush(); os.fsync(file.fileno())
            fd = os.open(archive, os.O_RDONLY | os.O_DIRECTORY)
            try: os.fsync(fd)
            finally: os.close(fd)
            audit = {'status': 'APPLYING', 'authorization': authorization, 'owner_id': OWNER,
                     'preparation_id': preparation_id, 'preparation_sha256': preparation_sha256,
                     'originals': [{'path': name, 'archive': str(archive/str(i)), 'sha256': sha(data)}
                                   for i, (name, data) in enumerate(originals.items())],
                     'observation': record['observed'], 'review_reference': record.get('review_reference'),
                     'historical_operation_modified': False,
                     'ground_contact': 'NOT_ASSERTED', 'movement_authorized': False}
            marker = locks.LOCK_ROOT/'reconciliation.json'
            locks.atomic_json(marker, {'kind': 'RECONCILIATION', 'owner_id': preparation_id,
                                      'state': 'UNCONFIRMED', 'process': locks.process_identity()})
            locks.atomic_json(prior_path, audit)
            target = locks.LOCK_ROOT.parent/'diagnostic_agent_session.json'
            original_target = json.loads(originals[str(target)])
            try:
                locks.atomic_json(target, {**original_target, 'state': 'CLOSED',
                                          'closure_basis': 'REVIEWED_PRELAUNCH_FAILURE_NO_LAUNCH',
                                          'recovery_preparation_id': preparation_id})
                (locks.LOCK_ROOT/'lifecycle.json').unlink()
                final = {**audit, 'status': 'APPLIED', 'transition': 'PRELAUNCH_RESTRICTIONS_RECONCILED',
                         'finished_at': locks.utc_now()}
                locks.atomic_json(prior_path, final)
                marker.unlink()
                fd = os.open(locks.LOCK_ROOT, os.O_RDONLY | os.O_DIRECTORY)
                try: os.fsync(fd)
                finally: os.close(fd)
                return final
            except BaseException:
                # If the last directory fsync/unlink is uncertain, reestablish a
                # durable blocker. Never silently report a partial closure.
                locks.atomic_json(marker, {'kind': 'RECONCILIATION', 'owner_id': preparation_id,
                                          'state': 'UNCONFIRMED', 'process': locks.process_identity()})
                raise


def recovery_scope(originals, observed):
    """Exact human-reviewable effects, stable across observation timestamps."""
    target = locks.LOCK_ROOT.parent/'diagnostic_agent_session.json'
    before = json.loads(originals[str(target)])
    return {'owner_id': OWNER, 'trial_id': TRIAL, 'proof_manifest_sha256': MANIFEST_SHA,
            'implementation_sha256': sha(Path(__file__).read_bytes()),
            'versions': {name: sha(data) for name, data in originals.items()},
            'observed': observed,
            'transitions': [
                {'path': str(locks.LOCK_ROOT/'lifecycle.json'), 'before': 'UNCONFIRMED',
                 'after': 'ABSENT', 'archived_original_sha256': sha(originals[str(locks.LOCK_ROOT/'lifecycle.json')])},
                {'path': str(target), 'before': before, 'after': {**before, 'state': 'CLOSED',
                 'closure_basis': 'REVIEWED_PRELAUNCH_FAILURE_NO_LAUNCH',
                 'recovery_preparation_id': '<fresh preparation UUID>'}},
                {'path': str(locks.LOCK_ROOT/'reconciliation.json'), 'before': 'ABSENT',
                 'during': 'UNCONFIRMED', 'after': 'ABSENT_ONLY_ON_CONFIRMED_COMMIT'}],
            'archive': [{'path': name, 'sha256': sha(data)} for name, data in originals.items()],
            'unchanged': ['historical operation.json UNCONFIRMED', 'backend.log',
                          'historical evidence and reports', 'identity and movement BLOCKED'],
            'partial_failure': 'RETAIN_RESTRICTIONS_AND_AUDIT_NO_AUTOMATIC_RESUME'}


def inspect_recovery():
    """Informational review, NO TTL/preparation and NO application eligibility.

    Collect partial context even if a check fails. Only a separate audit is written.
    Human review precedes any later finite-lived preparation.
    """
    inspection_id = str(uuid4())
    record = {'schema': 'tfg.prelaunch-recovery-review/1', 'inspection_id': inspection_id,
              'owner_id': OWNER, 'trial_id': TRIAL, 'created_at_utc': locks.utc_now(),
              'status': 'BLOCKED', 'reasons': [], 'current_files': {}, 'observation_context': {},
              'scope': None, 'ttl_seconds': None, 'preparation_created': False,
              'application_eligible': False, 'reservations_changed': False,
              'movement_authorized': False, 'ground_contact': 'NOT_ASSERTED'}
    try:
        with locks.file_mutex(locks.LOCK_ROOT/'v1.execution.lock', blocking=False):
            with locks.file_mutex(locks.LOCK_ROOT/'registry.lock', blocking=False):
                originals = proof()
                record['proof_manifest_sha256'] = MANIFEST_SHA
                for name in originals:
                    try:
                        path = Path(name); raw = path.read_bytes()
                        record['current_files'][name] = {'sha256': sha(raw), 'size_bytes': len(raw)}
                        if path.name in {'lifecycle.json', 'operation.json', 'diagnostic_agent_session.json'}:
                            record['current_files'][name]['record'] = json.loads(raw)
                    except (OSError, ValueError) as exc:
                        record['current_files'][name] = {'unknown': type(exc).__name__}
                versions = None
                try:
                    versions = local_snapshot(originals)
                except (OSError, ValueError) as exc:
                    record['reasons'].append('LOCAL: '+str(exc))
                observed = None
                try:
                    observed = observe(record['observation_context'])
                except (OSError, ValueError, subprocess.SubprocessError) as exc:
                    record['reasons'].append('ENVIRONMENT/PROCESSES: '+str(exc))
                if versions is not None and local_snapshot(originals) != versions:
                    record['reasons'].append('Local state changed during informative inspection')
                # Proposed effects remain available for review even when blocked;
                # UNKNOWN observations can never become a preparation's evidence.
                record['scope'] = recovery_scope(originals, observed)
                if not record['reasons']:
                    record['status'] = 'REVIEWABLE_NOT_AUTHORIZED'
    except (OSError, ValueError, locks.VehicleBusy) as exc:
        record['reasons'].append(type(exc).__name__+': '+str(exc))
    directory = root()/'reviews'/inspection_id
    directory.mkdir(parents=True)
    path = directory/'inspection.json'; locks.atomic_json(path, record)
    return {**record, 'inspection_sha256': sha(path.read_bytes()), 'inspection_path': str(path)}


def apply_reviewed(inspection_id, inspection_sha256, authorization):
    """ONE fresh preparation then ONE apply, after exact scope authorization.

    No retries/renewal, no operator-authentication claim, no MCP entry. An
    informative review has no TTL and is never itself release evidence.
    """
    from uuid import UUID
    if str(UUID(inspection_id)) != inspection_id:
        raise ValueError('Canonical inspection ID required')
    if authorization != f'AUTHORIZE_PRELAUNCH_SCOPE {OWNER} {inspection_id} {inspection_sha256}':
        raise ValueError('Explicit authorization of the exact inspected scope required')
    path = root()/'reviews'/inspection_id/'inspection.json'
    if path.is_symlink() or path.parent.is_symlink():
        raise ValueError('Review symlinks not allowed')
    raw = path.read_bytes()
    if sha(raw) != inspection_sha256:
        raise ValueError('Inspection hash mismatch')
    review = json.loads(raw)
    if (review.get('status') != 'REVIEWABLE_NOT_AUTHORIZED' or review.get('inspection_id') != inspection_id
            or review.get('owner_id') != OWNER or review.get('scope') is None):
        raise ValueError('Review blocked or wrong identity; no preparation/application')
    # A review authorization is consumed durably BEFORE preparation. Lost response
    # or reload cannot reuse it to generate another preparation/application.
    directory = path.parent
    with locks.file_mutex(locks.LOCK_ROOT/'v1.execution.lock', blocking=False):
        with locks.file_mutex(locks.LOCK_ROOT/'registry.lock', blocking=False):
            if path.read_bytes() != raw:
                raise ValueError('Review changed before consuming authorization')
            claim = directory/'authorization-consumed.json'
            if claim.exists():
                raise ValueError('Authorization already consumed; audit outcome, never retry automatically')
            locks.atomic_json(claim, {'authorization': authorization, 'status': 'CONSUMED_NOT_OUTCOME',
                                     'inspection_sha256': inspection_sha256, 'at_utc': locks.utc_now()})
    preparation = prepare(review_scope=review['scope'], review_reference={
        'inspection_id': inspection_id, 'inspection_sha256': inspection_sha256,
        'scope_authorization': authorization})
    pid, digest = preparation['preparation_id'], preparation['preparation_sha256']
    locks.atomic_json(directory/'fresh-preparation.json', {'preparation_id': pid, 'preparation_sha256': digest})
    return apply(pid, digest, f'RECOVER_PRELAUNCH {OWNER} {pid} {digest}')


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='action', required=True)
    commands.add_parser('inspect', help='Informative audit only; no TTL or application')
    applying = commands.add_parser('apply-reviewed', help='Requires separate exact scope authorization')
    applying.add_argument('--inspection-id', required=True)
    applying.add_argument('--inspection-sha256', required=True)
    applying.add_argument('--authorization', required=True)
    args = parser.parse_args()
    if args.action == 'inspect':
        result = inspect_recovery()
    else:
        result = apply_reviewed(args.inspection_id, args.inspection_sha256, args.authorization)
    print(json.dumps(result, indent=2))
