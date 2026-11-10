"""Offline /tmp protocol tests; historical records are fixtures, not live reads."""
import copy
import json
from pathlib import Path
import pytest
from tools.rover_xrce_trace.historical_disposition import OfflineDisposition,dry_run
from tools.rover_xrce_trace.session_precheck import POINTER,HISTORICAL_OWNER

@pytest.fixture
def records():
    root=Path(__file__).resolve().parents[1]/'simulation/ros2_gazebo/results/rover_xrce_trial_2026_10_24/b9ee5ec5-049d-47cc-b22f-26535b972b5f'
    def read(p):return json.loads((root/p).read_bytes())
    target=read('host_state_after.json')['target'];pointer=target['descriptor']
    prefix='container_after/container_copies'+pointer['prefix']+'/'
    return dict(target=target,start_operation=read('runtime_copies/start/operation.json'),
        stop_operation=read('runtime_copies/stop/operation.json'),
        environment_reference=read('runtime_copies/start/rover_environment_reference.json'),
        environment=read('environment_after.json'),historical_evidence=root,
        selection=read(prefix+'selection.json'),launch=read(prefix+'launch.json'),
        monitor=read(prefix+'capture/monitor.json'),inventory=dict(owned=[],ambiguous=[],agents=[],
        boot_id='51f3835d-91d2-4044-a115-2dcb8c14768a',state_files={POINTER:json.dumps({**pointer,
        'status':'BLOCKED','movement_authorized':False,'source_association_verified':False})}))

@pytest.fixture
def current():
    return dict(observed_monotonic=10,complete=True,restriction=None,guards={},
                other_sessions=[],host_processes=[],host_boot_id='fixture-host')

def scope(records,current):
    return dry_run(records,current,now=10)['scope_sha256']

def auth(value):return f'AUTHORIZE_DIAGNOSTIC_DISPOSITION {HISTORICAL_OWNER} {value}'

def test_full_flow_is_not_admission(records,current,tmp_path):
    before=copy.deepcopy(records)
    root=tmp_path/'disposition';engine=OfflineDisposition(root,clock=lambda:10)
    report=dry_run(records,current,now=10)
    assert report['status']=='DRY_RUN_ELIGIBLE' and not root.exists()
    key=report['scope_sha256']
    result=engine.apply(records,lambda:current,scope_sha256=key,authorization=auth(key))
    assert result['status']=='DISPOSED_DIAGNOSTICALLY_INCOMPLETE'
    assert not result['opening_authorized'] and not result['movement_authorized']
    assert result==engine.query() and records==before
    before_files={p.name:p.read_bytes() for p in root.iterdir()}
    assert engine.apply(records,lambda:pytest.fail('repeat must query only'),scope_sha256=key,authorization=auth(key))==result
    assert before_files=={p.name:p.read_bytes() for p in root.iterdir()}
    assert records['monitor']['capture_complete'] is False

@pytest.mark.parametrize('kind',['authorization','guards','process','unknown','stale','descriptor','changed'])
def test_fail_closed(records,current,tmp_path,kind):
    key=scope(records,current);authorization=auth(key)
    if kind=='authorization':authorization=authorization.replace(HISTORICAL_OWNER,'other-owner')
    elif kind=='guards':current['guards']={'lifecycle':'UNCONFIRMED'}
    elif kind=='process':current['host_processes']=[{'pid':44}]
    elif kind=='unknown':current.pop('complete')
    elif kind=='stale':current['observed_monotonic']=0
    elif kind=='descriptor':records['target']['descriptor']['lifecycle_id']='other'
    calls=[]
    def reader():
        calls.append(1)
        if kind=='changed' and len(calls)>1:return {**current,'other_sessions':['new-session']}
        return current
    engine=OfflineDisposition(tmp_path/'audit',clock=lambda:10)
    with pytest.raises(ValueError):engine.apply(records,reader,scope_sha256=key,authorization=authorization)
    assert engine.query()['status']=='NOT_ATTEMPTED'

@pytest.mark.parametrize('failure',[OSError,KeyboardInterrupt])
@pytest.mark.parametrize('stage',[1,2])
def test_partial_persistence_blocks_replay(records,current,tmp_path,failure,stage):
    from tools.vehicle_execution_lock import atomic_json
    writes=[]
    def write(path,value):
        writes.append(path)
        if len(writes)==stage:raise failure('injected')
        atomic_json(path,value)
    key=scope(records,current)
    engine=OfflineDisposition(tmp_path/'audit',clock=lambda:10,write=write)
    with pytest.raises(failure):engine.apply(records,lambda:current,scope_sha256=key,authorization=auth(key))
    assert engine.query()['status']=='APPLYING_UNCONFIRMED'
    with pytest.raises(ValueError):engine.apply(records,lambda:current,scope_sha256=key,authorization=auth(key))


def test_no_runtime_store_and_unknown_real_dry_run(records):
    with pytest.raises(ValueError):OfflineDisposition(Path('missions/generated/dispositions'))
    result=dry_run(records,now=10)
    assert result['status']=='BLOCKED' and result['unknown_fields']


def test_failure_after_final_replace_is_still_uncertain(records,current,tmp_path):
    from tools.vehicle_execution_lock import atomic_json
    def write(path,value):
        atomic_json(path,value)
        if path.name=='intent.json':raise OSError('simulated final fsync/close acknowledgement failure')
    engine=OfflineDisposition(tmp_path/'audit',clock=lambda:10,write=write)
    key=scope(records,current)
    with pytest.raises(OSError):engine.apply(records,lambda:current,scope_sha256=key,authorization=auth(key))
    assert engine.query()['status']=='APPLYING_UNCONFIRMED'


def test_other_disposition_or_modified_archive_not_reused(records,current,tmp_path):
    engine=OfflineDisposition(tmp_path/'audit',clock=lambda:10)
    key=scope(records,current)
    engine.apply(records,lambda:current,scope_sha256=key,authorization=auth(key))
    with pytest.raises(ValueError):engine.apply(records,lambda:current,scope_sha256='other',authorization=auth('other'))
    (engine.root/'originals.json').write_text('{}')
    assert engine.query()['status']=='APPLYING_UNCONFIRMED'


def test_competing_apply_excluded_without_sleeps(records,current,tmp_path):
    from tools.vehicle_execution_lock import VehicleBusy,file_mutex
    engine=OfflineDisposition(tmp_path/'audit',clock=lambda:10)
    engine.root.mkdir()
    key=scope(records,current)
    with file_mutex(engine.root/'v1.execution.lock'):
        with pytest.raises(VehicleBusy):engine.apply(records,lambda:current,scope_sha256=key,authorization=auth(key))
    assert engine.query()['status']=='NOT_ATTEMPTED'


def test_archived_cli_assessment_does_not_promote_old_inventory(records):
    from tools.rover_xrce_trace.historical_disposition import historical_dry_run
    result=historical_dry_run(records['historical_evidence'])
    assert result['conditions']['historical_proof'] is True
    assert result['status']=='BLOCKED' and result['unknown_fields']


def test_project_path_reuses_actual_lock_locations_in_temporary_project(records,current,tmp_path,monkeypatch):
    from tools.rover_xrce_trace import historical_disposition as d
    lock_root=tmp_path/'project'/'vehicle_locks';lock_root.mkdir(parents=True)
    monkeypatch.setattr(d.locks,'LOCK_ROOT',lock_root)
    monkeypatch.setattr(d,'current_records',lambda context=None:(copy.deepcopy(records),copy.deepcopy(current)))
    engine=d.ProjectDisposition();engine.clock=lambda:10
    key=scope(records,current)
    result=engine.apply_reviewed(scope_sha256=key,authorization=auth(key))
    assert result['status']=='DISPOSED_DIAGNOSTICALLY_INCOMPLETE'
    assert result['offline_only'] is False
    assert (lock_root/'registry.lock').exists()
    assert (lock_root/'v1.execution.lock').exists()
    assert not (engine.root/'registry.lock').exists()
    assert not list(lock_root.glob('*.json'))
    assert engine.query()==result


def test_current_dry_run_query_failure_is_not_absence(tmp_path,monkeypatch):
    from tools.rover_xrce_trace import historical_disposition as d
    lock_root=tmp_path/'locks';lock_root.mkdir()
    for n in ('v1.execution.lock','registry.lock'):(lock_root/n).touch()
    monkeypatch.setattr(d.locks,'LOCK_ROOT',lock_root)
    def failed(context=None):
        context['environment']={'status':'DOCKER_UNAVAILABLE'}
        raise ValueError('query failed, inventory unknown')
    monkeypatch.setattr(d,'current_records',failed)
    result=d.real_dry_run()
    assert result['status']=='BLOCKED' and result['observation_context']['environment']['status']=='DOCKER_UNAVAILABLE'
    assert sorted(p.name for p in lock_root.iterdir())==['registry.lock','v1.execution.lock']


def test_current_dry_run_stopped_is_distinct_from_query_failure(tmp_path,monkeypatch):
    from tools.rover_xrce_trace import historical_disposition as d
    lock_root=tmp_path/'locks';lock_root.mkdir()
    for n in ('v1.execution.lock','registry.lock'):(lock_root/n).touch()
    monkeypatch.setattr(d.locks,'LOCK_ROOT',lock_root)
    monkeypatch.setattr(d,'current_records',lambda context=None:({},dict(environment_observation={'status':'STOPPED'})))
    result=d.real_dry_run()
    assert result['status']=='BLOCKED' and result['current']['environment_observation']['status']=='STOPPED'


def test_future_consumption_never_reuses_stale_current_reads(records,current,tmp_path):
    from tools.rover_xrce_trace.historical_disposition import assess_disposition
    engine=OfflineDisposition(tmp_path/'audit',clock=lambda:10)
    key=scope(records,current)
    audit=engine.apply(records,lambda:current,scope_sha256=key,authorization=auth(key))
    report=assess_disposition(records,current,audit,now=10)
    assert report['historical_pointer_resolved'] and not report['opening_authorized']
    assert not assess_disposition(records,current,audit,now=14)['historical_pointer_resolved']
    current['guards']={'v3.json':'UNCONFIRMED'}
    assert not assess_disposition(records,current,audit,now=10)['historical_pointer_resolved']


def test_supplied_dry_run_metadata_does_not_change_stable_scope(records,current):
    first=dry_run(records,{**current,'sources':[{'read_at_utc':'one'}]},now=10)
    second=dry_run(records,{**current,'sources':[{'read_at_utc':'two'}]},now=10)
    assert first['scope_sha256']==second['scope_sha256']


def test_public_supervisor_inventory_reuses_ownership_and_propagates_failures(tmp_path,monkeypatch):
    import simulation.ros2_gazebo.scripts.sim_processes as supervisor
    process=supervisor.Process(42,1,123,('micro_ros_agent','udp4'))
    monkeypatch.setattr(supervisor,'snapshot',lambda:{42:process})
    monkeypatch.setattr(supervisor,'remembered_identities',lambda:set())
    monkeypatch.setattr(supervisor,'select_owned',lambda table,remembered:{42:process})
    monkeypatch.setattr(supervisor,'unattributed_auxiliaries',lambda table,owned:[])
    for key in ('STATE','PID_FILE','DIAGNOSTIC_STATE'):monkeypatch.setattr(supervisor,key,tmp_path/key)
    result=supervisor.readonly_inventory()
    assert result['owned'][0]['start_ticks']==123 and result['agents'][0]['pid']==42
    assert not list(tmp_path.iterdir())
    def denied():raise PermissionError('proc unavailable')
    monkeypatch.setattr(supervisor,'snapshot',denied)
    with pytest.raises(PermissionError):supervisor.readonly_inventory()


@pytest.fixture
def reviewed_scope():
    """Replay recorded real scope/audit as a fixture; freshness is simulated only."""
    from tools.rover_xrce_trace import historical_disposition as d
    root=Path(__file__).resolve().parents[1]
    r=root/'simulation/ros2_gazebo/results/rover_xrce_pointer_review_2026_10_24'
    report=json.loads((r/'disposition_integration_20261024/current_dry_run.json').read_bytes())
    audit=json.loads((r/'disposition_application_20261024/audit_copy/intent.json').read_bytes())
    scope=copy.deepcopy(report['scope']);current=scope.pop('current')
    scope.pop('historical_manifest_sha256')
    scope['historical_evidence']=d.EVIDENCE
    current['observed_monotonic']=10
    return scope,current,audit


def test_exact_reviewed_disposition_satisfies_only_diagnostic_precheck(reviewed_scope):
    from tools.rover_xrce_trace import historical_disposition as d
    records,current,audit=reviewed_scope
    before=copy.deepcopy(reviewed_scope)
    result=d.diagnostic_precheck(records,current,audit,now=10)
    assert result['status']=='SATISFIED' and result['disposition_consumed']
    assert result['historical_classification']['status']=='BLOCKED'
    assert records['monitor']['phase']=='INCOMPLETE' and records['monitor']['capture_complete'] is False
    assert not result['movement_authorized'] and not result['opening_authorized']
    assert reviewed_scope==before


@pytest.mark.parametrize('change',['missing','audit_hash','audit_scope','audit_flag','offline','owner',
    'engine','stale','guard','process','target_active','monitor','different_reviewed_scope'])
def test_diagnostic_disposition_never_hides_changed_context(reviewed_scope,change):
    from tools.rover_xrce_trace import historical_disposition as d
    records,current,audit=reviewed_scope
    if change=='missing':audit={}
    elif change=='audit_hash':audit['scope_sha256']='0'*64
    elif change=='audit_scope':audit['scope']['monitor']['capture_complete']=True
    elif change=='audit_flag':audit['movement_authorized']=True
    elif change=='offline':audit['offline_only']=True
    elif change=='owner':audit['owner_id']='another-owner'
    elif change=='engine':records['environment']['engine_id']='other'
    elif change=='stale':current['observed_monotonic']=0
    elif change=='guard':current['guards']={'v3.json':'UNCONFIRMED'}
    elif change=='process':records['inventory']['ambiguous']=[{'pid':2}]
    elif change=='target_active':records['target']['state']='STARTED'
    elif change=='monitor':records['monitor']['capture_complete']=True
    else:
        audit['scope']['current']['host_boot_id']='other'
        audit['scope_sha256']=d.digest(audit['scope'])
        audit['authorization']=auth(audit['scope_sha256'])
    result=d.diagnostic_precheck(records,current,audit,now=10)
    assert result['status']=='BLOCKED' and not result['precheck_satisfied']
    assert not result['opening_authorized']


@pytest.mark.parametrize('action',['start','restart'])
@pytest.mark.parametrize('satisfied',[False,True])
def test_lifecycle_consumes_under_exclusion_before_any_backend(reviewed_scope,tmp_path,monkeypatch,action,satisfied):
    from tools import simulation_lifecycle as life,vehicle_execution_lock as locks
    from tools.rover_xrce_trace import historical_disposition as d
    records,current,audit=reviewed_scope
    locks.LOCK_ROOT.parent.mkdir(parents=True,exist_ok=True)
    (locks.LOCK_ROOT.parent/'diagnostic_agent_session.json').write_text(json.dumps(records['target']))
    seen=[]
    def precheck(*,expected_target):
        assert expected_target==records['target']
        assert not (locks.LOCK_ROOT/'lifecycle.json').exists()
        for name in ('v1.execution.lock','registry.lock'):
            with pytest.raises(locks.VehicleBusy):
                with locks.file_mutex(locks.LOCK_ROOT/name,blocking=False):pass
        seen.append('checked')
        return {'precheck_satisfied':satisfied,'reason':'fixture decision',
                'current_environment_execution':{'fixture':'current execution'}}
    monkeypatch.setattr(d,'diagnostic_precheck_locked',precheck)
    monkeypatch.setattr(life,'assert_environment_execution',lambda value:None)
    def backend(step,*args):seen.append(step);return 0
    monkeypatch.setattr(life,'_backend',backend)
    result=life.run_lifecycle(action,profile='two_drones_rover')
    assert result['success'] is satisfied
    assert seen==(['checked']+(['stop','start'] if action=='restart' else ['start']) if satisfied else ['checked'])
    assert not (locks.LOCK_ROOT/'lifecycle.json').exists()


def test_standalone_precheck_and_lifecycle_use_same_reader_and_audit(reviewed_scope,monkeypatch):
    from tools.rover_xrce_trace import historical_disposition as d
    records,current,audit=reviewed_scope
    monkeypatch.setattr(d,'current_records',lambda context=None:(copy.deepcopy(records),copy.deepcopy(current)))
    monkeypatch.setattr(d.ProjectDisposition,'query',lambda self:copy.deepcopy(audit))
    monkeypatch.setattr(d.time,'monotonic',lambda:10)
    result=d.diagnostic_precheck_locked(expected_target=records['target'])
    assert result['precheck_satisfied']
    assert d.diagnostic_precheck_locked(expected_target={})['status']=='BLOCKED'

@pytest.mark.parametrize('state',['STOPPED','DOCKER_UNAVAILABLE','UNKNOWN'])
def test_partial_current_reader_does_not_invoke_classifier(monkeypatch, state):
    from tools.rover_xrce_trace import historical_disposition as d
    def reader(context):
        context['environment']={'status':state}
        return {'target':{}}, {'complete':False,'environment_observation':{'status':state}}
    monkeypatch.setattr(d,'current_records',reader)
    monkeypatch.setattr(d.ProjectDisposition,'query',lambda self:{})
    monkeypatch.setattr(d,'classify_last_session',lambda **kw:pytest.fail('partial records classified'))
    result=d.diagnostic_precheck_locked()
    assert result['status']=='BLOCKED' and state in result['reason']
    assert result['environment_status']==state and not result['precheck_satisfied']


def test_partial_records_without_environment_block_before_classifier(monkeypatch):
    from tools.rover_xrce_trace import historical_disposition as d
    monkeypatch.setattr(d,'current_records',lambda context:({'target':{}},{}))
    monkeypatch.setattr(d.ProjectDisposition,'query',lambda self:{})
    monkeypatch.setattr(d,'classify_last_session',lambda **kw:pytest.fail('partial classified'))
    assert 'Incomplete current records' in d.diagnostic_precheck_locked()['reason']


def test_precheck_does_not_hide_programming_typeerror(records,current,monkeypatch):
    from tools.rover_xrce_trace import historical_disposition as d
    monkeypatch.setattr(d,'current_records',lambda context:(records,current))
    monkeypatch.setattr(d.ProjectDisposition,'query',lambda self:{})
    def broken(**kw):raise TypeError('programming defect')
    monkeypatch.setattr(d,'classify_last_session',broken)
    with pytest.raises(TypeError,match='programming defect'):d.diagnostic_precheck_locked()


def test_environment_changed_during_current_reads_blocks(monkeypatch):
    from tools.rover_xrce_trace import historical_disposition as d
    def changed(context):
        context['environment']={'status':'ACTIVE'}
        raise ValueError('Current container execution changed during inventory')
    monkeypatch.setattr(d,'current_records',changed)
    result=d.diagnostic_precheck_locked()
    assert result['status']=='BLOCKED' and 'changed during inventory' in result['reason']

@pytest.mark.parametrize('state',['STOPPED','DOCKER_UNAVAILABLE','UNKNOWN','MISMATCH'])
def test_real_reader_partial_environment_path(records, tmp_path, monkeypatch, state):
    """Exercise actual current_records -> locked precheck, no Docker/ROS execution."""
    from tools.rover_xrce_trace import historical_disposition as d
    from tools import reconciliation_environment as env
    root=tmp_path/'runtime';lock=root/'vehicle_locks';lock.mkdir(parents=True)
    monkeypatch.setattr(d.locks,'LOCK_ROOT',lock)
    target=records['target'];owner=target['descriptor']['lifecycle_id'];closing=target['closed_by']
    (root/'diagnostic_agent_session.json').write_text(json.dumps(target))
    for identity, values in [(owner,{'operation.json':records['start_operation'],
                                    'rover_environment_reference.json':records['environment_reference']}),
                             (closing,{'operation.json':records['stop_operation']})]:
        directory=root/'simulation_lifecycle'/identity;directory.mkdir(parents=True,exist_ok=True)
        for name,value in values.items():(directory/name).write_text(json.dumps(value))
    observed={'status':state}
    if state=='MISMATCH':observed={'status':'ACTIVE',**target['descriptor']['manifest'],'engine_id':'other-engine'}
    monkeypatch.setattr(env,'inspect_environment',lambda:observed)
    monkeypatch.setattr(d.ProjectDisposition,'query',lambda self:{})
    monkeypatch.setattr(d,'classify_last_session',lambda **kw:pytest.fail('No inventory, no classification'))
    result=d.diagnostic_precheck_locked()
    assert result['status']=='BLOCKED'
    assert ('identity mismatch' in result['reason']) if state=='MISMATCH' else state in result['reason']
    assert not (root/'historical_dispositions').exists()

@pytest.fixture
def failed_records():
    from tools.rover_xrce_trace import historical_disposition as d
    root=Path(__file__).resolve().parents[1]/'simulation/ros2_gazebo/results/rover_xrce_trial_2026_10_25/0f678646-fe41-47b0-ba33-20fad1ae873e'
    return d.historical_records(root)


def test_failed_originals_review_is_not_application_or_monitor_closure(failed_records,current,tmp_path):
    from tools.rover_xrce_trace import historical_disposition as d
    result=d.dry_run(failed_records,current,now=10)
    assert result['status']=='DRY_RUN_ELIGIBLE',result['classification']
    assert failed_records['monitor']['phase']=='FAILED' and failed_records['monitor']['capture_complete'] is False
    engine=d.OfflineDisposition(tmp_path/'new-audit',owner=d.FAILED_OWNER,clock=lambda:10)
    old=f'AUTHORIZE_DIAGNOSTIC_DISPOSITION {d.HISTORICAL_OWNER} {result["scope_sha256"]}'
    with pytest.raises(ValueError,match='Exact scope'):engine.apply(failed_records,lambda:current,scope_sha256=result['scope_sha256'],authorization=old)
    auth=f'AUTHORIZE_DIAGNOSTIC_DISPOSITION {d.FAILED_OWNER} {result["scope_sha256"]}'
    audit=engine.apply(failed_records,lambda:current,scope_sha256=result['scope_sha256'],authorization=auth)
    assert audit==engine.query() and audit['owner_id']==d.FAILED_OWNER
    assert failed_records['monitor']['phase']=='FAILED'
    assert not d.assess_disposition(failed_records,current,{**audit,'owner_id':d.HISTORICAL_OWNER},now=10)['historical_pointer_resolved']


@pytest.mark.parametrize('kind',['altered','missing','closure','environment','ambiguous'])
def test_failed_review_rejects_changes(failed_records,current,tmp_path,kind):
    from tools.rover_xrce_trace import historical_disposition as d
    import shutil
    if kind in ('altered','missing'):
        dest=tmp_path/'originals';shutil.copytree(failed_records['historical_evidence'],dest)
        p=dest/'runtime-copies/stop/backend.log'
        if kind=='missing':p.unlink()
        else:p.write_bytes(p.read_bytes()+b'changed')
        failed_records['historical_evidence']=dest
    elif kind=='closure':failed_records['stop_operation']['state']='UNCONFIRMED'
    elif kind=='environment':failed_records['environment']['engine_id']='different'
    else:failed_records['inventory']['ambiguous']=[{'pid':999}]
    assert d.dry_run(failed_records,current,now=10)['status']=='BLOCKED'


def test_failed_case_project_route_is_owner_scoped_and_temp_only(failed_records,current,tmp_path,monkeypatch):
    from tools.rover_xrce_trace import historical_disposition as d
    root=tmp_path/'project'/'vehicle_locks';root.mkdir(parents=True)
    monkeypatch.setattr(d.locks,'LOCK_ROOT',root)
    monkeypatch.setattr(d,'current_records',lambda context=None:(copy.deepcopy(failed_records),copy.deepcopy(current)))
    report=d.dry_run(failed_records,current,now=10)
    engine=d.ProjectDisposition(d.FAILED_OWNER);engine.clock=lambda:10
    audit=engine.apply_reviewed(scope_sha256=report['scope_sha256'],authorization=f'AUTHORIZE_DIAGNOSTIC_DISPOSITION {d.FAILED_OWNER} {report["scope_sha256"]}')
    assert audit['offline_only'] is False and audit==engine.query()
    assert not (root.parent/'historical_dispositions'/d.HISTORICAL_OWNER).exists()
    decision=d.diagnostic_precheck(failed_records,current,audit,now=10)
    assert decision['precheck_satisfied'] and not decision['opening_authorized']
    assert not d.diagnostic_precheck(failed_records,{**current,'guards':{'lifecycle':'UNCONFIRMED'}},audit,now=10)['precheck_satisfied']
