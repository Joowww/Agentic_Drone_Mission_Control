"""Fresh inspect/apply with synthetic streams, isolated records and deterministic races."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
from threading import Event
from unittest.mock import Mock
from uuid import uuid4

import pytest

from tools import execution_reconciliation as reconcile
from tools import vehicle_execution_lock as locks
from tools import virtual_preflight_jobs as jobs
from tools import simulation_lifecycle as lifecycle
from tools.ros2_flight_control import CONTAINER


def environment(active=True):
    return {'status':'ACTIVE' if active else 'STOPPED', 'engine_id':'synthetic-engine',
            'container_id':'a'*64, 'name':'/'+CONTAINER, 'created_at':'2026-10-01T00:00:00Z',
            'image_id':'sha256:'+'b'*64, 'unknown_fields':[], 'reasons':[],
            'state':{'Status':'running' if active else 'exited', 'Running':active,
                     'Pid':123 if active else 0, 'Paused':False, 'Restarting':False, 'Dead':False,
                     'StartedAt':'2026-10-16T16:00:00Z',
                     'FinishedAt':'0001-01-01T00:00:00Z' if active else '2026-10-19T17:00:00Z'}}


def streams():
    result={'subscription':'NEW_VOLATILE','collection_wall_seconds':3.,'samples':{}}
    for v in ('v1','v2'):
        result['samples'][v]={}
        for kind in ('status','position'):
            samples=[]
            for i in (1,2,3):
                msg={'header':{'stamp':{'sec':100+i,'nanosec':0}}}
                msg.update({'armed':False,'flying':False,'failsafe':[]} if kind=='status' else
                           {'pose':{'position':{'latitude':41.,'longitude':2.,'altitude':584.}}})
                samples.append({'receipt_elapsed_seconds':float(i),'message':msg})
            result['samples'][v][kind]=samples
    return result


@pytest.fixture
def system(tmp_path, monkeypatch):
    monkeypatch.setattr(reconcile,'INSPECTION_ROOT',tmp_path/'inspections')
    monkeypatch.setattr(jobs,'RUN_ROOT',tmp_path/'runs')
    monkeypatch.setattr(reconcile,'boot_id',lambda:'test-boot')
    identity={'pid':999991,'start_ticks':10,'boot_id':'test-boot'}
    monkeypatch.setattr(locks,'process_identity',lambda pid=None: None if pid else {'pid':123,'start_ticks':1,'boot_id':'test-boot'})
    run_id=str(uuid4()); root=jobs.run_directory(run_id);root.mkdir(parents=True)
    from tests.test_virtual_preflight import EXAMPLE
    content_data=json.loads(EXAMPLE.read_text());content_data['vehicle']['vehicle_id']='drone_02'
    content=json.dumps(content_data).encode();sha=hashlib.sha256(content).hexdigest()
    (root/'input.json').write_bytes(content);(root/'mission.json').write_bytes(content)
    locks.atomic_json(root/'job.json',{'schema_version':2,'vehicle_selection':{'vehicle_id':'drone_02','simulated_vehicle':'v2'},'run_id':run_id,'input_sha256':sha,'job_state':'FINISHED','worker':identity,
                                      'started_at':'2026-10-18T21:18:42+00:00','finished_at':'2026-10-18T21:19:09+00:00'})
    locks.atomic_json(root/'report.json',{'run_id':run_id,'mission_sha256':sha,'status':'ERROR','executor_result':None,'analysis':None,
                                         'execution_started_at':'2026-10-18T21:18:50+00:00','execution_finished_at':'2026-10-18T21:19:09+00:00'})
    locks.LOCK_ROOT.mkdir()
    locks.atomic_json(locks.LOCK_ROOT/'v2.json',{'owner_id':run_id,'actor':'asynchronous','state':'UNCONFIRMED','vehicle':'v2','process':identity})
    collector=Mock(side_effect=lambda:deepcopy(streams()));monkeypatch.setattr(reconcile,'collect_observations',collector)
    monkeypatch.setattr(reconcile,'inspect_environment',Mock(side_effect=lambda:environment()))
    return run_id,root,collector


def inspect(system):
    return reconcile.inspect_execution_reconciliation(system[0])


def apply(inspected, **changes):
    values=dict(inspection_id=inspected['inspection_id'],inspection_sha256=inspected['inspection_sha256'],
                authorization_statement='Operator explicitly authorizes reconciliation only, no flight',
                ground_confirmations=[{'vehicle':v,'source':'OPERATOR_VISUAL','on_ground':True,
                                       'statement':'Operator independently sees this vehicle resting on the ground',
                                       'observed_at_utc':datetime.now(timezone.utc).isoformat()} for v in ('v1','v2')])
    values.update(changes)
    return values,reconcile.apply_execution_reconciliation(**values)


def test_inspection_does_not_modify_reservations_or_historic_report(system):
    before=(locks.LOCK_ROOT/'v2.json').read_bytes();report=(system[1]/'report.json').read_bytes()
    result=inspect(system)
    assert result['status']=='AWAITING_EXPLICIT_GROUND_CONFIRMATION'
    assert (locks.LOCK_ROOT/'v2.json').read_bytes()==before
    assert (system[1]/'report.json').read_bytes()==report
    assert result['generation_freshness']=='ABSOLUTE_AGE_UNKNOWN'


def test_apply_archives_original_and_is_idempotent_without_new_observations(system):
    original=(locks.LOCK_ROOT/'v2.json').read_bytes();report=(system[1]/'report.json').read_bytes()
    inspected=inspect(system);arguments,result=apply(inspected)
    assert result['status']=='APPLIED' and not result['flight_authorized']
    assert locks.restriction() is None
    assert (locks.LOCK_ROOT/'history'/inspected['inspection_id']/'v2.json').read_bytes()==original
    assert (system[1]/'report.json').read_bytes()==report
    assert reconcile.apply_execution_reconciliation(**arguments)['replayed'] is True
    assert system[2].call_count==2


@pytest.mark.parametrize('failure',['missing_samples','stalled_stamp','flying','moving','wrong_subscription'])
def test_insufficient_or_unsafe_evidence_never_permits_apply(system,failure):
    observation=streams()
    if failure=='missing_samples':observation['samples']['v1']['status']=[]
    elif failure=='stalled_stamp':observation['samples']['v2']['position'][1]['message']['header']['stamp']['sec']=101
    elif failure=='flying':observation['samples']['v1']['status'][-1]['message']['flying']=True
    elif failure=='moving':observation['samples']['v2']['position'][-1]['message']['pose']['position']['altitude']=600
    else:observation['subscription']='TRANSIENT_HISTORY'
    system[2].side_effect=lambda:observation
    inspected=inspect(system);assert inspected['status']=='BLOCKED'
    assert apply(inspected)[1]['status']=='BLOCKED'
    assert (locks.LOCK_ROOT/'v2.json').exists()


@pytest.mark.parametrize('change',['ttl','boot','owner','report','process','ground_missing','ground_unsupported','hash'])
def test_application_is_bound_to_inspected_versions_processes_and_ground_evidence(system,monkeypatch,change):
    inspected=inspect(system);override={}
    if change=='ttl':
        now=reconcile.time.monotonic();monkeypatch.setattr(reconcile.time,'monotonic',lambda:now+121)
    elif change=='boot':monkeypatch.setattr(reconcile,'boot_id',lambda:'different-boot')
    elif change=='owner':
        p=locks.LOCK_ROOT/'v2.json';v=json.loads(p.read_text());v['owner_id']=str(uuid4());locks.atomic_json(p,v)
    elif change=='report':(system[1]/'report.json').write_text('{}')
    elif change=='process':monkeypatch.setattr(locks,'process_identity',lambda pid=None:{'pid':pid or 123,'start_ticks':999,'boot_id':'test-boot'})
    elif change=='ground_missing':override['ground_confirmations']=[]
    elif change=='ground_unsupported':override['ground_confirmations']=[{'vehicle':v,'source':'ARMED_FALSE','statement':'not visual','observed_at_utc':datetime.now(timezone.utc).isoformat()} for v in ('v1','v2')]
    else:override['inspection_sha256']='0'*64
    assert apply(inspected,**override)[1]['status']=='BLOCKED'
    assert (locks.LOCK_ROOT/'v2.json').exists()


def test_pid_reuse_or_alive_worker_blocks_inspection_without_telemetry(system,monkeypatch):
    monkeypatch.setattr(locks,'process_identity',lambda pid=None:{'pid':pid or 123,'start_ticks':999,'boot_id':'test-boot'})
    assert inspect(system)['status']=='BLOCKED'
    system[2].assert_not_called()


def test_apply_revalidation_excludes_admission_and_lifecycle_without_sleep(system,monkeypatch):
    inspected=inspect(system);entered=Event();finish=Event();backend=Mock(return_value=0)
    monkeypatch.setattr(lifecycle,'_backend',backend)
    def observe():
        entered.set();assert finish.wait(10);return streams()
    system[2].side_effect=observe
    with ThreadPoolExecutor() as pool:
        future=pool.submit(apply,inspected)
        assert entered.wait(10)
        try:
            with pytest.raises(locks.VehicleBusy):locks.reserve(str(uuid4()),'other','v1')
            assert lifecycle.run_lifecycle('restart')['status']=='BLOCKED'
            backend.assert_not_called()
        finally:finish.set()
        assert future.result()[1]['status']=='APPLIED'


def test_state_change_inside_revalidation_preserves_restriction(system):
    inspected=inspect(system)
    def observe():
        (system[1]/'report.json').write_text('{}');return streams()
    system[2].side_effect=observe
    assert apply(inspected)[1]['status']=='BLOCKED'
    assert (locks.LOCK_ROOT/'v2.json').exists()


def test_missing_job_is_not_reconstructed(system):
    (system[1]/'job.json').unlink()
    # A reservation claiming an async worker must retain its job. Refuse lost artifacts.
    assert inspect(system)['status']=='BLOCKED'


def test_disappeared_worker_without_result_stays_historically_unknown_after_explicit_reconciliation(system):
    (system[1]/'report.json').unlink()
    job=json.loads((system[1]/'job.json').read_text());job['job_state']='RUNNING'
    locks.atomic_json(system[1]/'job.json',job)
    inspected=inspect(system)
    assert inspected['status']=='AWAITING_EXPLICIT_GROUND_CONFIRMATION'
    assert apply(inspected)[1]['status']=='APPLIED'
    assert not (system[1]/'report.json').exists()
    assert json.loads((system[1]/'job.json').read_text())['job_state']=='RUNNING'


def test_missing_collector_evidence_cannot_clear_anything(system):
    system[2].side_effect=RuntimeError('read-only collector unavailable')
    assert inspect(system)['status']=='BLOCKED'
    assert (locks.LOCK_ROOT/'v2.json').exists()


def test_inspection_changed_during_application_is_rejected(system):
    inspected=inspect(system)
    def observe():
        path=reconcile.INSPECTION_ROOT/inspected['inspection_id']/'inspection.json'
        path.write_text(path.read_text()+' ')
        return streams()
    system[2].side_effect=observe
    assert apply(inspected)[1]['status']=='BLOCKED'
    assert (locks.LOCK_ROOT/'v2.json').exists()


def test_audit_lookup_after_reload_is_readonly_and_does_not_reapply(system,monkeypatch):
    inspected=inspect(system)
    args,result=apply(inspected)
    assert result['status']=='APPLIED'
    contents={str(p):p.read_bytes() for p in reconcile.INSPECTION_ROOT.rglob('*') if p.is_file()}
    system[2].reset_mock()
    monkeypatch.setattr(reconcile,'capture',Mock(side_effect=AssertionError('lookup must not inspect live state')))
    view=reconcile.get_execution_reconciliation(inspected['inspection_id'])
    assert view['application']['status']=='APPLIED' and view['application']['flight_authorized'] is False
    assert contents=={str(p):p.read_bytes() for p in reconcile.INSPECTION_ROOT.rglob('*') if p.is_file()}
    system[2].assert_not_called()


def test_interruption_during_archival_keeps_durable_barrier_and_never_resumes(system,monkeypatch):
    inspected=inspect(system)
    original=reconcile.Path.unlink
    def fail(path,*args,**kwargs):
        if path==locks.LOCK_ROOT/'v2.json': raise OSError('injected removal interruption')
        return original(path,*args,**kwargs)
    monkeypatch.setattr(reconcile.Path,'unlink',fail)
    args,result=apply(inspected)
    assert result['status']=='BLOCKED'
    assert (locks.LOCK_ROOT/'reconciliation.json').exists()
    with pytest.raises(locks.VehicleBusy):locks.reserve(str(uuid4()),'new flight','v1')
    repeated=reconcile.apply_execution_reconciliation(**args)
    assert repeated['status']=='APPLYING' and repeated['replayed'] is True
    assert (locks.LOCK_ROOT/'v2.json').exists()


def test_query_exposes_expiry_without_releasing_or_collecting(system,monkeypatch):
    inspected=inspect(system);now=reconcile.time.monotonic()
    monkeypatch.setattr(reconcile.time,'monotonic',lambda:now+121)
    system[2].reset_mock()
    view=reconcile.get_execution_reconciliation(inspected['inspection_id'])
    assert view['evidence_expired'] is True and view['remaining_seconds']==0
    assert (locks.LOCK_ROOT/'v2.json').exists()
    system[2].assert_not_called()


def test_active_global_executor_mutex_blocks_inspection_without_waiting_or_observing(system):
    original=(locks.LOCK_ROOT/'v2.json').read_bytes()
    with locks.file_mutex(locks.LOCK_ROOT/'v1.execution.lock'):
        result=inspect(system)
    assert result['status']=='BLOCKED'
    assert (locks.LOCK_ROOT/'v2.json').read_bytes()==original
    system[2].assert_not_called()


def test_repeated_application_with_changed_authorization_is_a_conflict(system):
    args,result=apply(inspect(system));assert result['status']=='APPLIED'
    args['authorization_statement']='Different authorization'
    system[2].reset_mock()
    assert reconcile.apply_execution_reconciliation(**args)['status']=='BLOCKED'
    assert locks.restriction() is None
    system[2].assert_not_called()
