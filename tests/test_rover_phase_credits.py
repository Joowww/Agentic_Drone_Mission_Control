"""Explicit synthetic source clocks, pipes and native I/O. No SDK or middleware."""
import json,os
import pytest
from tools import rover_observation_stream as stream,rover_ground_executor as ground,rover_ros2_adapter as ros
from tools.rover_control import RoverLimits
from tests import test_rover_pulse_integration as integration
from tests.test_rover_pulse_integration import current_source,setup,fake_ros


class CreditFrames(integration.Frames):
    def __init__(self,*args,**kw):
        super().__init__(*args,**kw)
        self.rows=[raw for raw in self.rows if json.loads(raw)['event']!='sample']
        header=json.loads(self.rows[0]);header.update(selection_mode='CREDIT_PHASED_V1',spacing_source_ns=0)
        self.rows[0]=json.dumps(header).encode();self.sequence=len(self.rows);self.pairs=0;self.phase=None;self.grants=[]
        self.force_ready=True;self.fail=None
    def grant(self,phase,timeout_s):
        assert timeout_s>0
        if self.fail=='write':raise BrokenPipeError('SYNTHETIC_CREDIT_WRITE')
        self.phase=phase;self.grants.append(phase)
        self.enqueue({'event':'selection_credit','credit':len(self.grants),'phase':phase})
        start=len(self.rows);self.deliver_pair()
        for i in range(start,len(self.rows)):
            row=json.loads(self.rows[i])
            if row['event']=='sample':
                row.update(selection_phase=phase,selection_credit=len(self.grants))
                # 10ms advancing source clock: original diagnostic0.5s selector
                # would discard these. Original callback receipts remain intact.
                stamp={'sec':0,'nanosec':self.pairs*10000000}
                row['body']['header']['stamp']=stamp;row['sample']['header']['stamp']=stamp
                self.rows[i]=json.dumps(row).encode()
        if self.fail=='missing' and phase=='W':self.rows=[r for r in self.rows if json.loads(r).get('topic')!='/rover1/odometry']
        if self.fail=='aged':self.clock.sleep(.6)
    def ready(self,timeout_s=0.):return bool(self.rows)
    def read(self,timeout_s):
        if self.fault=='source' and self.commands and not self.requested:raise TimeoutError('SYNTHETIC_SOURCE_LOSS')
        if not self.rows:raise TimeoutError('SYNTHETIC_NO_CREDIT_OR_CHANNEL')
        return self.rows.pop(0)


def source_fixture(current_source,*,fault=None):
    guard,current,clock=current_source
    f=CreditFrames(current,clock,mode=0,armed=False)
    src=stream.ObservationStream(f,session_id=integration.SESSION,identity=f.identity,
        read_context=lambda pid:f.identity if pid==f.identity['pid'] else {**f.identity,'pid':pid},
        clock=clock,max_age_s=.5,selection_mode='CREDIT_PHASED_V1')
    f.source=src;f.fail=fault
    return src,f


def limits():return RoverLimits(.05,.1,3.,1.,5.,.5,.01,.01)


def test_stationary_qualification_same_source_manual_disarmed_no_commands(current_source):
    src,f=source_fixture(current_source)
    result=stream.qualify_stationary_source(src,limits())
    assert result['status']=='STATIONARY_RETENTION_SEQUENCE_OBSERVED',result
    assert f.grants==list('BIWWSSDD') and not f.commands
    assert src.counts=={'/ap/v3/status':8,'/rover1/odometry':8} and src.closed
    assert result['remaining_pairs']==2 and result['receiver_close']['return_code']==0
    assert len(result['observations'])==7 and not result['vehicle_stop_or_disarm_certified']
    for row in result['observations']:
        assert row['channel_receipt_skew_s']<=.5
        assert all(0<=r['decision_age_s']<=.5 for r in row['channels'].values())


@pytest.mark.parametrize('fault',['aged','missing','write'])
def test_stationary_data_loss_preserves_reserve_and_terminal_diagnostic(current_source,fault):
    src,f=source_fixture(current_source,fault=fault)
    result=stream.qualify_stationary_source(src,limits())
    assert result['status']=='UNCONFIRMED' and result['error']
    assert not f.commands and max(src.counts.values())<=4
    assert result['receiver_close'] is not None


def test_producer_idle_cannot_spend_reserve_and_wrong_credit_rejected(current_source):
    src,f=source_fixture(current_source);src.prepare_identity(timeout_s=1)
    assert f.pairs==1 and not f.rows
    src.set_phase('I');src.observe(timeout_s=1)
    src.set_phase('W');src.observe(timeout_s=1);src.observe(timeout_s=1)
    assert min(10-v for v in src.counts.values())==6
    with pytest.raises(Exception,match='RESERVED'):src.observe(timeout_s=1)
    assert f.grants==list('BIWW')
    src.set_phase('S');src.observe(timeout_s=1)
    with pytest.raises(Exception,match='rewind'):src.set_phase('W')
    src.set_phase('D');src._grant(1)
    row=json.loads(f.rows[0]);row['credit']=999;f.rows[0]=json.dumps(row).encode()
    with pytest.raises(Exception,match='Unrequested'):src.observe(timeout_s=1)


@pytest.mark.parametrize('fault',[None,'source','identity','hold_reject','disarm_reject','close','cleanup_partial','cancel'])
def test_credit_pipe_full_protected_actor_pulse_stop_finalization(setup,current_source,fake_ros,monkeypatch,fault):
    monkeypatch.setattr(integration,'Frames',CreditFrames)
    admitted,start,factory,src,f,calls,_=integration.trial(setup,current_source,fake_ros,monkeypatch,
        fault=fault,armed=False,selection_mode='CREDIT_PHASED_V1')
    result=ground.start_ground_trial(admitted['run_id'],start,adapter_factory=factory,readiness=lambda **kw:{'ready':True},cancelled=f.cancelled)
    assert calls==['stop'],result
    assert max(src.counts.values())<=10
    assert all(p in 'BIPWSD' for p in f.grants)
    if fault in (None,'cancel'):
        assert result['finalization']['disarmed_observed'] and result['infrastructure_close']['status']=='SUCCESS',result
        assert f.grants==list('BIPPSSDD') and src.closed
    else:assert result['status']=='UNCONFIRMED',result


def test_manual_full_pulse_budget_still_blocks_before_mode_or_arm(setup,current_source,fake_ros,monkeypatch):
    monkeypatch.setattr(integration,'Frames',CreditFrames)
    admitted,start,factory,src,f,calls,_=integration.trial(setup,current_source,fake_ros,monkeypatch,
        mode=0,armed=False,selection_mode='CREDIT_PHASED_V1')
    result=ground.start_ground_trial(admitted['run_id'],start,adapter_factory=factory,readiness=lambda **kw:{'ready':True})
    assert result['observation_budget']=={'remaining_pairs':9,'minimum_required_pairs':11,'guarantees_cadence':False}
    assert not f.commands and f.grants==['B'] and calls==['stop']


def test_partial_credit_does_not_freshen_or_replace_last_complete_pair(current_source):
    src,f=source_fixture(current_source);src.prepare_identity(timeout_s=1)
    previous=src.current();src.set_phase('I');src._grant(1)
    src._next(1);src._next(1) # ack and Status only
    assert src.current()==previous
    src._next(1)
    assert src.current()['status_received_monotonic_s']>previous['status_received_monotonic_s']


def test_credit_missing_grant_ack_or_wrong_phase_is_rejected(current_source):
    src,f=source_fixture(current_source);src._grant(1)
    # Original header/metadata then a sample, with the ack missing. Sequence is
    # made coherent so rejection must be the specific credit association.
    ack=next(i for i,raw in enumerate(f.rows) if json.loads(raw)['event']=='selection_credit')
    f.rows.pop(ack)
    for i,raw in enumerate(f.rows):
        row=json.loads(raw);row['sequence']=i+1;f.rows[i]=json.dumps(row).encode()
    with pytest.raises(Exception,match='credit/phase'):src.prepare_identity(timeout_s=1)


from tests.test_rover_transport_driver import selection
from tools.rover_xrce_trace import passive_trial as passive
from unittest.mock import Mock
from dataclasses import asdict
import hashlib


@pytest.mark.parametrize('bad',[None,'mode','reserve','age','phase_pin','native_contract','build_binding','bootstrap_missing','bootstrap_changed','bootstrap_review'])
def test_selector_consumes_stationary_selection_and_native_contract(selection,monkeypatch,bad):
    root,ap,rp,agent,reader=selection
    for name in ['tools/rover_identity_probe/phase_selection.hpp','tools/rover_control.py','tools/rover_ros2_adapter.py']:
        p=root/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_text('SYNTHETIC_PHASE_FIXTURE')
        reader['source_hashes'][name]=hashlib.sha256(p.read_bytes()).hexdigest()
    reader['retention_selection']={'mode':'CREDIT_PHASED_V1','purpose':'STATIONARY_ONLY',
        'reserved_stop_pairs':3,'reserved_final_pairs':3,'limits':asdict(limits()),'bootstrap':dict(stream.BOOTSTRAP_CONTRACT)}
    build={'schema':'tfg.rover-transport-build-review/1','preparation_valid':True,'snapshot_unchanged':True,
        'artifacts':{'receiver':reader['binary']},'native_dependencies':reader['native_dependencies'],
        'contract':{'pure_cpp_contract':'PASSED','dds_participant_created':False,'ros_initialized':False},
        'phase_contract':{'phase_selection_contract':'PASSED','dds_participant_created':False,'ros_initialized':False},
        'retention_contract':passive.RETENTION_CONTRACT}
    if bad=='native_contract':build['phase_contract']['phase_selection_contract']='UNKNOWN'
    buildpath=root/'build.json';buildpath.write_text(json.dumps(build))
    sha=hashlib.sha256(buildpath.read_bytes()).hexdigest()
    reader.update(provenance=str(buildpath),provenance_sha256=sha,helper_review={'receiver_build_review_sha256':sha,'bootstrap_contract':dict(stream.BOOTSTRAP_CONTRACT)})
    if bad=='bootstrap_missing':reader['retention_selection'].pop('bootstrap')
    if bad=='bootstrap_changed':reader['retention_selection']['bootstrap']['total_s']=120.
    if bad=='bootstrap_review':reader['helper_review'].pop('bootstrap_contract')
    if bad=='mode':reader['retention_selection']['mode']='UNKNOWN'
    if bad=='reserve':reader['retention_selection']['reserved_stop_pairs']=2
    if bad=='age':reader['retention_selection']['limits']['observation_max_age_s']=5.
    if bad=='phase_pin':reader['source_hashes'].pop('tools/rover_identity_probe/phase_selection.hpp')
    if bad=='build_binding':reader['helper_review']['receiver_build_review_sha256']='0'*64
    rp.write_text(json.dumps(reader));command=Mock(return_value=0);monkeypatch.setattr(passive.LocalPorts,'command',command)
    if bad:
        assert not passive.selection_dry_run(root,ap,rp)['selection_files_valid'];command.assert_not_called()
    else:
        assert passive.selection_dry_run(root,ap,rp)['selection_files_valid'];command.assert_not_called()
        ports=passive.LocalPorts(root,root,ap,rp);ports.reader(integration.SESSION)
        cmd=command.call_args_list[-1].args
        assert cmd[0]=='reader' and any('stationary_limits={' in arg for arg in cmd[1])


def test_existing_capture_driver_passes_credit_flag_and_preserves_stationary_receipts(current_source,tmp_path,monkeypatch):
    tmp_path.chmod(0o700);prefix=tmp_path/'prefix';prefix.mkdir()
    (prefix/'selection.json').write_text(json.dumps({'descriptor':{'lifecycle_id':integration.SESSION}}))
    monkeypatch.setattr(passive,'admit_from_prefix',lambda p:{'measurement_allowed':True,'fixture':'SYNTHETIC'})
    src,f=source_fixture(current_source)
    def start(*args,**kw):
        assert kw['credit_selection'] is True and kw['rpc_metadata'] and not kw['probe_on_start']
        src.journal=kw['journal'];read=f.read
        def recording(timeout_s):
            raw=read(timeout_s);kw['raw_sink'](raw+b'\n');return raw
        f.read=recording
        return src
    monkeypatch.setattr(stream,'start_receiver',start)
    result=passive.capture_transport_from_prefix(prefix,'/tmp/SYNTHETIC','a'*64,tmp_path,stationary_limits=asdict(limits()))
    assert result['status']=='RECEIVER_CLOSED' and not f.commands
    assert result['stationary_qualification']['status']=='STATIONARY_RETENTION_SEQUENCE_OBSERVED'
    receipt=json.loads((tmp_path/'receiver-receipt.json').read_text())
    assert receipt==result and (tmp_path/'receiver.stderr').read_bytes()==b''
    rows=[json.loads(l) for l in (tmp_path/'journal.jsonl').read_text().splitlines()]
    assert len([r for r in rows if r['event']=='selection_credit'])==8
    assert len([r for r in rows if r['event']=='sample'])==16 and rows[-1]['event']=='footer'
    assert all(r['observed_state']['mode']==0 and not r['observed_state']['armed'] for r in result['stationary_qualification']['observations'])


def test_staged_bootstrap_rejects_repeated_metadata_after_readiness(current_source):
    src,f=source_fixture(current_source);src.prepare_metadata(timeout_s=stream.BOOTSTRAP_CONTRACT['total_s'])
    f.enqueue({'event':'rpc_request','accepted':True})
    with pytest.raises(Exception,match='RPC repeated'):src._next(1)
    assert src.failed and src.metadata_prepared_monotonic_s is not None


def test_bootstrap_budget_is_finite_sum_not_watch_tolerance():
    b=stream.BOOTSTRAP_CONTRACT
    assert b['total_s']==b['initial_availability_s']+b['rpc_response_s']+b['scene_request_s']+b['records']*b['record_write_s']==5.75
    assert b['new_pair_timeout_s']==1. and not b['bootstrap_pair_is_live_observation']
    assert b['credits']=='B1_METADATA_I1_W2_S2_D2'


def test_stationary_watch_gap_is_not_hidden_by_fresh_transfer(current_source):
    src,f=source_fixture(current_source);original=f.grant
    def delayed(phase,timeout_s):
        if phase=='W':f.clock.sleep(.51)
        original(phase,timeout_s)
    f.grant=delayed
    result=stream.qualify_stationary_source(src,limits())
    assert result['status']=='UNCONFIRMED' and result['failed_phase']=='W'
    # Poll's original freshness guard can reject the previous pair before it
    # even consumes a newly queued pair after that gap; retain never blesses it.
    assert result['error']['reason']=='Receiver current sample stale/future'
    assert src.counts=={'/ap/v3/status':3,'/rover1/odometry':3}
    assert min(10-v for v in src.counts.values())==7 and not f.commands
