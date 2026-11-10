"""Pure read-only classification of the retained last-session pointer.

No runtime operations, writes, reservation changes or identity approval. Callers
must gather current evidence under the existing execution/registry exclusion.
The pointer is not a reservation. Missing/contradictory evidence fails closed.
"""
import json
import hashlib
from pathlib import Path
from uuid import UUID
from .selection import check_frozen_descriptor

POINTER = '/tmp/tfg_demo.diagnostic.json'
FLAGS = {'status':'BLOCKED','movement_authorized':False,'source_association_verified':False}


def _require(condition, reason):
    if not condition:
        raise ValueError(reason)


def _recorded(value):
    _require(isinstance(value,dict), 'Missing/malformed retained record')
    _require(all(value.get(k)==v and type(value.get(k)) is type(v) for k,v in FLAGS.items()),
             'Retained record flags differ')
    return {k:v for k,v in value.items() if k not in FLAGS}


def _process(value):
    _require(isinstance(value,dict), 'Missing recorded process identity')
    _require(type(value.get('pid')) is int and value['pid']>0 and
             type(value.get('start_ticks')) is int and value['start_ticks']>0 and
             isinstance(value.get('boot_id'),str) and bool(value['boot_id']),
             'Incomplete recorded process identity')
    return value


HISTORICAL_OWNER = '51790d37-9fce-489b-9a24-688d3790fff7'
HISTORICAL_MANIFEST = '047f42f388c7391856ee912906613f7f9db6eb16d6d96429eb18e030ac269e7e'


def _timeout_closure_proof(directory, *, target, start, stop, reference, selection, launch, monitor):
    """Read-only, case-pinned original evidence. Never admits or repairs a session."""
    root = Path(directory)
    raw = (root/'manifest.json').read_bytes()
    _require(hashlib.sha256(raw).hexdigest() == HISTORICAL_MANIFEST, 'Historical manifest altered')
    entries = json.loads(raw)['files']
    data = {}
    for entry in entries:
        path = root/entry['path']
        _require(not path.is_symlink() and path.resolve().is_relative_to(root.resolve()), 'Unsafe historical path')
        content = path.read_bytes()
        _require(len(content) == entry['size_bytes'] and hashlib.sha256(content).hexdigest() == entry['sha256'],
                 'Historical original altered: '+entry['path'])
        data[entry['path']] = content
    def read(name):
        return json.loads(data[name])
    prefix = 'container_after/container_copies/tmp/tfg_diagnostic_agents/'+HISTORICAL_OWNER+'/'
    for actual, name in ((target,'host_state_after.json'),
                         (start,'runtime_copies/start/operation.json'),
                         (stop,'runtime_copies/stop/operation.json'),
                         (reference,'runtime_copies/start/rover_environment_reference.json'),
                         (selection,prefix+'selection.json'), (launch,prefix+'launch.json'),
                         (monitor,prefix+'capture/monitor.json')):
        expected = read(name)
        if name == 'host_state_after.json':
            expected = expected['target']
        _require(actual == expected, 'Supplied records differ from pinned originals: '+name)
    report = json.loads(data['runtime_copies/stop/backend.log'].decode().splitlines()[0])
    _require(report['success'] is True and report['errors'] == [] and report['remaining'] == []
             and report['unattributed_auxiliaries'] == [], 'Independent cleanup not confirmed')
    _require(read('lifecycle_stop-command.json')['return_code'] == 0, 'Stop return missing')
    # Pinned original receipt and chronology cannot be replaced by model declarations.
    _require(monitor['phase']=='INCOMPLETE' and monitor['capture_complete'] is False
             and monitor['closure_requested'] is False and monitor['errors']==[
                 'Diagnostic wall-time budget exhausted', 'Agent exit not observed by monitor',
                 'Protected launch exit not observed by monitor'], 'Not reviewed timeout outcome')
    _require(read('lifecycle_stop-command.json')['started_monotonic'] > monitor['finished_monotonic']
             >= monitor['started_monotonic']+monitor['duration_limit_s'], 'Timeout/stop chronology contradictory')


FAILED_OWNER = '104e100b-6614-49d5-85ea-2f070350cc67'
FAILED_MANIFEST = '2cbfa422e39f75ea64967467d59176ce8a079b2e79e7f00c05bc1e6635e65504'


def _failed_closure_proof(directory, *, target, start, stop, reference, selection, launch, monitor):
    """One pinned FAILED case; cleanup proof is independent of the exception text."""
    root=Path(directory);raw=(root/'manifest.json').read_bytes()
    _require(hashlib.sha256(raw).hexdigest()==FAILED_MANIFEST,'Historical FAILED manifest altered')
    data={}
    for entry in json.loads(raw)['files']:
        path=root/entry['path']
        _require(not path.is_symlink() and path.resolve().is_relative_to(root.resolve()),'Unsafe historical path')
        content=path.read_bytes()
        _require(len(content)==entry['size_bytes'] and hashlib.sha256(content).hexdigest()==entry['sha256'],
                 'Historical FAILED original altered: '+entry['path'])
        data[entry['path']]=content
    def read(name):return json.loads(data[name])
    prefix='container-copies/tmp/tfg_diagnostic_agents/'+FAILED_OWNER+'/'
    for actual,name in ((target,'post-close-host-state.json'),(start,'runtime-copies/start/operation.json'),
                        (stop,'runtime-copies/stop/operation.json'),(reference,'runtime-copies/start/rover_environment_reference.json'),
                        (selection,prefix+'selection.json'),(launch,prefix+'launch.json'),(monitor,prefix+'capture/monitor.json')):
        expected=read(name)
        if name=='post-close-host-state.json':expected=expected['target']
        _require(actual==expected,'Supplied records differ from pinned FAILED originals: '+name)
    report=json.loads(data['runtime-copies/stop/backend.log'].decode().splitlines()[0])
    _require(report.get('success') is True and report.get('errors')==[] and report.get('remaining')==[]
             and report.get('unattributed_auxiliaries')==[],'Independent FAILED-session cleanup not confirmed')
    command=read('lifecycle-stop.command.json')
    _require(command['rc']==0 and read('lifecycle-stop.stdout')['success'] is True,'Protected stop receipt missing')
    state=read('post-close-host-state.json');inventory=read('post-close-index.json')['inventory']
    _require(state['guards']=={} and state['restriction'] is None and
             all(inventory.get(k)==[] for k in ('owned','ambiguous','agents')),'Independent post-close state contradictory')
    _require(monitor.get('phase')=='FAILED' and monitor.get('capture_complete') is False and
             monitor.get('error')=="PermissionError: [Errno 13] Permission denied: '/proc/1358/exe'",
             'Not the pinned FAILED outcome')
    _require(command['started_monotonic']<=monitor['observation_monotonic']<=command['finished_monotonic'],
             'FAILED receipt/stop chronology contradictory')
    # Error text alone proves neither process exit nor closure. The independently
    # hash-verified protected stop and post-close records above are required.



PASSIVE_SESSION_LAYOUT = 'PASSIVE_SESSION_RECORDS_V1'
PROTECTED_FAILED_LAYOUT = 'PROTECTED_FAILED_START_CLOSE_V1'
OPERATIONAL_LAYOUT = 'OPERATIONAL_SESSION_RECORDS_V1'
FUNCTION_SESSION_LAYOUT = 'SHA256SUMS_FUNCTION_SESSION_V1'
# Exact paths emitted by the existing preserved-tree/function-result producer.
# No suffix discovery, relabelling or reconstructed subprocess stdout.
FUNCTION_SESSION_PATHS = {
    'start-operation/operation.json':'preserved/start-lifecycle/operation.json',
    'start-operation/rover_environment_reference.json':'preserved/start-lifecycle/rover_environment_reference.json',
    'stop-operation/operation.json':'preserved/stop-lifecycle/operation.json',
    'stop-command.json':'preserved/driver/stop-command.json',
    'stop.stdout':'preserved/driver/stop.stdout',
    'post-precheck.stdout':'preserved/driver/post-precheck.stdout',
    'container-selection.json':'preserved/sdk/overlay/selection.json',
    'container-launch.json':'preserved/sdk/overlay/launch.json',
    'container-capture/monitor.json':'preserved/sdk/overlay/capture/monitor.json',
    'closure-request.json':'preserved/sdk/overlay/capture/closure-request.json',
    'cleanup-finished.json':'preserved/sdk/overlay/capture/cleanup-finished.json',
    'monitor-exit.json':'preserved/sdk/overlay/capture/monitor_exit.json',
}
PASSIVE_SESSION_MANIFEST = '4d9558a2e31b9ea2ec42eca6d8b18cc007ce2cf4049bab011fa561ad59e34faf'
PASSIVE_SESSION_PATHS = {
    'stop-command.json':'passive-session/stop-command.json',
    'stop.stdout':'passive-session/stop.stdout',
    'post-precheck-command.json':'passive-session/post-precheck-command.json',
    'post-precheck.stdout':'passive-session/post-precheck.stdout',
}


def closure_archive_reference(directory):
    """Reference only; application binds its digest, never a UUID allowlist."""
    if Path(directory).is_file():
        _require(not Path(directory).is_symlink(),'Unsafe closure reference')
        reference=json.loads(Path(directory).read_bytes())
        _require(reference.get('kind')=='VERIFIED_CLOSURE_ARCHIVE_V2','Unknown closure reference')
        return reference
    root=Path(directory).resolve()
    if Path(directory).is_symlink():raise ValueError('Unsafe closure archive root')
    if not (root/'manifest.json').exists() and (root/'SHA256SUMS').exists():
        return {'kind':'VERIFIED_CLOSURE_ARCHIVE_V2','directory':str(root),
                'layout':FUNCTION_SESSION_LAYOUT,
                'checksum_sha256':hashlib.sha256((root/'SHA256SUMS').read_bytes()).hexdigest()}
    reference = {'kind':'VERIFIED_CLOSURE_ARCHIVE_V2','directory':str(root),
                 'manifest_sha256':hashlib.sha256((root/'manifest.json').read_bytes()).hexdigest()}
    # Exact reviewed archive, never suffix discovery or a lifecycle-ID exemption.
    if reference['manifest_sha256'] == PASSIVE_SESSION_MANIFEST:
        reference['layout'] = PASSIVE_SESSION_LAYOUT
    elif json.loads((root/'manifest.json').read_bytes()).get('schema')=='rover-operational-evidence/1':
        reference['layout'] = OPERATIONAL_LAYOUT
    return reference


def _passive_session_inventory(read, *, target, start, stop, at):
    """A sealed function-result record, NOT reconstructed subprocess stdout.

    Its separate context supplies return code, reader version, chronology and
    execution identity. The failed partial serialization is never consumed.
    """
    records = read('post-current-records-serializable.json')
    current = read('post-current-conditions.json')
    context = read('post-current-context.json')
    for key, expected in [('target',target),('start_operation',start),('stop_operation',stop),
                          ('environment_reference',read('start-operation/rover_environment_reference.json')),
                          ('selection',read('container-selection.json')),('launch',read('container-launch.json')),
                          ('monitor',read('container-capture/monitor.json'))]:
        _require(records.get(key)==expected, 'Post-close read associated with another session: '+key)
    _require(type(context.get('inventory_return_code')) is int and
             context['inventory_return_code']==0 and current.get('complete') is True,
             'Post-close inventory read failed/incomplete')
    # Recorded hash of the metadata-only reader payload used for this layout.
    _require(context.get('inventory_source_sha256')==
             '526abc38d44bb63dedd3e764ae225153cff3f85a65e8022f5f857649344caef9',
             'Unknown post-close inventory reader provenance')
    sources = context['sources']
    _require(sources==current.get('sources') and bool(sources), 'Post-close source context mismatch')
    names = [row['source'] for row in sources]
    required = ['sim_processes.readonly_inventory in exact container',
                'reconciliation_environment metadata/boot recheck after inventory',
                'host /proc relevant role inventory; vehicle_execution_lock.process_identity',
                'vehicle_locks/*.json and vehicle_execution_lock.restriction']
    _require(all(names.count(name)==1 for name in required) and
             [names.index(name) for name in required]==sorted(names.index(name) for name in required),
             'Post-close inventory observation sources absent/out of order')
    began = at(context['started_at_utc']); times = [at(row['read_at_utc']) for row in sources]
    _require(began>=at(stop['finished_at']) and times==sorted(times) and times[0]>=began and
             0 <= (times[-1]-began).total_seconds() <= 3,
             'Post-close read chronology/freshness unverified')
    environment = context['environment']; recheck = context['environment_recheck']
    inventory_time = times[names.index(required[0])]
    recheck_time = times[names.index(required[1])]
    _require(at(environment['finished_at_utc'])<=inventory_time<=at(recheck['started_at_utc'])<=
             at(recheck['finished_at_utc'])<=recheck_time,
             'Post-close inventory environment chronology unknown')
    identity_keys = ('engine_id','container_id','image_id','name','created_at','state')
    _require(environment.get('status')=='ACTIVE' and recheck.get('status')=='ACTIVE' and
             current.get('environment_observation')==environment and
             all(records['environment'].get(k)==environment.get(k)==recheck.get(k) for k in identity_keys),
             'Post-close inventory environment changed')
    from tools.reconciliation_environment import active_execution_identity
    inventory = records['inventory']
    _require(context['current_environment_execution']==active_execution_identity(environment,inventory['boot_id']),
             'Post-close inventory execution context mismatch')
    pointer = target['descriptor']; prefix = pointer['prefix']
    _require(set(inventory['state_files'])=={POINTER} and
             _recorded(json.loads(inventory['state_files'][POINTER]))==pointer,
             'Post-close inventory pointer associated with another session')
    for key, name in [('selection','selection.json'),('launch','launch.json'),('monitor','capture/monitor.json')]:
        _require(json.loads(inventory['files'][prefix+'/'+name])==records[key],
                 'Post-close inventory retained file mismatch: '+name)
    _require(all(environment[k]==pointer['manifest'][k] for k in ('engine_id','container_id','image_id')),
             'Post-close inventory container identity mismatch')
    _require(current.get('restriction','UNKNOWN') is None and current.get('guards')=={} and
             current.get('host_processes')==[] and current.get('other_sessions')==[] and bool(current.get('host_boot_id')),
             'Historical post-close restrictions/queries not confirmed')
    return inventory


def _manifest_data(reference, *, require_mode=True):
    """Shared original-byte verification; no file discovery or suffix matching."""
    import stat
    _require(isinstance(reference,dict) and reference.get('kind')=='VERIFIED_CLOSURE_ARCHIVE_V2','Unknown closure proof protocol')
    root=Path(reference['directory'])
    if reference.get('layout')==FUNCTION_SESSION_LAYOUT:
        return _checksum_data(reference)
    raw=(root/'manifest.json').read_bytes()
    _require(not root.is_symlink() and hashlib.sha256(raw).hexdigest()==reference['manifest_sha256'],'Closure manifest changed')
    manifest=json.loads(raw);operational=manifest.get('schema')=='rover-operational-evidence/1'
    _require(operational or manifest.get('schema')=='tfg.evidence-manifest/1','Unknown closure manifest')
    if operational:
        _require(reference.get('layout')==OPERATIONAL_LAYOUT and
                 str(UUID(manifest['session_id']))==manifest['session_id'], 'Operational manifest session/layout missing')
    _require(isinstance(manifest.get('files'),list),'Closure manifest entries missing')
    data={}
    for entry in manifest['files']:
        _require(isinstance(entry,dict) and isinstance(entry.get('path'),str),'Malformed closure entry')
        name=entry['path'];path=root/name
        _require(isinstance(name,str) and name and str(Path(name))==name and name!='.' and
                 name not in data and not Path(name).is_absolute() and '..' not in Path(name).parts and
                 not any(p.is_symlink() for p in (path,*path.parents)) and path.is_file()
                 and path.resolve().is_relative_to(root.resolve()),'Unsafe/duplicate closure original')
        content=path.read_bytes()
        size=entry.get('size' if operational else 'size_bytes')
        if operational:
            _require(set(entry)=={'path','size','sha256'},'Operational manifest entry fields differ')
        _require(type(size) is int and size>=0 and len(content)==size and hashlib.sha256(content).hexdigest()==entry['sha256']
                 and (operational or not require_mode and 'mode' not in entry or
                      oct(stat.S_IMODE(path.stat().st_mode))==entry.get('mode')),'Closure original changed: '+name)
        data[name]=content
    return data


def _checksum_data(reference):
    """GNU text SHA256SUMS: hashes/paths only, no invented sizes or modes."""
    import re
    root=Path(reference['directory']);seal=root/'SHA256SUMS'
    _require(not any(p.is_symlink() for p in (seal,*seal.parents)), 'Unsafe checksum archive path')
    raw=seal.read_bytes()
    _require(len(raw)<=65536 and hashlib.sha256(raw).hexdigest()==reference.get('checksum_sha256'),
             'Closure checksum manifest changed')
    data={}
    for line in raw.decode('utf-8').splitlines():
        match=re.fullmatch(r'([0-9a-f]{64})  (.+)',line)
        _require(match is not None,'Malformed closure checksum entry')
        sha,name=match.groups();path=root/name
        _require(name not in data and name!='SHA256SUMS' and str(Path(name))==name and name!='.'
                 and not Path(name).is_absolute() and '..' not in Path(name).parts
                 and not any(p.is_symlink() for p in (path,*path.parents)) and path.is_file()
                 and path.resolve().is_relative_to(root.resolve()),'Unsafe/duplicate checksum original')
        content=path.read_bytes()
        _require(hashlib.sha256(content).hexdigest()==sha,'Closure original changed: '+name)
        data[name]=content
    _require(bool(data),'Empty closure checksum manifest')
    return data


def _verified_closure_data(reference):
    """Reviewed protocol facts, not stop SUCCESS alone or a process snapshot."""
    layout = reference.get('layout')
    _require(layout in (None,PASSIVE_SESSION_LAYOUT,PROTECTED_FAILED_LAYOUT,OPERATIONAL_LAYOUT,FUNCTION_SESSION_LAYOUT), 'Unknown closure archive layout')
    data=_manifest_data(reference,require_mode=layout!=PROTECTED_FAILED_LAYOUT)
    paths=FUNCTION_SESSION_PATHS if layout==FUNCTION_SESSION_LAYOUT else {}
    if layout==OPERATIONAL_LAYOUT:
        paths={'start-operation/operation.json':'start-lifecycle/operation.json',
               'start-operation/rover_environment_reference.json':'start-lifecycle/rover_environment_reference.json',
               'stop-operation/operation.json':'stop-lifecycle/operation.json',
               'stop-command.json':'passive-session/stop-command.json','stop.stdout':'passive-session/stop.stdout',
               'post-precheck.stdout':'passive-session/post-precheck.stdout'}
        _require('post-host-state.json' in data and 'sdk-file-index.json' in data,'Operational closure index/state missing')
        pointer=json.loads(data['post-host-state.json'])['target']['descriptor']
        manifest=json.loads((Path(reference['directory'])/'manifest.json').read_bytes())
        _require(manifest['session_id']==pointer['lifecycle_id'],'Operational manifest/descriptor session contradiction')
        index=json.loads(data['sdk-file-index.json']);seen=set();destinations=set()
        for row in index:
            source=row['path'];destination=row['archive_path']
            _require(source not in seen and destination not in destinations,'Duplicate operational SDK association')
            seen.add(source);destinations.add(destination)
            _require(destination in data and row.get('stable_stat') is True and
                     row.get('truncated_prefix',False) is False and type(row.get('bytes')) is int and
                     row['bytes']==len(data[destination]) and hashlib.sha256(data[destination]).hexdigest()==row['sha256'],
                     'Operational SDK original incomplete/altered: '+source)
        for canonical,suffix in [('container-selection.json','selection.json'),('container-launch.json','launch.json'),
                                 ('container-capture/monitor.json','capture/monitor.json'),
                                 ('closure-request.json','capture/closure-request.json'),
                                 ('cleanup-finished.json','capture/cleanup-finished.json'),
                                 ('monitor-exit.json','capture/monitor_exit.json')]:
            matches=[row for row in index if row['path']==pointer['prefix']+'/'+suffix]
            _require(len(matches)==1,'Operational SDK association missing: '+suffix)
            paths[canonical]=matches[0]['archive_path']
    def read(name):
        path = paths.get(name,name) if layout in (OPERATIONAL_LAYOUT,FUNCTION_SESSION_LAYOUT) else PASSIVE_SESSION_PATHS.get(name,name) if layout else name
        _require(path in data, 'Closure original absent from manifest: '+path)
        return json.loads(data[path])
    return data,read


def _closure_operations(target,start,stop,environment):
    """Lifecycle facts shared by layouts and the current-state classifier.

    A failed start has no completion timestamp. Its own protected stop must
    retain the original operation and execution, rather than completing it.
    """
    pointer=target['descriptor'];owner=pointer['lifecycle_id'];closing=target.get('closed_by')
    _require(target.get('state')=='CLOSED' and closing==stop.get('owner_id') and closing!=owner
             and str(UUID(closing))==closing and start.get('owner_id')==owner
             and start.get('diagnostic_agent')==pointer and stop.get('diagnostic_close_target')==pointer,
             'Recorded cleanup descriptor/owner contradiction')
    failed=start.get('state')=='UNCONFIRMED'
    for op,action in ((start,'start'),(stop,'stop')):
        state='UNCONFIRMED' if failed and action=='start' else 'FINISHED'
        _require(op.get('kind')=='SIMULATION_LIFECYCLE' and op.get('state')==state
                 and op.get('action')==action and op.get('profile')=='two_drones_rover'
                 and op.get('movement_authorized') is False
                 and (state=='UNCONFIRMED' or bool(op.get('finished_at'))),
                 'Recorded lifecycle operation incomplete/contradictory')
    if failed:
        _require(stop.get('closing_failed_start')==start,'Protected-close original failed-start link changed')
        execution=start.get('environment_execution')
        _require(isinstance(execution,dict) and stop.get('environment_execution')==execution
                 and environment.get('environment')==execution.get('persistent_identity')
                 and environment.get('lifecycle_id')==owner and environment.get('profile')=='two_drones_rover'
                 and all(environment['environment'].get(k)==pointer['manifest'][k] for k in ('engine_id','container_id','image_id'))
                 and environment['pre_start_state']['StartedAt']==execution.get('container_started_at'),
                 'Protected-close environment/execution contradiction')
    return failed


def _protected_cleanup_facts(pointer,execution,launch,request,finished,report):
    """Original failed-start cleanup facts, independent of archive paths."""
    root=_process(_recorded(launch)['process']);cleanup_owner=_process(request.get('cleanup_owner'))
    _require(root['boot_id']==cleanup_owner['boot_id']==execution.get('container_boot_id'),
             'Protected-close process/boot contradiction')
    _require(request.get('lifecycle_id')==pointer['lifecycle_id'] and request.get('selection_sha256')==pointer['selection_sha256']
             and request.get('source')=='PROTECTED_PROCESS_CLEANUP'
             and {k:v for k,v in finished.items() if k not in ('finished_at_utc','infrastructure_cleanup_complete')}==request
             and finished.get('infrastructure_cleanup_complete') is True,'Protected cleanup incomplete/contradictory')
    _require(report.get('success') is True and all(report.get(k)==[] for k in ('errors','remaining','unattributed_auxiliaries')),
             'Protected cleanup partial/uncertain')
    _require(report.get('diagnostic_agent',{}).get('selection')=={**pointer,**FLAGS},
             'Protected cleanup report selection contradiction')
    _require(any(v.get('pid')==root['pid'] and v.get('start_ticks')==root['start_ticks']
                 and v.get('boot_id')==root['boot_id'] and v.get('process',{}).get('pid')==root['pid']
                 and v['process'].get('start_ticks')==root['start_ticks'] and v['process'].get('diagnostic_selection_sha256')==
                     hashlib.sha256(json.dumps(pointer,sort_keys=True,separators=(',',':')).encode()).hexdigest()
                 for v in report.get('signals',[])), 'Protected cleanup not bound to original launch/session')


def _protected_failed_archive(reference):
    """Consume original protected-close layout and explicitly bound start archive.

    This is recorded infrastructure closure, not a historical freshness verdict
    or a completion receipt from the missing monitor parent.
    """
    from datetime import datetime
    data,_=_verified_closure_data(reference)
    start_data=_manifest_data(reference['start_archive'],require_mode=False)
    def read(name):
        _require(name in data,'Protected-close original absent: '+name)
        return json.loads(data[name])
    def at(value):
        stamp=datetime.fromisoformat(value.replace('Z','+00:00'))
        _require(stamp.tzinfo is not None,'Protected-close chronology timezone missing')
        return stamp
    post=read('after-host.json');target=post['target'];pointer=target['descriptor']
    check_frozen_descriptor(pointer);owner=pointer['lifecycle_id']
    start=read('original-restriction.json');stop=read('stop-lifecycle/operation.json')
    _require(json.loads(start_data['start-lifecycle/operation.json'])==start,
             'Protected-close original start/archive link changed')
    environment=json.loads(start_data['start-lifecycle/rover_environment_reference.json'])
    index=read('after-files.json')
    def sdk(name):
        source=pointer['prefix']+'/'+name
        entries=[row for row in index if row.get('path')==source]
        _require(len(entries)==1,'Missing/ambiguous protected-close source: '+source)
        entry=entries[0];path=entry['archive_path']
        _require(path in data and not entry.get('truncated_prefix',True) and entry.get('stable_stat') is True
                 and hashlib.sha256(data[path]).hexdigest()==entry['sha256'],
                 'Protected-close source altered/incomplete: '+source)
        return json.loads(data[path])
    selection=sdk('selection.json');launch=sdk('launch.json');monitor=sdk('capture/monitor.json')
    request=_recorded(sdk('capture/closure-request.json'))
    finished=_recorded(sdk('capture/cleanup-finished.json'))
    _require(_closure_operations(target,start,stop,environment),'Protected-close start is not UNCONFIRMED')
    execution=start['environment_execution']
    _require(selection.get('descriptor')==pointer and selection.get('helpers')==pointer['helpers'],
             'Protected-close selection contradiction')
    reports=[]
    for line in data['stop-lifecycle/backend.log'].decode().splitlines():
        try:row=json.loads(line)
        except ValueError:continue
        if isinstance(row,dict) and 'signals' in row and 'remaining' in row:reports.append(row)
    _require(len(reports)==1,'Missing/ambiguous original protected cleanup result')
    report=reports[0]
    _protected_cleanup_facts(pointer,execution,launch,request,finished,report)
    response=read('protected-stop.stdout');command=read('protected-stop-command.json')
    _require(command.get('return_code')==0 and command.get('error') is None
             and response.get('success') is True and response.get('status')=='SUCCESS'
             and response.get('operation')==stop,'Protected stop response/return contradiction')
    observation=read('after-observation.json');inventory=observation['inventory']
    _require(inventory.get('boot_id')==execution['container_boot_id'] and
             all(inventory.get(k)==[] for k in ('owned','ambiguous','agents'))
             and set(inventory.get('state_files',{}))=={POINTER}
             and _recorded(json.loads(inventory['state_files'][POINTER]))==pointer
             and post.get('restriction','UNKNOWN') is None and post.get('files')=={},
             'Protected post-close inventory/restrictions incomplete')
    _require(at(start['started_at'])<=at(stop['started_at'])<=at(request['requested_at_utc'])<=
             at(finished['finished_at_utc'])<=at(stop['finished_at'])<=at(command['finished_at_utc'])<=
             at(observation['at_utc'])<=at(post['at_utc']), 'Protected-close chronology contradiction')
    _require(observation['diagnostic']['monitor']==monitor and report['diagnostic_agent']['monitor']==monitor
             and monitor.get('kind')=='PASSIVE_DIAGNOSTIC_MONITOR' and monitor.get('lifecycle_id')==owner
             and monitor.get('phase') in {'INCOMPLETE','FAILED','CLOSED'} and monitor.get('capture_complete') is False,
             'Protected-close retained monitor changed/contradictory')
    _recorded(monitor)
    return {'historical':{'target':target,'start_operation':start,'stop_operation':stop,
            'environment_reference':environment,'selection':selection,'launch':launch,'monitor':monitor},
            'limitations':{'historical_capture_complete':False,'historical_fresh_observation':None,
                'basis':'RECORDED_CLEANUP_NOT_HISTORICAL_RESOURCE_ABSENCE'}}


def verified_closure_archive(reference):
    """Historical V2 closure proof; its freshness requirement is unchanged."""
    _require(reference.get('layout')!=PROTECTED_FAILED_LAYOUT,
             'Protected failed-start archive records cleanup only; current-resource scope review required')
    _require(reference.get('layout') not in (OPERATIONAL_LAYOUT,FUNCTION_SESSION_LAYOUT),
             'Recorded cleanup archive requires current-resource scope review; historical V2 freshness not asserted')
    from datetime import datetime
    data,read=_verified_closure_data(reference)
    layout=reference.get('layout')
    def at(value):
        result=datetime.fromisoformat(value.replace('Z','+00:00'))
        _require(result.tzinfo is not None,'Unknown closure timezone');return result
    target=read('post-host-state.json')['target'];start=read('start-operation/operation.json');stop=read('stop-operation/operation.json')
    report=json.loads(data['stop-operation/backend.log'].decode().splitlines()[0])
    _require(report.get('success') is True and all(report.get(k)==[] for k in ('remaining','errors','unattributed_auxiliaries')),
             'Independent protected cleanup not verified')
    _require(read('stop-command.json')['return_code']==0 and read('stop.stdout').get('success') is True
             and read('stop.stdout')['operation']==stop,'Stop response/return/operation contradiction')
    _require(any(v.get('pid')==read('container-launch.json')['process']['pid'] and
                 v.get('start_ticks')==read('container-launch.json')['process']['start_ticks'] for v in report['signals']),
             'Cleanup not bound to original launch identity')
    inventory=(_passive_session_inventory(read,target=target,start=start,stop=stop,at=at)
               if layout else read('post-container-inventory.stdout'))
    _require(all(inventory.get(k)==[] for k in ('owned','ambiguous','agents')),'Independent post-close processes unknown/remain')
    _require(read('post-host-state.json').get('guards')=={},'Historical guards not confirmed absent')
    if layout:
        # The later read supplies inventory/provenance, not an unrecorded
        # monotonic freshness verdict. Wall chronology alone cannot replace it.
        prior = read('post-precheck.stdout')
        _require(prior.get('historical_classification',{}).get('lifecycle_id')==target['descriptor']['lifecycle_id'],
                 'Post-precheck associated with another session')
        _require(read('post-precheck-command.json')['return_code']==0 and
                 at(read('passive-session/post-precheck-timing.json')['started_at'])>=at(stop['finished_at']),
                 'Post-precheck chronology/return unknown')
        _require(prior.get('conditions',{}).get('fresh_observation') is True,
                 'Historical post-close freshness unverified: archived precheck is not fresh; '
                 'later inventory has no monotonic completion/verdict')
        _require(all(prior.get('conditions',{}).get(k) is True for k in
                     ('reader_complete','no_restrictions','no_guards','no_other_sessions','no_host_processes','host_identity_known')),
                 'Historical post-close restrictions/queries not confirmed')
    else:
        conditions=read('post-precheck.stdout')['conditions']
        _require(all(conditions.get(k) is True for k in ('fresh_observation','reader_complete','no_restrictions','no_guards','no_other_sessions','no_host_processes','host_identity_known')),
                 'Historical post-close restrictions/queries not confirmed')
        command=read('post-container-inventory-command.json')
        _require(command['return_code']==0 and at(command['started_at'])>=at(stop['finished_at'])
                 and at(read('post-precheck-command.json')['started_at'])>=at(stop['finished_at']), 'Post-close chronology unknown')
    monitor=read('container-capture/monitor.json')
    _require((monitor.get('phase') in {'INCOMPLETE','FAILED'} or monitor.get('phase')=='CLOSED' and monitor.get('capture_semantics')=='SEPARATE_CHANNELS_V2' and monitor.get('core_capture_complete') is True) and monitor.get('capture_complete') is False,
             'Not an explicitly incomplete diagnostic history')
    result={'target':target,'start_operation':start,'stop_operation':stop,
            'environment_reference':read('start-operation/rover_environment_reference.json'),
            'selection':read('container-selection.json'),'launch':read('container-launch.json'),'monitor':monitor}
    _require(target.get('state')=='CLOSED' and target.get('closed_by')==stop.get('owner_id'),'Historical target not closed by recorded stop')
    return result


def recorded_cleanup_archive(reference):
    """Recorded cleanup facts only, never a historical post-close freshness proof."""
    if reference.get('layout')==PROTECTED_FAILED_LAYOUT:return _protected_failed_archive(reference)
    data,read=_verified_closure_data(reference)
    target=read('post-host-state.json')['target'];pointer=target['descriptor']
    check_frozen_descriptor(pointer)
    start=read('start-operation/operation.json');stop=read('stop-operation/operation.json')
    selection=read('container-selection.json');launch=read('container-launch.json')
    monitor=read('container-capture/monitor.json');environment=read('start-operation/rover_environment_reference.json')
    failed_start=_closure_operations(target,start,stop,environment)
    _require(not failed_start or reference.get('layout')==OPERATIONAL_LAYOUT,
             'Protected failed-start closure evidence required')
    _require(selection.get('descriptor')==pointer and selection.get('helpers')==pointer['helpers'] and
             environment.get('lifecycle_id')==pointer['lifecycle_id'] and environment.get('profile')=='two_drones_rover' and
             all(environment['environment'][k]==pointer['manifest'][k] for k in ('engine_id','container_id','image_id')),
             'Recorded cleanup selection/environment contradiction')
    _require(monitor.get('kind')=='PASSIVE_DIAGNOSTIC_MONITOR' and monitor.get('lifecycle_id')==pointer['lifecycle_id'] and monitor.get('capture_complete') is False and
             monitor.get('phase') in {'INCOMPLETE','FAILED','CLOSED'}, 'Not an incomplete retained diagnostic')
    _recorded(launch);_recorded(monitor)
    operational=reference.get('layout')==OPERATIONAL_LAYOUT
    function_session=reference.get('layout')==FUNCTION_SESSION_LAYOUT
    report_path=('preserved/stop-lifecycle/backend.log' if function_session else
                 'stop-lifecycle/backend.log' if operational else 'stop-operation/backend.log')
    _require(report_path in data,'Closure original absent from manifest: '+report_path)
    report=json.loads(data[report_path].decode().splitlines()[0])
    _require(report.get('success') is True and all(report.get(k)==[] for k in
             ('remaining','errors','unattributed_auxiliaries')), 'Recorded independent cleanup not verified')
    response=read('stop.stdout')
    _require(read('stop-command.json').get('return_code')==0 and response.get('success') is True and
             response.get('operation')==stop, 'Recorded stop response contradiction')
    root=_process(launch['process'])
    _require(any(v.get('pid')==root['pid'] and v.get('start_ticks')==root['start_ticks'] for v in report['signals']),
             'Recorded cleanup not bound to original launch')
    prior=read('post-precheck.stdout')
    if operational or function_session:
        _operational_closure_checks(reference,data,read,target,start,stop,environment,selection,launch,monitor,report)
    return {'historical':{'target':target,'start_operation':start,'stop_operation':stop,
            'environment_reference':environment,'selection':selection,'launch':launch,'monitor':monitor},
            'limitations':{'historical_capture_complete':False,
                'historical_fresh_observation':prior.get('conditions',{}).get('fresh_observation'),
                'basis':'RECORDED_CLEANUP_NOT_HISTORICAL_RESOURCE_ABSENCE'}}


def _function_session_inventory(data,read,historical,execution,at):
    """Consume the two sealed function results as results, never as stdout.

    Bind their metadata-only query payload to the archived source before-images.
    Historical durations/conditions remain historical, not a current verdict.
    """
    pointer=historical['target']['descriptor'];prefix=pointer['prefix']
    files=[prefix+'/'+n for n in ('selection.json','launch.json','capture/monitor.json')]
    source_paths=[('/tmp/tfg_simulation_profiles.py','predeployment-originals/05-tfg_simulation_profiles.py','tools/simulation_profiles.py'),
                  ('/tmp/tfg_sim_processes.py','predeployment-originals/06-tfg_sim_processes.py','simulation/ros2_gazebo/scripts/sim_processes.py'),
                  ('/root/ardu_ws/src/ardupilot_gz/ardupilot_gz_bringup/launch/tfg_demo.launch.py',
                   'predeployment-originals/09-tfg_demo.launch.py',None)]
    index=read('predeployment-index.json')['rows'];sources=[]
    _require(len({row['path'] for row in index})==len(index),'Duplicate function-result source association')
    for path,name,key in source_paths:
        rows=[row for row in index if row['path']==path]
        _require(len(rows)==1 and name in data,'Function-result reader source missing')
        row=rows[0];content=data[name]
        _require(row.get('present') is True and row.get('stable') is True and row.get('type')=='regular'
                 and row.get('size')==len(content) and row.get('sha256')==hashlib.sha256(content).hexdigest(),
                 'Function-result reader source altered/incomplete')
        sources.append((content,key))
    final_time=None
    for name in ('post-restoration-check.function.json','post-after-restoration.function.json'):
        value=read(name)
        _require(set(value)=={'records','current','observation_context','Path_serialized_fields'} and
                 value['Path_serialized_fields']==['records.historical_evidence'],
                 'Unknown function-result representation')
        records=value['records'];current=value['current'];context=value['observation_context'];inventory=records['inventory']
        _require(all(records.get(k)==v for k,v in historical.items()),'Function-result session/descriptor association contradiction')
        _require(type(context.get('inventory_return_code')) is int and context['inventory_return_code']==0
                 and current.get('complete') is True and current['sources']==context['sources'],
                 'Function-result inventory read failed/incomplete')
        resources=current['resources'];hashes=resources['reader_hashes']
        from .present_resources import unpack, SCHEMA
        from .budget import SOCKET
        expanded=unpack(resources);reads=expanded.get('reads',[]);ids=expanded.get('table_reads',[])
        expected_tables=['/proc/self/net/'+n for n in ('udp','udp6','tcp','tcp6')]*2
        _require(expanded.get('schema')==SCHEMA and expanded.get('status')=='FREE' and
                 expanded.get('occupied')==[] and expanded.get('reasons')==[] and
                 expanded.get('budget')==SOCKET.record() and len(reads)<=SOCKET.reads and
                 expanded.get('counts',{}).get('read_calls',SOCKET.reads+1)<=SOCKET.reads and
                 len(ids)==8 and len(set(ids))==8 and
                 all(type(i) is int and 0<=i<len(reads) for i in ids) and
                 [reads[i].get('source') for i in ids]==expected_tables and
                 all(reads[i].get('operation')=='bytes_to_eof' for i in ids) and
                 all(row.get('state')=='OBSERVED' for row in reads),
                 'Function-result resource inventory incomplete/occupied')
        _require(inventory.get('resources')==resources and
                 all(key is None or hashes.get(key)==hashlib.sha256(content).hexdigest() for content,key in sources),
                 'Function-result reader provenance contradiction')
        payload={'profiles':sources[0][0].decode(),'supervisor':sources[1][0].decode(),'files':files,
                 'present':True,'reader_hashes':hashes,'host_launch':sources[2][0].decode()}
        from .selection import digest
        _require(context.get('inventory_source_sha256')==digest(payload),'Unknown function-result reader provenance')
        _require(all(inventory.get(k)==[] for k in ('owned','ambiguous','agents')) and
                 set(inventory.get('state_files',{}))=={POINTER} and
                 _recorded(json.loads(inventory['state_files'][POINTER]))==pointer and
                 set(inventory['files'])==set(files) and all(json.loads(inventory['files'][prefix+'/'+n])==historical[k]
                     for k,n in [('selection','selection.json'),('launch','launch.json'),('monitor','capture/monitor.json')]),
                 'Function-result inventory/retained files incomplete or contradictory')
        before=inventory.get('query_context_before');after=inventory.get('query_context_after')
        _require(isinstance(before,dict) and before==after and before.get('boot_id')==inventory['boot_id']==execution['container_boot_id']
                 and all(resources['context'].get(k)==v for k,v in before.items()),'Function-result query context changed')
        from tools.reconciliation_environment import active_execution_identity
        _require(context['current_environment_execution']==execution and
                 active_execution_identity(context['environment'],inventory['boot_id'])==execution and
                 active_execution_identity(context['environment_recheck'],inventory['boot_id'])==execution and
                 current['environment_observation']==context['environment'], 'Function-result environment/execution changed')
        _require(current.get('restriction','UNKNOWN') is None and current.get('guards')=={} and
                 current.get('host_processes')==[] and current.get('other_sessions')==[] and bool(current.get('host_boot_id')),
                 'Function-result restrictions/reservations/sessions incomplete')
        names=[row['source'] for row in context['sources']]
        required=['sim_processes.readonly_inventory in exact container',
                  'reconciliation_environment metadata/boot recheck after inventory',
                  'host /proc relevant role inventory; vehicle_execution_lock.process_identity',
                  'vehicle_locks/*.json and vehicle_execution_lock.restriction']
        _require(all(names.count(n)==1 for n in required) and
                 [names.index(n) for n in required]==sorted(names.index(n) for n in required),
                 'Function-result observation sources absent/out of order')
        times=[at(row['read_at_utc']) for row in context['sources']]
        _require(bool(times) and times==sorted(times) and
                 at(historical['stop_operation']['finished_at'])<=at(context['started_at_utc'])<=times[0]
                 and (final_time is None or final_time<=times[0]),'Function-result closure chronology contradiction')
        _require(at(context['environment']['finished_at_utc'])<=times[names.index(required[0])]
                 <=at(context['environment_recheck']['started_at_utc'])
                 <=at(context['environment_recheck']['finished_at_utc'])<=times[names.index(required[1])],
                 'Function-result environment observation order unproven')
        final_time=times[-1]
    return final_time


def _function_monitor_wait(data,read,pointer,monitor,receipt,finished,observed_at,at):
    """Precision-aware chronology backed by the exact monitor implementation.

    No epsilon: require its causal read/terminal snapshot/wait sequence, same
    process incarnation and a seconds-resolution wall interval containing the
    cleanup completion. Unknown producer versions remain blocked.
    """
    import math
    from datetime import timedelta
    name='preserved/sdk/overlay/monitor.py'
    known={'d71be743ea66e76c61747309a84fd055f8d83873013c7f2ab7ddfe9d8f2cad3f',
           'd53d166d8f3405110246a225376effcfcf9ace475ac8c9741ba2989bea7db5dd'}
    _require(name in data and hashlib.sha256(data[name]).hexdigest()==pointer['helpers']['monitor.py'] in known,
             'Unverified causal monitor implementation')
    supervisor=read('preserved/sdk/overlay/capture/monitor_supervisor.json')
    _recorded(supervisor)
    _require(supervisor.get('phase')=='CHILD_REAPED' and type(supervisor.get('return_code')) is int
             and supervisor['return_code']==receipt['return_code']
             and supervisor.get('child')==monitor['monitor'],'Monitor parent wait association contradiction')
    pair=(monitor.get('finished_monotonic'),receipt.get('observed_monotonic'))
    _require(all(type(v) in (int,float) and math.isfinite(v) for v in pair) and 0<=pair[0]<=pair[1]
             and monitor.get('cleanup_result')==finished and finished.get('infrastructure_cleanup_complete') is True,
             'Monitor causal closure order unproven')
    # The pinned producer uses strftime seconds, not a fractional timestamp.
    stamp=receipt['observed_at_utc'];wall=at(stamp)
    _require(wall.strftime('%Y-%m-%dT%H:%M:%SZ')==stamp and
             at(finished['finished_at_utc'])<wall+timedelta(seconds=1) and wall<=observed_at,
             'Monitor wait wall interval contradicts causal closure')


def _operational_closure_checks(reference,data,read,target,start,stop,environment,selection,launch,monitor,report):
    """Representation-specific independent receipts; no historical freshness claim."""
    from datetime import datetime
    from tools.reconciliation_environment import active_execution_identity
    def at(value):
        stamp=datetime.fromisoformat(value.replace('Z','+00:00'))
        _require(stamp.tzinfo is not None,'Operational timestamp timezone absent');return stamp
    pointer=target['descriptor'];owner=pointer['lifecycle_id'];root=_process(launch['process'])
    execution=start['environment_execution']
    _require(execution['persistent_identity']==environment['environment'] and
             execution['container_started_at']==environment['pre_start_state']['StartedAt'] and
             execution['container_boot_id']==root['boot_id'],'Operational start execution contradiction')
    request=_recorded(read('closure-request.json'));finished=_recorded(read('cleanup-finished.json'))
    if start.get('state')=='UNCONFIRMED':
        _protected_cleanup_facts(pointer,execution,launch,request,finished,report)
    cleanup_owner=_process(request['cleanup_owner'])
    _require(request.get('lifecycle_id')==owner and request.get('selection_sha256')==pointer['selection_sha256'] and
             request.get('source')=='PROTECTED_PROCESS_CLEANUP' and cleanup_owner['boot_id']==root['boot_id'] and
             {k:v for k,v in finished.items() if k not in ('finished_at_utc','infrastructure_cleanup_complete')}==request and
             finished.get('infrastructure_cleanup_complete') is True,'Operational cleanup receipts contradict/incomplete')
    _require(report['diagnostic_agent']['selection']=={**pointer,**FLAGS} and
             report['diagnostic_agent']['monitor']==monitor and monitor.get('cleanup_request')=={**request,**FLAGS} and
             monitor.get('cleanup_result')=={**finished,**FLAGS},'Operational cleanup/monitor association contradiction')
    _require(any(v.get('pid')==root['pid'] and v.get('start_ticks')==root['start_ticks'] and
                 v.get('process',{}).get('pid')==root['pid'] and v['process'].get('start_ticks')==root['start_ticks'] and
                 v['process'].get('diagnostic_selection_sha256')==hashlib.sha256(json.dumps(pointer,sort_keys=True,separators=(',',':')).encode()).hexdigest()
                 for v in report['signals']),'Operational cleanup signal session contradiction')
    function_session=reference.get('layout')==FUNCTION_SESSION_LAYOUT
    if function_session:
        historical={'target':target,'start_operation':start,'stop_operation':stop,
                    'environment_reference':environment,'selection':selection,'launch':launch,'monitor':monitor}
        observed_at=_function_session_inventory(data,read,historical,execution,at)
        post_at=observed_at
    else:
        observed=read('post-current-observation.json');inventory=observed['inventory'];post=read('post-host-state.json')
        raw_observed=read('post-current-read.stdout')
        _require({k:v for k,v in raw_observed.items() if k!='files'}==observed,
                 'Operational post-close original stdout/decoded record contradiction')
        originals={row['path']:row for row in raw_observed['files']}
        _require(len(originals)==len(raw_observed['files']),'Duplicate operational raw SDK source')
        for row in read('sdk-file-index.json'):
            source=originals.get(row['path'])
            _require(source is not None and all(source.get(k)==row.get(k) for k in ('sha256','bytes','stable_stat')),
                     'Operational SDK index/original stdout contradiction')
        ctx=observed['context_before']
        _require(ctx==observed['context_after'] and ctx['boot_id']==inventory['boot_id']==root['boot_id'] and
                 all(inventory.get(k)==[] for k in ('owned','ambiguous','agents')) and
                 set(inventory.get('state_files',{}))=={POINTER} and
                 _recorded(json.loads(inventory['state_files'][POINTER]))==pointer and
                 post.get('restriction','UNKNOWN') is None and post.get('guards')=={},'Operational post-close state/context incomplete')
        command=read('post-current-read-command.json')
        _require(command.get('return_code')==0 and command.get('error') is None,'Operational post-close query failed')
        for name in ('post-environment-before.json','post-environment-after.json'):
            _require(active_execution_identity(read(name),inventory['boot_id'])==execution,'Operational post-close environment changed')
        _require(observed['diagnostic_summary']['selection']=={**pointer,**FLAGS} and
                 observed['diagnostic_summary']['monitor']==monitor,'Operational post-close monitor contradiction')
        observed_at=at(observed['at_utc']);post_at=at(post['read_at_utc'])
    receipt=read('monitor-exit.json');watcher=_process(monitor['monitor'])
    _require(receipt==report['diagnostic_agent']['monitor_exit'] and
             (function_session or receipt==observed['diagnostic_summary']['monitor_exit']) and
             receipt.get('state')=='PARENT_WAIT_STATUS_OBSERVED' and receipt.get('source')=='RETAINED_MONITOR_PARENT_POPEN_WAIT' and
             type(receipt.get('return_code')) is int and receipt['return_code']==1 and
             all(receipt.get(k)==watcher[k] for k in ('pid','start_ticks','boot_id')),
             'Operational actual monitor wait missing/contradictory')
    if function_session:
        _function_monitor_wait(data,read,pointer,monitor,receipt,{**finished,**FLAGS},observed_at,at)
    else:
        _require(at(finished['finished_at_utc'])<=at(receipt['observed_at_utc'])<=observed_at,
                 'Operational monitor wait chronology contradiction')
    # Infrastructure closure is established by the bound cleanup, post-close
    # inventory and actual monitor wait above, not by diagnostic completeness.
    # Preserve the terminal state emitted by monitor.run, including its errors;
    # an INCOMPLETE capture may still have independently accredited cleanup.
    core=monitor.get('core_capture_complete');sockets=monitor.get('socket_capture_complete')
    errors=monitor.get('errors')
    _require(monitor.get('capture_semantics')=='SEPARATE_CHANNELS_V2' and
             type(core) is bool and type(sockets) is bool and
             isinstance(errors,list) and all(isinstance(error,str) for error in errors) and
             core==(not errors) and monitor.get('phase')==('CLOSED' if core else 'INCOMPLETE') and
             not (core and sockets) and monitor.get('capture_complete') is False and
             monitor.get('closure_requested') is True,
             'Operational separate-channel closure contradiction')
    start_bound=start['started_at'] if start.get('state')=='UNCONFIRMED' else start['finished_at']
    _require(at(start['started_at'])<=at(start_bound)<=at(stop['started_at'])<=at(request['requested_at_utc'])<=
             at(finished['finished_at_utc'])<=at(stop['finished_at'])<=observed_at<=post_at,
             'Operational closure chronology contradiction')


def _generic_closure_proof(proof_reference,**supplied):
    originals=(recorded_cleanup_archive(proof_reference)['historical']
               if proof_reference.get('layout') in (OPERATIONAL_LAYOUT,FUNCTION_SESSION_LAYOUT) else verified_closure_archive(proof_reference))
    names={'start':'start_operation','stop':'stop_operation','reference':'environment_reference'}
    for name,value in supplied.items():
        _require(originals[names.get(name,name)]==value,'Current retained record differs from reviewed closure original: '+name)


def classify_last_session(*, target, start_operation, stop_operation,
                          environment_reference, environment, inventory, selection, launch, monitor,
                          historical_evidence=None):
    """Classify supplied observations; CLEAR means this pointer alone is historical.

    Does not admit a lifecycle, authorize another opening, prove ground contact
    or validate native trace joins. Current process checks complement durable
    closure; neither CLOSED alone nor an empty process snapshot suffices.
    """
    result={'status':'BLOCKED','pointer_classification':'UNKNOWN_OR_CONTRADICTORY',
            'reasons':[], 'movement_authorized':False,'source_association_verified':False}
    try:
        _require(isinstance(inventory,dict), 'Current inventory unavailable')
        _require(all(isinstance(inventory.get(k),list) and not inventory[k]
                     for k in ('owned','ambiguous','agents')), 'Current processes remain or inventory incomplete')
        files=inventory.get('state_files')
        _require(isinstance(files,dict) and set(files)=={POINTER}, 'Other process/session state or missing pointer')
        pointer=_recorded(json.loads(files[POINTER]))
        check_frozen_descriptor(pointer)
        owner=pointer['lifecycle_id'];result['lifecycle_id']=owner
        _require(isinstance(target,dict) and target.get('state')=='CLOSED', 'Target is not confirmed CLOSED')
        _require(target.get('descriptor')==pointer, 'Pointer/target descriptor mismatch')
        closing=target.get('closed_by');_require(str(UUID(closing))==closing and closing!=owner, 'Unknown closing owner')
        _require(isinstance(start_operation,dict) and isinstance(stop_operation,dict), 'Missing lifecycle operation')
        failed_start=start_operation.get('state')=='UNCONFIRMED'
        _closure_operations(target,start_operation,stop_operation,environment_reference)
        if failed_start:
            _require(isinstance(historical_evidence,dict) and historical_evidence.get('layout') in {PROTECTED_FAILED_LAYOUT,OPERATIONAL_LAYOUT},
                     'Protected failed-start closure evidence required')
            originals=recorded_cleanup_archive(historical_evidence)['historical']
            supplied={'target':target,'start_operation':start_operation,'stop_operation':stop_operation,
                      'environment_reference':environment_reference,'selection':selection,'launch':launch,'monitor':monitor}
            _require(originals==supplied,'Protected failed-start retained records differ from originals')
        _require(isinstance(environment_reference,dict) and environment_reference.get('lifecycle_id')==owner
                 and environment_reference.get('profile')=='two_drones_rover', 'Environment reference mismatch')
        _require(isinstance(environment,dict) and environment.get('status')=='ACTIVE', 'Current environment not known ACTIVE')
        original=environment_reference['environment']
        _require(all(environment.get(k)==original[k] for k in
                     ('engine_id','container_id','image_id','name','created_at')), 'Environment identity changed')
        _require(all(environment[k]==pointer['manifest'][k] for k in
                     ('engine_id','container_id','image_id')), 'Pointer/environment identity mismatch')
        # A CLOSED historical session is assessed in ITS original proc/clock
        # context. A new execution of the same container must not rewrite it.
        from tools.reconciliation_environment import active_execution_identity
        current_execution=active_execution_identity(environment,inventory.get('boot_id'))
        historical_started_at=environment_reference['pre_start_state']['StartedAt']
        from datetime import datetime
        historical_time=datetime.fromisoformat(historical_started_at.replace('Z','+00:00'))
        _require(historical_time.tzinfo is not None, 'Historical execution timestamp unavailable')
        _require(isinstance(selection,dict) and selection.get('descriptor')==pointer and
                 selection.get('helpers')==pointer['helpers'], 'Overlay selection mismatch')
        complete = (isinstance(monitor,dict) and monitor.get('kind')=='PASSIVE_DIAGNOSTIC_MONITOR'
                    and monitor.get('lifecycle_id')==owner and monitor.get('phase')=='CLOSED'
                    and monitor.get('capture_complete') is True and monitor.get('closure_requested') is True
                    and monitor.get('errors')==[])
        if not complete and not failed_start:
            generic=isinstance(historical_evidence,dict) and historical_evidence.get('kind')=='VERIFIED_CLOSURE_ARCHIVE_V2'
            _require(generic or owner in (HISTORICAL_OWNER,FAILED_OWNER) and historical_evidence is not None,
                     'Monitor closure absent/incomplete/contradictory')
            proof=_generic_closure_proof if generic else _timeout_closure_proof if owner==HISTORICAL_OWNER else _failed_closure_proof
            proof(historical_evidence, target=target, start=start_operation,
                stop=stop_operation, reference=environment_reference, selection=selection,
                launch=launch, monitor=monitor)
        _recorded(monitor);root=_process(_recorded(launch).get('process'))
        agent=_process(monitor.get('agent'));watcher=_process(monitor.get('monitor'))
        _require(all(p['boot_id']==root['boot_id'] for p in (agent,watcher)),
                 'Historical process boot contexts contradict each other')
        result['execution_context']={
            'persistent_identity_verified':True,
            'historical':{'container_started_at':historical_started_at,'container_boot_id':root['boot_id']},
            'current':current_execution,
            'container_reexecuted':historical_started_at!=current_execution['container_started_at'],
            'container_boot_changed':root['boot_id']!=current_execution['container_boot_id'],
            'historical_pids_used_as_current':False,
            'historical_monitor_phase':monitor['phase'],
            'historical_capture_complete':monitor['capture_complete']}
        if result['execution_context']['container_reexecuted'] or result['execution_context']['container_boot_changed']:
            result['execution_context']['relationship']='CLOSED_HISTORY_DIFFERENT_EXECUTION_CONTEXT'
        else:result['execution_context']['relationship']='CLOSED_HISTORY_SAME_EXECUTION_CONTEXT'
        _require(agent.get('executable')==pointer['prefix']+'/lib/micro_ros_agent/micro_ros_agent'
                 and agent.get('mapped_native_library')==pointer['prefix']+'/lib/libmicroxrcedds_agent.so.2.4'
                 and agent.get('library_sha256')==pointer['manifest']['library_sha256'], 'Receipt artifact identity differs')
        result['start_outcome']='FAILED_START_INFRASTRUCTURE_CLOSED' if failed_start else 'COMPLETED_START_CLOSED'
        if complete:
            result.update(status='CLEAR',pointer_classification='HISTORICAL_CLOSED_POINTER',closed_by=closing)
        else:
            result.update(pointer_classification='HISTORICAL_INFRASTRUCTURE_CLOSED_DIAGNOSTICS_INCOMPLETE',
                          infrastructure_closure='VERIFIED_FROM_RECORDS', diagnostic_capture='INCOMPLETE',
                          requires_explicit_scope_review=True, closed_by=closing)
            result['reasons'].append('Historical diagnostics incomplete; separate scope review required')
    except (OSError,ValueError,KeyError,TypeError,AttributeError) as exc:
        result['reasons'].append(str(exc))
    return result
