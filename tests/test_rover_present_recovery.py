"""Explicitly synthetic present observations; no live socket, Docker or ROS calls."""
import copy
import json
from pathlib import Path
from unittest.mock import patch
import importlib.util
import sys

import pytest

from tools.rover_xrce_trace import present_resources as r, present_recovery as recovery, historical_disposition as d
from tools.rover_xrce_trace.session_precheck import closure_archive_reference
from tests.test_rover_socket_inventory import tree, put, udp, stat, HEADER, FixtureClock


@pytest.fixture
def proc(tree):
    root,_=tree
    put(root,'self/stat',stat(100,10));(root/'self/ns/time').symlink_to('time:[44]')
    for name in ('udp','udp6','tcp','tcp6'):put(root,'self/net/'+name,HEADER)
    return root


def collect(proc):return r.collect(r.expected_scope(),reader=r.s.Reader(proc,clock=FixtureClock()))


def test_free_reads_all_tables_to_eof_with_existing_bounds(proc):
    value=collect(proc)
    assert value['status']=='FREE',value
    assert len(value['table_reads'])==8
    assert all(value['reads'][i]['operation']=='bytes_to_eof' for i in value['table_reads'])
    assert value['budget']['cooperative_s']==.25 and value['budget']['reads']==2048


@pytest.mark.parametrize('kind',['foreign','wildcard','dual_stack','shared','unknown','foreign_namespace','tcp_timewait'])
def test_occupied_relevant_endpoint_always_rejects(proc,kind):
    if kind=='dual_stack':
        put(proc,'self/net/udp6',HEADER+udp(43,'0'*32,2019).replace('00000000:0000','0'*32+':0000'))
    elif kind=='tcp_timewait':put(proc,'self/net/tcp',HEADER+udp(0,'00000000',5760).replace(' 07 ',' 06 '))
    else:put(proc,'self/net/udp',HEADER+udp(43,'00000000' if kind=='wildcard' else '0100007F',2019))
    if kind=='shared':(proc/'200/fd/2').symlink_to('socket:[43]')
    elif kind=='unknown':(proc/'300/fd/8').unlink()
    elif kind=='foreign_namespace':
        (proc/'300/ns/net').unlink();(proc/'300/ns/net').symlink_to('net:[999]')
    value=collect(proc);assert value['status']=='OCCUPIED',value
    row=value['occupied'][0]
    assert row['ownership']=={'shared':'SHARED','unknown':'UNKNOWN','tcp_timewait':'UNKNOWN','foreign_namespace':'FOREIGN_NAMESPACE'}.get(kind,'FOREIGN')
    if kind=='dual_stack':assert row['possible_dual_stack']
    if kind=='wildcard':assert row['local']['wildcard']
    if kind=='tcp_timewait':
        assert row['kernel_state_name']=='TIME_WAIT'
        assert row['resource_state']=='TIME_WAIT_COOLDOWN'
        assert value['reasons']==['RELEVANT_TCP_TIME_WAIT_COOLDOWN']


@pytest.mark.parametrize(('code','name','classification','reason'),[
    ('01','ESTABLISHED','ACTIVE','RELEVANT_LOCAL_ENDPOINT_OCCUPIED'),
    ('06','TIME_WAIT','TIME_WAIT_COOLDOWN','RELEVANT_TCP_TIME_WAIT_COOLDOWN'),
    ('0A','LISTEN','ACTIVE','RELEVANT_LOCAL_ENDPOINT_OCCUPIED'),
    ('FF','UNKNOWN','UNKNOWN','RELEVANT_LOCAL_ENDPOINT_STATE_UNKNOWN'),
])
def test_tcp_states_are_explicit_but_never_treated_as_free(proc,code,name,classification,reason):
    row=udp(0,'00000000',5760).replace(' 07 ',' '+code+' ')
    put(proc,'self/net/tcp',HEADER+row)
    value=collect(proc)
    assert value['status']=='OCCUPIED',value
    assert value['reasons']==[reason]
    assert value['occupied'][0]['kernel_state_name']==name
    assert value['occupied'][0]['resource_state']==classification
    assert value['occupied'][0]['ownership']=='UNKNOWN'
    assert r.unpack(r.pack(value))==value
    decision=r.acquisition_decision(value)
    assert not decision['accepted']
    if code=='06':
        assert ('tcp',5760) in decision['tcp_not_listening']
        assert 'ENDPOINT_OWNER_NOT_UNIQUE_KNOWN' in decision['reasons']


def test_malformed_tcp_state_is_incomplete_and_never_free(proc):
    row=udp(0,'00000000',5760).replace(' 07 ',' GG ')
    put(proc,'self/net/tcp',HEADER+row)
    value=collect(proc)
    assert value['status']=='INCOMPLETE',value
    assert value['reasons']==['Malformed TCP table']


@pytest.mark.parametrize('kind',['permission','truncated','pid_changed','context_changed','eof_missing'])
def test_incomplete_or_changed_observation_never_free(proc,kind):
    put(proc,'self/net/udp',HEADER+udp(43,'00000000',2019))
    if kind=='truncated':put(proc,'self/net/udp',HEADER+udp(43,'00000000',2019)[:-1])
    class Changed(r.s.Reader):
        def __init__(self):super().__init__(proc,clock=FixtureClock());self.calls={}
        def get(self,name,*args,**kw):
            self.calls[name]=self.calls.get(name,0)+1
            if kind=='permission' and name=='300/fd':raise r.s.Incomplete('EACCES')
            if kind=='pid_changed' and name=='300/stat' and self.calls[name]==2:put(proc,name,stat(300,31))
            if kind=='context_changed' and name=='self/ns/time' and self.calls[name]==2:
                (proc/name).unlink();(proc/name).symlink_to('time:[999]')
            answer=super().get(name,*args,**kw)
            if kind=='eof_missing' and name=='self/net/udp':self.reads[answer[1]]['operation']='bytes'
            return answer
    value=r.collect(r.expected_scope(),reader=Changed())
    assert value['status']=='INCOMPLETE',value
    assert value['reasons']


@pytest.fixture
def review_data(proc,monkeypatch):
    history=Path(__file__).resolve().parents[1]/'simulation/ros2_gazebo/results/rover_identity_trial_2026_10_26/1cb9d86a-659b-4aa8-b7b1-214d2202210f'
    records=json.loads((history/'post-current-records-serializable.json').read_text())
    records.update(recovery_basis=recovery.BASIS,historical_evidence=closure_archive_reference(history))
    records['inventory']['boot_id']='boot'
    value=collect(proc);value['reader_hashes']=recovery.reader_hashes()
    now=value['finished_monotonic']+.01
    host_context={'clock':'CLOCK_MONOTONIC','process':{'pid':999,'start_ticks':42,'boot_id':'SYNTHETIC-HOST'},'time_namespace':'time:[HOST]'}
    monkeypatch.setattr(recovery,'host_clock_context',lambda:copy.deepcopy(host_context))
    records['inventory']['query_context_before']={k:value['context'][k] for k in ('boot_id','net_namespace','pid_namespace','time_namespace')}
    records['inventory']['query_context_after']=copy.deepcopy(records['inventory']['query_context_before'])
    current=dict(disposition_state='NOT_ATTEMPTED',disposition_schema=None,complete=True,observed_monotonic=now-.1,restriction=None,guards={},other_sessions=[],host_processes=[],host_boot_id='SYNTHETIC-HOST',host_time_namespace='time:[HOST]',resources=value,
        host_acquisition={'basis':recovery.HOST_WINDOW,'started_monotonic':now-.1,'received_monotonic':now-.01,
                          'clock_context':copy.deepcopy(host_context),'received_clock_context':copy.deepcopy(host_context)})
    return records,current,now


def test_synthetic_present_review_does_not_repair_historical_freshness(review_data):
    records,current,now=review_data;report=d.dry_run(records,current,now=now)
    assert report['status']=='DRY_RUN_ELIGIBLE',report
    assert report['scope']['historical_limitations']['historical_fresh_observation'] is False
    assert report['scope']['historical']['monitor']['phase']=='INCOMPLETE'
    assert report['scope']['protocol']==recovery.BASIS
    assert not report['movement_authorized'] and not report['opening_authorized']


@pytest.mark.parametrize('kind',['reservation','process','session','old','incomplete','identity','context','reader','scope','resources_old','occupied','audit_interrupted','old_audit'])
def test_present_review_rejects_pending_or_unknown_facts(review_data,kind):
    records,current,now=copy.deepcopy(review_data)
    if kind=='audit_interrupted':current['disposition_state']='APPLYING_UNCONFIRMED'
    elif kind=='old_audit':current.update(disposition_state='DISPOSED_DIAGNOSTICALLY_INCOMPLETE',disposition_schema='tfg.diagnostic-disposition/2')
    elif kind=='reservation':current['guards']={'v3.json':'pending'}
    elif kind=='process':records['inventory']['owned']=[{'pid':99}]
    elif kind=='session':records['inventory']['state_files']['/tmp/other']='unreviewed'
    elif kind=='old':current['observed_monotonic']=now-4
    elif kind=='incomplete':current['complete']=False
    elif kind=='identity':records['environment']['container_id']='0'*64
    elif kind=='context':current['resources']['context']['time_namespace']='time:[999]'
    elif kind=='reader':current['resources']['reader_hashes']={}
    elif kind=='scope':current['resources']['scope']['endpoints']=[]
    elif kind=='resources_old':current['resources']['finished_monotonic']=now-4
    elif kind=='occupied':current['resources'].update(status='OCCUPIED',reasons=['RELEVANT_LOCAL_ENDPOINT_OCCUPIED'])
    assert d.dry_run(records,current,now=now)['status']=='BLOCKED'


def test_synthetic_audit_consumption_rechecks_resources_and_context(review_data,tmp_path):
    records,current,now=review_data;report=d.dry_run(records,current,now=now)
    owner=records['target']['descriptor']['lifecycle_id'];sha=report['scope_sha256']
    engine=d.OfflineDisposition(tmp_path/'audit',clock=lambda:now,owner=owner)
    audit=engine.apply(records,lambda:current,scope_sha256=sha,authorization=f'AUTHORIZE_DIAGNOSTIC_DISPOSITION {owner} {sha}')
    assert audit['schema']==recovery.SCHEMA and audit['offline_only']
    assert len(audit['application_observations'])==2
    assert d.assess_disposition(records,current,audit,now=now)['historical_pointer_resolved']
    current['resources']['status']='OCCUPIED'
    assert not d.assess_disposition(records,current,audit,now=now)['historical_pointer_resolved']
    current['resources']['status']='FREE';records['environment']['state']['StartedAt']='2026-10-27T15:58:02Z'
    assert not d.assess_disposition(records,current,audit,now=now)['historical_pointer_resolved']


def test_context_change_during_application_rejected(review_data,tmp_path):
    records,current,now=review_data;report=d.dry_run(records,current,now=now);calls=[]
    def read():
        calls.append(1)
        if len(calls)==2:records['environment']['state']['StartedAt']='2026-10-27T15:58:02Z'
        return current
    owner=records['target']['descriptor']['lifecycle_id'];sha=report['scope_sha256']
    engine=d.OfflineDisposition(tmp_path/'audit',clock=lambda:now,owner=owner)
    with pytest.raises(ValueError,match='Changed'):engine.apply(records,read,scope_sha256=sha,authorization=f'AUTHORIZE_DIAGNOSTIC_DISPOSITION {owner} {sha}')
    assert engine.query()['status']=='NOT_ATTEMPTED'


def test_interrupted_persistence_is_uncertain_and_never_replayed(review_data,tmp_path):
    records,current,now=review_data;report=d.dry_run(records,current,now=now)
    def fail(path,value):raise KeyboardInterrupt('SYNTHETIC interruption after durable claim')
    owner=records['target']['descriptor']['lifecycle_id'];sha=report['scope_sha256']
    engine=d.OfflineDisposition(tmp_path/'audit',clock=lambda:now,owner=owner,write=fail)
    with pytest.raises(KeyboardInterrupt):engine.apply(records,lambda:current,scope_sha256=sha,authorization=f'AUTHORIZE_DIAGNOSTIC_DISPOSITION {owner} {sha}')
    assert engine.query()['status']=='APPLYING_UNCONFIRMED'
    with pytest.raises(ValueError):engine.apply(records,lambda:pytest.fail('no replay'),scope_sha256=sha,authorization=f'AUTHORIZE_DIAGNOSTIC_DISPOSITION {owner} {sha}')


def test_bound_endpoints_and_startup_failure_guard(tmp_path,monkeypatch):
    path=Path(__file__).resolve().parents[1]/'simulation/ros2_gazebo/scripts/sim_processes.py'
    spec=importlib.util.spec_from_file_location('present_guard_fixture',path);m=importlib.util.module_from_spec(spec);sys.modules[spec.name]=m;spec.loader.exec_module(m)
    log=tmp_path/'launch.log';monkeypatch.setattr(m,'LOG_FILE',log)
    log.write_text('launch running\n');assert m.verify_start_log()['success']
    log.write_text('bind: Address already in use\n')
    with pytest.raises(RuntimeError,match='bind failure'):m.verify_start_log()
    value={'status':'OCCUPIED','scope':r.expected_scope(),'occupied':[{'protocol':e['protocol'],'local':{'port':e['port']},'ownership':'KNOWN','kernel_state_hex':'0A' if e['protocol']=='tcp' else '07'} for e in r.expected_scope()['endpoints']]}
    value.update(table_reads=list(range(8)),reads=[{'operation':'bytes_to_eof','state':'OBSERVED',
                 'source':'/proc/self/net/'+name} for name in ('udp','udp6','tcp','tcp6')*2])
    r.require_acquired(value)
    value['occupied'][0]['ownership']='FOREIGN'
    with pytest.raises(ValueError,match='acquisition'):r.require_acquired(value)


def test_distinct_socket_inodes_sharing_endpoint_are_reported_shared(proc):
    put(proc,'self/net/udp',HEADER+udp(42,'00000000',2019)+udp(43,'0100007F',2019))
    value=collect(proc)
    assert value['status']=='OCCUPIED' and all(row['ownership']=='SHARED' for row in value['occupied'])


def test_configuration_drift_fails_without_peer_fallback(monkeypatch):
    config={k:'SYNTHETIC '+k for k in r.CONFIG_PATHS}
    monkeypatch.setattr(r,'CONFIG_HASHES',{k:r.hashlib.sha256(v.encode()).hexdigest() for k,v in config.items()})
    assert r.scope(config['top'],config)==r.expected_scope()
    config['robot']='SYNTHETIC changed binding'
    with pytest.raises(ValueError,match='configuration changed'):r.scope(config['top'],config)


def test_project_apply_route_is_only_exercised_in_synthetic_tmp_project(review_data,tmp_path,monkeypatch):
    records,current,now=review_data;calls=[]
    lockroot=tmp_path/'generated/vehicle_locks';lockroot.mkdir(parents=True)
    monkeypatch.setattr(d.locks,'LOCK_ROOT',lockroot)
    def read(context=None,*,present=False):
        calls.append(present);assert present is True
        return copy.deepcopy(records),copy.deepcopy(current)
    monkeypatch.setattr(d,'current_records',read)
    report=d.dry_run(records,current,now=now);owner=records['target']['descriptor']['lifecycle_id'];sha=report['scope_sha256']
    engine=d.ProjectDisposition(owner);engine.clock=lambda:now
    audit=engine.apply_reviewed(scope_sha256=sha,authorization=f'AUTHORIZE_DIAGNOSTIC_DISPOSITION {owner} {sha}',present=True)
    assert calls==[True,True] and audit['schema']==recovery.SCHEMA
    result=d.diagnostic_precheck(records,current,audit,now=now)
    assert result['precheck_satisfied'] is True and not result['opening_authorized']
    assert not list(lockroot.glob('*.json'))


def test_present_basis_is_not_an_exception_for_e837(review_data):
    from tools.rover_xrce_trace.session_precheck import recorded_cleanup_archive
    records,current,now=review_data
    directory=Path(__file__).resolve().parents[1]/'simulation/ros2_gazebo/results/rover_identity_trial_2026_10_26/5379b30c-ac91-4cc8-808b-a7c28bb41801'
    ref=closure_archive_reference(directory);history=recorded_cleanup_archive(ref)['historical']
    records.update(history,historical_evidence=ref)
    pointer=records['target']['descriptor']
    records['environment']={'status':'ACTIVE',**records['environment_reference']['environment'],'state':records['environment_reference']['pre_start_state']}
    records['inventory']['state_files']={rkey:json.dumps({**pointer,'status':'BLOCKED','movement_authorized':False,'source_association_verified':False}) for rkey in records['inventory']['state_files']}
    records['inventory']['files']={pointer['prefix']+'/'+n:json.dumps(records[k]) for k,n in [('selection','selection.json'),('launch','launch.json'),('monitor','capture/monitor.json')]}
    assert d.dry_run(records,current,now=now)['status']=='DRY_RUN_ELIGIBLE'


@pytest.mark.parametrize('shift',[-1e8,1e8])
def test_sdk_epoch_and_namespace_do_not_define_host_freshness(review_data,shift):
    records,current,now=review_data
    value=current['resources']
    value['started_monotonic']+=shift;value['finished_monotonic']+=shift
    for row in value['reads']:
        row['started_monotonic']+=shift;row['finished_monotonic']+=shift
    assert value['context']['time_namespace']!=current['host_time_namespace']
    report=d.dry_run(records,current,now=now)
    assert report['status']=='DRY_RUN_ELIGIBLE',report
    assert report['conditions']['resource_duration'] and report['conditions']['host_window_complete']


def test_host_window_closes_after_validation_and_slow_query_blocks(review_data,monkeypatch):
    records,current,now=review_data;events=[];real_hashes=recovery.reader_hashes
    def validate():events.append('validated');return real_hashes()
    def clock():assert events==['validated'];return current['host_acquisition']['started_monotonic']+3.1
    monkeypatch.setattr(recovery,'reader_hashes',validate)
    report=d.dry_run(records,current,clock=clock)
    assert report['status']=='BLOCKED' and not report['conditions']['fresh_observation']
    assert report['current_review']['host_window_s']==pytest.approx(3.1)


def test_old_host_sample_cannot_be_renewed_by_recent_receipt_or_sdk_time(review_data):
    records,current,now=review_data
    current['host_acquisition']['started_monotonic']=current['observed_monotonic']=now-4
    current['host_acquisition']['received_monotonic']=now-.001
    report=d.dry_run(records,current,now=now)
    assert report['conditions']['host_window_complete']
    assert report['status']=='BLOCKED' and not report['conditions']['fresh_observation']


@pytest.mark.parametrize('change',['host_clock','sdk_context','receipt_before_start','receipt_future'])
def test_changed_context_or_invalid_host_window_rejected(review_data,change,monkeypatch):
    records,current,now=review_data
    if change=='host_clock':
        context=copy.deepcopy(current['host_acquisition']['clock_context']);context['time_namespace']='time:[OTHER_HOST]'
        monkeypatch.setattr(recovery,'host_clock_context',lambda:context)
    elif change=='sdk_context':records['inventory']['query_context_after']['net_namespace']='net:[changed]'
    elif change=='receipt_before_start':current['host_acquisition']['received_monotonic']=now-1
    else:current['host_acquisition']['received_monotonic']=now+1
    assert d.dry_run(records,current,now=now)['status']=='BLOCKED'


@pytest.mark.parametrize('change',[None,'sdk_namespace','incarnation','engine','container'])
def test_complete_host_acquisition_groups_reads_and_checks_both_contexts(review_data,tmp_path,monkeypatch,change):
    """Actual host reader with doubled Docker results; no live subprocess."""
    import types
    import subprocess
    from tools import reconciliation_environment as env
    records,current,_=review_data
    root=tmp_path/'generated';lockroot=root/'vehicle_locks';lockroot.mkdir(parents=True)
    monkeypatch.setattr(d.locks,'LOCK_ROOT',lockroot)
    target=records['target'];owner=target['descriptor']['lifecycle_id'];closing=target['closed_by']
    for name,value in [('diagnostic_agent_session.json',target),
        ('simulation_lifecycle/'+owner+'/operation.json',records['start_operation']),
        ('simulation_lifecycle/'+closing+'/operation.json',records['stop_operation']),
        ('simulation_lifecycle/'+owner+'/rover_environment_reference.json',records['environment_reference'])]:
        p=root/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(value))
    fake_proc=tmp_path/'host-proc';fake_proc.mkdir();boot=tmp_path/'host-boot';boot.write_text('SYNTHETIC-HOST')
    real_path=Path
    monkeypatch.setattr(d,'Path',lambda p:fake_proc if str(p)=='/proc' else boot if str(p)=='/proc/sys/kernel/random/boot_id' else real_path(p))
    monkeypatch.setattr(d.locks,'restriction',lambda:None)
    monkeypatch.setattr(d.ProjectDisposition,'query',lambda self:{'status':'NOT_ATTEMPTED'})
    before=copy.deepcopy(records['environment']);after=copy.deepcopy(before)
    if change=='incarnation':after['state']['StartedAt']='2026-10-27T15:58:02Z'
    elif change=='engine':after['engine_id']='different-engine'
    elif change=='container':after['container_id']='b'*64
    samples=iter([before,after]);snapshots=[]
    def metadata(*,final=False):snapshots.append(final);return next(samples)
    monkeypatch.setattr(env,'inspect_review_environment',metadata)
    monkeypatch.setattr(env,'inspect_environment',lambda:pytest.fail('No redundant five-call probe'))
    monkeypatch.setattr(env,'read_container_boot_id',lambda e:pytest.fail('Boot recheck belongs inside the SDK request'))
    inventory=copy.deepcopy(records['inventory']);inventory['resources']=copy.deepcopy(current['resources'])
    if change=='sdk_namespace':inventory['query_context_after']['net_namespace']='net:[CHANGED]'
    calls=[]
    def sdk(argv,**kwargs):
        calls.append(argv)
        assert argv[:3]==['docker','exec','-i']
        payload=json.loads(kwargs['input']);assert payload['present'] is True
        return types.SimpleNamespace(returncode=0,stdout=json.dumps(inventory),stderr='')
    monkeypatch.setattr(subprocess,'run',sdk)
    if change:
        with pytest.raises(ValueError,match='changed'):d.current_records({},present=True)
    else:
        actual,observed=d.current_records({},present=True)
        assert observed['host_acquisition']['started_monotonic']<=observed['host_acquisition']['received_monotonic']
        # Resource SDK epoch is unrelated to the real monotonic used by this host test.
        actual['historical_evidence']=records['historical_evidence']  # explicit --evidence, as in the CLI
        report=d.dry_run(actual,observed)
        assert report['status']=='DRY_RUN_ELIGIBLE',report
    assert len(calls)==1 and snapshots==([False] if change=='sdk_namespace' else [False,True])


def test_sealed_function_result_inventory_v1_remains_readable():
    from tools.rover_xrce_trace.session_precheck import recorded_cleanup_archive
    directory=Path(__file__).resolve().parents[1]/'evaluation/operations/rover_status_authorized_window_2026_10_31/8a4d30bd-ed13-45bc-b181-fd24f1f4dc5c'
    reference=closure_archive_reference(directory)
    historical=recorded_cleanup_archive(reference)['historical']
    assert set(historical)=={'target','start_operation','stop_operation','environment_reference','selection','launch','monitor'}
    assert historical['monitor']['phase']=='INCOMPLETE'
