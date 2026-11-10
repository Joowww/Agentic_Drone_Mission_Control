"""Pure classification tests: no Docker, processes, ROS or runtime mutations."""
import copy
import json
from pathlib import Path
import pytest
from tools.rover_xrce_trace.session_precheck import classify_last_session, POINTER

ROOT=Path(__file__).resolve().parents[1]
TRIAL=ROOT/'simulation/ros2_gazebo/results/rover_xrce_trial_2026_10_24/eb113b19-4923-4983-bed4-2e99db1aa512'
OWNER='18a9a8f0-17a3-488e-8083-da38bbe4c00a'


@pytest.fixture
def records():
    # Retained immutable evidence is read, never recreated or altered.
    def read(path):return json.loads((TRIAL/path).read_bytes())
    start=read(Path('lifecycle_start_result.json'))['operation']
    stop=read(Path('lifecycle_stop_result.json'))['operation']
    pointer=start['diagnostic_agent']
    prefix=Path('container_after/container_copies/tmp/tfg_diagnostic_agents')/OWNER
    env=read(Path('environment_after.json'))
    return dict(target={'state':'CLOSED','descriptor':pointer,'closed_by':stop['owner_id']},
        start_operation=start,stop_operation=stop,
        environment_reference={'lifecycle_id':OWNER,'profile':'two_drones_rover',
            'environment':{k:env[k] for k in ('engine_id','container_id','image_id','name','created_at')},
            'pre_start_state':env['state']},environment=env,
        inventory={'owned':[],'ambiguous':[],'agents':[],
            'boot_id':'51f3835d-91d2-4044-a115-2dcb8c14768a',
            'state_files':{POINTER:json.dumps({**pointer,'status':'BLOCKED','movement_authorized':False,'source_association_verified':False})}},
        selection=read(prefix/'selection.json'),launch=read(prefix/'launch.json'),monitor=read(prefix/'capture/monitor.json'))


def test_closed_historical_pointer_is_not_an_active_guard(records):
    before=copy.deepcopy(records)
    result=classify_last_session(**records)
    assert result['status']=='CLEAR',result
    assert result['pointer_classification']=='HISTORICAL_CLOSED_POINTER'
    assert result['movement_authorized'] is False and records==before


@pytest.mark.parametrize('state',['STARTED','OPENING','UNCONFIRMED',None])
def test_active_uncertain_or_unknown_target_blocks(records,state):
    records['target']['state']=state
    assert classify_last_session(**records)['status']=='BLOCKED'


@pytest.mark.parametrize('case',['corrupt','unknown','different_descriptor','missing_stop','failed_stop',
 'wrong_close_owner','missing_monitor','incomplete_monitor','monitor_errors','wrong_overlay',
 'process','state_file','engine','container','image','incarnation','boot','receipt_library'])
def test_missing_changed_or_contradictory_evidence_stays_blocked(records,case):
    if case=='corrupt':records['inventory']['state_files'][POINTER]='{'
    elif case=='unknown':records['inventory']['state_files'][POINTER]='{}'
    elif case=='different_descriptor':records['target']['descriptor']={}
    elif case=='missing_stop':records['stop_operation']=None
    elif case=='failed_stop':records['stop_operation']['state']='UNCONFIRMED'
    elif case=='wrong_close_owner':records['target']['closed_by']=OWNER
    elif case=='missing_monitor':records['monitor']=None
    elif case=='incomplete_monitor':records['monitor']['capture_complete']=False
    elif case=='monitor_errors':records['monitor']['errors']=['uncertain']
    elif case=='wrong_overlay':records['selection']['descriptor']={}
    elif case=='process':records['inventory']['owned']=[{'pid':1}]
    elif case=='state_file':records['inventory']['state_files']['/tmp/tfg_demo.pid']='1'
    elif case in {'engine','container','image'}:records['environment'][case+'_id']='changed'
    elif case=='incarnation':records['environment']=copy.deepcopy(records['environment']);records['environment']['state']['StartedAt']='changed'
    elif case=='boot':records['inventory']['boot_id']=None
    else:records['monitor']['agent']['library_sha256']='changed'
    assert classify_last_session(**records)['status']=='BLOCKED',case


@pytest.fixture
def timeout_records():
    """Immutable b9ee historical fixture; supplied inventory is recorded, NOT current."""
    trial=TRIAL.parent/'b9ee5ec5-049d-47cc-b22f-26535b972b5f'
    def read(name):return json.loads((trial/name).read_bytes())
    start=read('runtime_copies/start/operation.json')
    pointer=start['diagnostic_agent']
    prefix='container_after/container_copies'+pointer['prefix']+'/'
    return dict(target=read('host_state_after.json')['target'],start_operation=start,
        stop_operation=read('runtime_copies/stop/operation.json'),
        environment_reference=read('runtime_copies/start/rover_environment_reference.json'),
        environment=read('environment_after.json'),
        inventory=dict(owned=[],ambiguous=[],agents=[],
            boot_id='51f3835d-91d2-4044-a115-2dcb8c14768a',
            state_files={POINTER:json.dumps({**pointer,**{'status':'BLOCKED',
                'movement_authorized':False,'source_association_verified':False}})}),
        selection=read(prefix+'selection.json'),launch=read(prefix+'launch.json'),
        monitor=read(prefix+'capture/monitor.json'),historical_evidence=trial)


def test_real_timeout_fixture_classifies_without_admitting_or_mutating(timeout_records):
    before=copy.deepcopy(timeout_records)
    without=dict(timeout_records);without.pop('historical_evidence')
    assert classify_last_session(**without)['pointer_classification']=='UNKNOWN_OR_CONTRADICTORY'
    result=classify_last_session(**timeout_records)
    assert result['pointer_classification']=='HISTORICAL_INFRASTRUCTURE_CLOSED_DIAGNOSTICS_INCOMPLETE',result
    assert result['status']=='BLOCKED' and result['requires_explicit_scope_review']
    assert result['movement_authorized'] is False and result['source_association_verified'] is False
    assert timeout_records==before and timeout_records['monitor']['capture_complete'] is False
    assert classify_last_session(**timeout_records)==result


@pytest.mark.parametrize('case',['stop','owner','environment','monitor','process','guard','library'])
def test_timeout_exception_does_not_hide_contradictions(timeout_records,case):
    r=timeout_records
    if case=='stop':r['stop_operation']['state']='UNCONFIRMED'
    elif case=='owner':r['target']['closed_by']=OWNER
    elif case=='environment':r['environment']['engine_id']='different'
    elif case=='monitor':r['monitor']['errors'].append('unexplained')
    elif case=='process':r['inventory']['ambiguous']=[{'pid':4}]
    elif case=='guard':r['inventory']['state_files']['/tmp/tfg_demo.pid']='4'
    else:r['monitor']['agent']['library_sha256']='0'*64
    result=classify_last_session(**r)
    assert result['status']=='BLOCKED' and result['pointer_classification']=='UNKNOWN_OR_CONTRADICTORY'


@pytest.mark.parametrize('change',['manifest','original','missing'])
def test_timeout_proof_rejects_tampered_originals(timeout_records,tmp_path,change):
    import shutil
    source=timeout_records['historical_evidence']
    # Only a disposable fixture copy is changed; originals are never written.
    shutil.copytree(source,tmp_path/'fixture',ignore=shutil.ignore_patterns('__pycache__'))
    root=tmp_path/'fixture'
    p=root/('manifest.json' if change=='manifest' else 'runtime_copies/stop/backend.log')
    if change=='missing':p.unlink()
    else:p.write_bytes(p.read_bytes()+b' ')
    timeout_records['historical_evidence']=root
    result=classify_last_session(**timeout_records)
    assert result['status']=='BLOCKED' and result['pointer_classification']=='UNKNOWN_OR_CONTRADICTORY'


def test_complete_historical_precheck_needs_no_disposition_and_no_consent(records):
    from tools.rover_xrce_trace.historical_disposition import diagnostic_precheck
    current=dict(observed_monotonic=10,complete=True,restriction=None,guards={},
                 other_sessions=[],host_processes=[],host_boot_id='fixture-host')
    result=diagnostic_precheck(records,current,{},now=10)
    assert result['precheck_satisfied'] and not result['disposition_consumed']
    assert result['historical_classification']['pointer_classification']=='HISTORICAL_CLOSED_POINTER'
    assert not result['opening_authorized'] and not result['movement_authorized']
    current['guards']={'sequence.json':'UNCONFIRMED'}
    assert not diagnostic_precheck(records,current,{},now=10)['precheck_satisfied']


@pytest.fixture
def reactivated_records():
    """Actual 8076 closure + actual read-only reactivation evidence; never edited."""
    trial=TRIAL.parent/'8076e735-81bb-4542-afda-8db2fe54acef'
    control=ROOT/'simulation/ros2_gazebo/results/gui_control_two_drones_2026_10_25/94081694-c064-4167-ae34-9e92fc6290eb'
    def read(base,name):return json.loads((base/name).read_bytes())
    start=read(trial,'runtime_copies/start/operation.json');pointer=start['diagnostic_agent']
    owner=pointer['lifecycle_id'];prefix='after_stop/container_copies'+pointer['prefix']+'/'
    raw=read(control,'final-container.stdout')
    env={k:raw[k] for k in ('state','name')};env.update(status='ACTIVE',
        engine_id=pointer['manifest']['engine_id'],container_id=raw['id'],image_id=raw['image'],created_at=raw['created'])
    return dict(target=read(control,'host_record_copies/diagnostic_agent_session.json'),
        start_operation=start,stop_operation=read(trial,'runtime_copies/stop/operation.json'),
        environment_reference=read(trial,'runtime_copies/start/rover_environment_reference.json'),
        environment=env,inventory=read(control,'final-process-inventory.stdout'),
        selection=read(trial,prefix+'selection.json'),launch=read(trial,prefix+'launch.json'),
        monitor=read(trial,prefix+'capture/monitor.json'))


@pytest.mark.parametrize('mode',['reactivated','same_execution','boot_only'])
def test_closed_e238_uses_its_own_execution_context(reactivated_records,mode):
    r=reactivated_records
    if mode in {'same_execution','boot_only'}:r['environment']['state']=copy.deepcopy(r['environment_reference']['pre_start_state'])
    if mode=='same_execution':r['inventory']['boot_id']=r['monitor']['monitor']['boot_id']
    before=copy.deepcopy(r);result=classify_last_session(**r)
    assert result['status']=='CLEAR',result
    ctx=result['execution_context']
    assert ctx['container_reexecuted'] is (mode=='reactivated')
    assert ctx['container_boot_changed'] is (mode!='same_execution')
    assert ctx['historical_pids_used_as_current'] is False
    assert ctx['historical_monitor_phase']=='CLOSED' and ctx['historical_capture_complete'] is True
    assert r==before and not result['movement_authorized']


@pytest.mark.parametrize('bad',['engine_id','container_id','image_id','created_at','unknown',
                                  'active','missing_close','incomplete','ambiguous','process','historical_boot'])
def test_reactivation_never_hides_unknown_or_active_context(reactivated_records,bad):
    r=reactivated_records
    if bad in {'engine_id','container_id','image_id','created_at'}:r['environment'][bad]='changed'
    elif bad=='unknown':r['environment']['status']='UNKNOWN'
    elif bad=='active':r['target']['state']='STARTED'
    elif bad=='missing_close':r['stop_operation']=None
    elif bad=='incomplete':r['monitor']['phase']='INCOMPLETE';r['monitor']['capture_complete']=False
    elif bad=='ambiguous':r['inventory']['ambiguous']=[{'pid':7}]
    elif bad=='process':r['inventory']['owned']=[{'pid':8}]
    else:r['monitor']['agent']['boot_id']='contradicts-old-monitor'
    from tools.rover_xrce_trace.historical_disposition import diagnostic_precheck
    result=diagnostic_precheck(r,dict(complete=True,observed_monotonic=10,restriction=None,guards={},
        other_sessions=[],host_processes=[],host_boot_id='current-host'),
        {'owner_id':'51790d37-9fce-489b-9a24-688d3790fff7','status':'DISPOSED_DIAGNOSTICALLY_INCOMPLETE'},now=10)
    assert result['status']=='BLOCKED' and not result['disposition_consumed']


def test_e238_complete_history_never_consumes_51790_disposition(reactivated_records):
    from tools.rover_xrce_trace.historical_disposition import diagnostic_precheck,REVIEWED_SCOPE
    current=dict(complete=True,observed_monotonic=10,restriction=None,guards={},
        other_sessions=[],host_processes=[],host_boot_id='current-host')
    audit={'owner_id':'51790d37-9fce-489b-9a24-688d3790fff7',
           'scope_sha256':REVIEWED_SCOPE,'offline_only':False,'status':'DISPOSED_DIAGNOSTICALLY_INCOMPLETE'}
    before=copy.deepcopy(reactivated_records)
    result=diagnostic_precheck(reactivated_records,current,audit,now=10)
    assert result['status']=='SATISFIED' and not result['disposition_consumed']
    reactivated_records['monitor']['capture_complete']=False
    assert diagnostic_precheck(reactivated_records,current,audit,now=10)['status']=='BLOCKED'
    assert before['monitor']['capture_complete'] is True


@pytest.mark.parametrize('change',[None,'restart_between_reads','boot_between_reads','query_failed'])
def test_real_reader_consumer_brackets_current_execution(reactivated_records,tmp_path,monkeypatch,change):
    from tools.rover_xrce_trace import historical_disposition as d
    from tools import vehicle_execution_lock as locks,reconciliation_environment as env
    from types import SimpleNamespace
    import subprocess
    r=reactivated_records;owner=r['target']['descriptor']['lifecycle_id'];closing=r['target']['closed_by']
    def save(path,value):path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(value))
    save(locks.LOCK_ROOT.parent/'diagnostic_agent_session.json',r['target'])
    for oid,name,value in [(owner,'operation.json',r['start_operation']),
                           (owner,'rover_environment_reference.json',r['environment_reference']),
                           (closing,'operation.json',r['stop_operation'])]:
        save(locks.LOCK_ROOT.parent/'simulation_lifecycle'/oid/name,value)
    inventory=copy.deepcopy(r['inventory']);prefix=r['target']['descriptor']['prefix']
    inventory['files']={prefix+'/'+name:json.dumps(r[key]) for name,key in
        [('selection.json','selection'),('launch.json','launch'),('capture/monitor.json','monitor')]}
    before=copy.deepcopy(r['environment']);after=copy.deepcopy(before)
    if change=='restart_between_reads':after['state']['StartedAt']='2026-10-25T09:40:21Z'
    observations=iter([before,after])
    monkeypatch.setattr(env,'inspect_environment',lambda:next(observations))
    monkeypatch.setattr(env,'read_container_boot_id',lambda value:'newer-boot' if change=='boot_between_reads' else inventory['boot_id'])
    monkeypatch.setattr(subprocess,'run',lambda *a,**kw:SimpleNamespace(
        returncode=1 if change=='query_failed' else 0,stdout=json.dumps(inventory)))
    real_path=Path;host=tmp_path/'hostproc';host.mkdir();(host/'boot').write_text('host-boot')
    monkeypatch.setattr(d,'Path',lambda p:host if p=='/proc' else host/'boot' if p=='/proc/sys/kernel/random/boot_id' else real_path(p))
    monkeypatch.setattr(d.ProjectDisposition,'query',lambda self:{})
    result=d.diagnostic_precheck_locked(expected_target=r['target'])
    if change is None:
        assert result['precheck_satisfied'],result
        assert result['current_environment_execution']==env.active_execution_identity(before,inventory['boot_id'])
        assert not result['disposition_consumed']
    else:
        assert not result['precheck_satisfied'] and result['status']=='BLOCKED'
        assert not (locks.LOCK_ROOT/'lifecycle.json').exists()


@pytest.mark.parametrize('change',[None,'before_lease','during_backend','boot_during_backend'])
def test_lifecycle_pins_new_execution_and_blocks_active_changes(reactivated_records,tmp_path,monkeypatch,change):
    from tools import simulation_lifecycle as life,vehicle_execution_lock as locks,reconciliation_environment as env
    from tools.rover_xrce_trace import historical_disposition as d
    r=reactivated_records
    locks.LOCK_ROOT.parent.mkdir(parents=True,exist_ok=True)
    (locks.LOCK_ROOT.parent/'diagnostic_agent_session.json').write_text(json.dumps(r['target']))
    execution=env.active_execution_identity(r['environment'],r['inventory']['boot_id'])
    def reader(context=None):
        if context is not None:context['current_environment_execution']=copy.deepcopy(execution)
        return copy.deepcopy(r),dict(complete=True,observed_monotonic=10,restriction=None,guards={},
            other_sessions=[],host_processes=[],host_boot_id='host')
    monkeypatch.setattr(d,'current_records',reader);monkeypatch.setattr(d.ProjectDisposition,'query',lambda self:{})
    monkeypatch.setattr(d.time,'monotonic',lambda:10)
    calls=[];current=copy.deepcopy(execution)
    if change=='before_lease':current['container_started_at']='2026-10-25T10:00:00Z'
    monkeypatch.setattr(env,'inspect_active_execution',lambda:copy.deepcopy(current))
    def backend(action,gui,fd,process,log):
        calls.append(action)
        lease=json.loads((locks.LOCK_ROOT/'lifecycle.json').read_text())
        assert lease['environment_execution']==execution
        assert json.loads((log.parent/'environment_execution_reference.json').read_text())==execution
        assert execution['container_started_at']!=r['environment_reference']['pre_start_state']['StartedAt']
        # Both locks remain held through backend/current revalidation.
        for name in ('v1.execution.lock','registry.lock'):
            with pytest.raises(locks.VehicleBusy):
                with locks.file_mutex(locks.LOCK_ROOT/name,blocking=False):pass
        if change=='during_backend':current['container_started_at']='2026-10-25T10:00:00Z'
        elif change=='boot_during_backend':current['container_boot_id']='another-current-boot'
        return 0
    monkeypatch.setattr(life,'_backend',backend)
    result=life.run_lifecycle('start',profile='two_drones')
    if change is None:
        assert result['status']=='SUCCESS' and calls==['start']
        assert not (locks.LOCK_ROOT/'lifecycle.json').exists()
    elif change=='before_lease':
        assert result['status']=='BLOCKED' and not calls
        assert not (locks.LOCK_ROOT/'lifecycle.json').exists()
    else:
        assert result['status']=='UNCONFIRMED' and calls==['start']
        lease=json.loads((locks.LOCK_ROOT/'lifecycle.json').read_text())
        assert lease['state']=='UNCONFIRMED' and lease['environment_execution']==execution
    # A normal GUI opening never overwrites the previous diagnostic pointer.
    assert json.loads((locks.LOCK_ROOT.parent/'diagnostic_agent_session.json').read_text())==r['target']


def test_current_execution_reader_failure_is_blocked_not_absence(monkeypatch):
    from tools import simulation_lifecycle as life,reconciliation_environment as env,vehicle_execution_lock as locks
    def fail():raise TimeoutError('fixture metadata unavailable')
    monkeypatch.setattr(env,'inspect_active_execution',fail)
    with pytest.raises(locks.VehicleBusy):life.assert_environment_execution({})


@pytest.mark.parametrize('case',['stable','restart','boot_query_failed','metadata_unknown'])
def test_active_execution_public_reader_uses_bounded_real_contract(reactivated_records,monkeypatch,case):
    from tools import reconciliation_environment as env
    from types import SimpleNamespace
    import subprocess
    before=copy.deepcopy(reactivated_records['environment']);after=copy.deepcopy(before)
    if case=='restart':after['state']['StartedAt']='2026-10-25T12:00:00Z'
    if case=='metadata_unknown':after['status']='UNKNOWN'
    samples=iter([before,after]);monkeypatch.setattr(env,'inspect_environment',lambda:next(samples))
    calls=[]
    def read(args,**kw):
        calls.append(args)
        assert args[:3]==['docker','exec',before['container_id']]
        assert args[3:6]==['python3','-B','-c'] and 'boot_id' in args[6]
        assert kw['timeout']==env.COMMAND_TIMEOUT_SECONDS and kw['check'] is False
        return SimpleNamespace(returncode=1 if case=='boot_query_failed' else 0,
                               stdout=reactivated_records['inventory']['boot_id']+'\n')
    monkeypatch.setattr(subprocess,'run',read)
    if case=='stable':
        result=env.inspect_active_execution()
        assert result==env.active_execution_identity(before,reactivated_records['inventory']['boot_id'])
    else:
        with pytest.raises(ValueError):env.inspect_active_execution()
    assert len(calls)==1
