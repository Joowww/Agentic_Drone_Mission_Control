"""Public recovered start and explicit disarm closure. Doubles/temp storage only."""
from concurrent.futures import ThreadPoolExecutor
from threading import Event
import json
import pytest
from tools import rover_ground_executor as g, vehicle_execution_lock as locks
from tests.test_rover_navigation import execute, GOAL
from tests.test_rover_ground_executor import setup

POLICY={'kind':'DISARM_AFTER_OBSERVED_STOP_V1','timeout_s':3.}


def test_lost_admission_response_lookup_start_finalize_query_without_token(setup):
    a,s,factory,auth=execute(setup,finalization=POLICY,start=False)
    assert 'launch_token' not in a
    recovered=g.lookup_ground_trial('navigation')
    assert recovered['worker_phase']=='ADMITTED_NOT_STARTED'
    assert recovered['session_id']==a['session_id']
    report=g.start_ground_trial(recovered['run_id'],auth,adapter_factory=factory,readiness=lambda **kw:{'ready':True})
    assert report['result']['goal_outcome']=='GOAL_REACHED'
    assert report['finalization']['status']=='DISARMED_STATIONARY_OBSERVED'
    q=g.query_ground_trial(a['run_id'])
    assert q['status']=='FINISHED' and q['job_closure_confirmed']
    assert q['report']['closure']['stop_observed'] and q['reservation'] is None
    assert not any('token' in k for k in q)
    assert g.start_ground_trial(a['run_id'],auth,adapter_factory=lambda journal:pytest.fail('must not restart'))['status']=='BLOCKED'

@pytest.mark.parametrize('failure',['disarm_rejected','disarm_lost','finalization_stale','finalization_source'])
def test_finalization_uncertainty_retains_stop_and_reservation(setup,failure):
    report,s,a=execute(setup,finalization=POLICY,failure=failure)
    assert report['result']['goal_outcome']=='GOAL_REACHED' and report['result']['stop']['stationary_observed']
    assert report['finalization']['status']=='UNCONFIRMED' and report['status']=='UNCONFIRMED'
    assert locks.restriction('v3') and g.query_ground_trial(a['run_id'])['status']=='UNCONFIRMED'


def test_interrupted_between_stop_and_close_retains_durable_stop_evidence(setup):
    with pytest.raises(KeyboardInterrupt):execute(setup,finalization=POLICY,failure='finalization_interrupt')
    row=g.lookup_ground_trial('navigation');q=g.query_ground_trial(row['run_id'])
    assert q['status']=='UNCONFIRMED' and locks.restriction('v3')
    saved=json.loads((g.directory(row['run_id'])/'stop-evidence.json').read_bytes())
    assert saved['goal_outcome']=='GOAL_REACHED' and saved['stop']['stationary_observed']

@pytest.mark.parametrize('pose',[(0.,0.,0.),(.8,.4,.2)])
def test_cancel_in_approach_or_dwell_closes_safely_without_claiming_goal(setup,pose):
    calls=[0]
    def cancelled():calls[0]+=1;return calls[0]>4
    report,s,a=execute(setup,pose=pose,finalization=POLICY,cancelled=cancelled)
    assert report['result']['goal_outcome']=='GOAL_FAILED'
    assert report['result']['stop']['stationary_observed']
    assert report['finalization']['disarmed_observed']
    assert g.query_ground_trial(a['run_id'])['status']=='FINISHED' and locks.restriction('v3') is None
    assert report['status']=='GOAL_FAILED_CLOSURE_OBSERVED'


def test_failed_goal_confirmed_stop_and_close_are_separate(setup):
    report,s,a=execute(setup,finalization=POLICY,failure='stuck')
    assert report['result']['goal_outcome']=='GOAL_FAILED'
    assert report['finalization']['disarmed_observed'] and g.query_ground_trial(a['run_id'])['status']=='FINISHED'


def test_two_start_requests_claim_once_without_a_second_worker(setup,monkeypatch):
    a,s,factory,auth=execute(setup,start=False)
    entered,finish=Event(),Event();calls=[]
    def pause(root,*args):
        calls.append(root);entered.set();assert finish.wait(5)
        return {'status':'STARTING_TEST_DOUBLE_ONLY'}
    monkeypatch.setattr(g,'_consume_start_claim',pause)
    with ThreadPoolExecutor(max_workers=2) as pool:
        first=pool.submit(g.start_ground_trial,a['run_id'],auth,adapter_factory=factory)
        assert entered.wait(5)
        second=pool.submit(g.start_ground_trial,a['run_id'],auth,adapter_factory=factory)
        assert second.result()['status']=='BLOCKED'
        finish.set();assert first.result()['status']=='STARTING_TEST_DOUBLE_ONLY'
    assert len(calls)==1 and not s.commands

@pytest.mark.parametrize('stage',['before_claim','before_starting','after_starting','before_worker_identity'])
def test_start_interruptions_never_resume_uncertain_claim(setup,monkeypatch,stage):
    a,s,factory,auth=execute(setup,start=False);root=g.directory(a['run_id'])
    original=g.locks.atomic_json
    if stage=='before_claim':
        original_open=__import__('os').open
        def fail(path,*args,**kw):
            if str(path).endswith('start-intent.json'):raise OSError('fixture claim failure')
            return original_open(path,*args,**kw)
        monkeypatch.setattr('os.open',fail)
    else:
        def fail(path,value):
            if path.name=='job.json' and ((stage in ('before_starting','after_starting') and value['job_state']=='STARTING')
                or stage=='before_worker_identity' and value['job_state']=='RUNNING'):
                if stage=='after_starting':original(path,value)
                raise OSError('fixture persistence interruption')
            return original(path,value)
        monkeypatch.setattr(g.locks,'atomic_json',fail)
    if stage=='before_claim':
        with pytest.raises(OSError):g.start_ground_trial(a['run_id'],auth,adapter_factory=factory)
        assert g.query_ground_trial(a['run_id'])['worker_phase']=='ADMITTED_NOT_STARTED'
    else:
        assert g.start_ground_trial(a['run_id'],auth,adapter_factory=factory)['status']=='UNCONFIRMED'
        assert g.query_ground_trial(a['run_id'])['status']=='UNCONFIRMED'
        assert g.start_ground_trial(a['run_id'],auth,adapter_factory=factory)['status']=='BLOCKED'
    assert not s.commands

@pytest.mark.parametrize('field',['candidate_sha256','session_id','authorization_sha256'])
def test_other_start_scope_rejected_before_claim(setup,field):
    a,s,factory,auth=execute(setup,start=False);auth[field]='other'
    with pytest.raises(ValueError,match='scope'):g.start_ground_trial(a['run_id'],auth,adapter_factory=factory)
    assert g.query_ground_trial(a['run_id'])['worker_phase']=='ADMITTED_NOT_STARTED' and not s.commands


def test_start_response_lost_completed_query_is_only_recovery(setup):
    a,s,factory,auth=execute(setup,finalization=POLICY,start=False)
    g.start_ground_trial(a['run_id'],auth,adapter_factory=factory,readiness=lambda **kw:{'ready':True})  # discard response
    before=len(s.commands);q=g.query_ground_trial(g.lookup_ground_trial('navigation')['run_id'])
    assert q['status']=='FINISHED'
    assert g.start_ground_trial(a['run_id'],auth,adapter_factory=factory)['status']=='BLOCKED'
    assert len(s.commands)==before


def test_old_job_cannot_borrow_disarm_from_generic_execution_authority(setup):
    path,request,auth,session,factory=setup
    a=g.admit_ground_trial(path,'old-bounded',request,auth)
    adapter=factory(lambda event:None)
    from tools.rover_ros2_adapter import DISARM
    with locks.execution_scope(a['run_id'],'v3'):
        adapter.probe(timeout_s=1.)
        with pytest.raises(ValueError,match='FINALIZING'):
            adapter.exchange({'kind':'service','endpoint':DISARM,'type':'ardupilot_msgs/srv/ArmMotors','payload':{'arm':False}},timeout_s=1.)
    assert not session.commands


def test_dead_start_requester_or_reused_pid_is_query_only_uncertainty(setup,monkeypatch):
    a,s,factory,auth=execute(setup,start=False)
    monkeypatch.setattr(g,'_consume_start_claim',lambda *args:{'status':'STARTING_FIXTURE_ONLY'})
    g.start_ground_trial(a['run_id'],auth,adapter_factory=factory)
    root=g.directory(a['run_id']);before={p.name:p.read_bytes() for p in root.glob('*.json')}
    monkeypatch.setattr(locks,'identity_alive',lambda identity:False)
    q=g.query_ground_trial(a['run_id'])
    assert q['status']=='UNCONFIRMED' and q['worker_phase']=='STARTING_WORKER_LOST_OR_UNKNOWN'
    assert before=={p.name:p.read_bytes() for p in root.glob('*.json')}
    assert g.start_ground_trial(a['run_id'],auth,adapter_factory=factory)['status']=='BLOCKED' and not s.commands


def test_identity_persisted_but_response_interrupted_cannot_start_again(setup,monkeypatch):
    a,s,factory,auth=execute(setup,start=False);original=locks.atomic_json
    def fail_after(path,value):
        original(path,value)
        if path.name=='job.json' and value.get('job_state')=='RUNNING':raise OSError('fixture lost identity-write response')
    monkeypatch.setattr(locks,'atomic_json',fail_after)
    assert g.start_ground_trial(a['run_id'],auth,adapter_factory=factory)['status']=='UNCONFIRMED'
    assert g.query_ground_trial(a['run_id'])['status']=='UNCONFIRMED'
    assert g.start_ground_trial(a['run_id'],auth,adapter_factory=factory)['status']=='BLOCKED' and not s.commands


def test_rejected_stop_does_not_enable_finalization(setup):
    report,s,a=execute(setup,finalization=POLICY,failure='stop')
    assert report['result']['goal_outcome']=='GOAL_REACHED'
    assert report['finalization']['status']=='UNCONFIRMED' and not report['finalization']['disarm_attempted']
    assert not s.disarm_requested and locks.restriction('v3')


def test_missing_finalization_capability_blocks_before_first_control(setup):
    a,s,factory,auth=execute(setup,finalization=POLICY,start=False)
    original=s.probe
    s.probe=lambda **kw:{**original(**kw),'disarm_available':False}
    report=g.start_ground_trial(a['run_id'],auth,adapter_factory=factory,readiness=lambda **kw:{'ready':True})
    assert report['status']=='UNCONFIRMED' and not s.commands and locks.restriction('v3')


def test_native_disarm_timeout_preserves_exact_service_and_no_retry(setup,monkeypatch):
    from types import SimpleNamespace
    from unittest.mock import Mock
    from tools import rover_ros2_adapter as ros
    path,request,auth,_,_=setup
    admitted=g.admit_ground_trial(path,'transport-contract-only',request,auth)
    native=ros.NativeRos2Session.__new__(ros.NativeRos2Session)
    native._require_identity=lambda **kw:None  # isolated typed transport contract, no real identity claim
    monkeypatch.setattr(ros,'_assert_disarm_scope',lambda:None)  # real scope refusal tested separately
    native.node=object();native.disarm_type=SimpleNamespace(Request=lambda:SimpleNamespace(arm=None))
    future=SimpleNamespace(done=lambda:False,cancel=Mock())
    native.disarm_client=SimpleNamespace(call_async=Mock(return_value=future))
    native.rclpy=SimpleNamespace(spin_until_future_complete=Mock())
    command={'kind':'service','endpoint':ros.DISARM,'type':'ardupilot_msgs/srv/ArmMotors','payload':{'arm':False}}
    with locks.execution_scope(admitted['run_id'],'v3'):
        with pytest.raises(TimeoutError) as exc:native.exchange(command,timeout_s=.1)
    assert exc.value.diagnostic['service']==ros.DISARM
    assert exc.value.diagnostic['type']=='ardupilot_msgs/srv/ArmMotors'
    assert exc.value.diagnostic['response_received'] is False
    native.disarm_client.call_async.assert_called_once()
    assert native.disarm_client.call_async.call_args.args[0].arm is False
    future.cancel.assert_called_once()
