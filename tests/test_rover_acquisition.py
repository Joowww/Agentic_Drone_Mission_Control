"""Explicit synthetic /proc, backend and lifecycle fixtures. No live resources."""
import copy
from dataclasses import replace
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest
from tools.rover_xrce_trace import present_resources as r, selection
from simulation.ros2_gazebo.scripts import sim_processes as supervisor
from tools import simulation_lifecycle as lifecycle, vehicle_execution_lock as locks
from tests.test_rover_present_recovery import proc, review_data
from tests.test_rover_socket_inventory import tree, put, udp, FixtureClock, HEADER
from tests.test_failed_start_protected_close import failed, model


@pytest.fixture
def acquired(proc):
    rows={'udp':[],'tcp':[]}
    for i,e in enumerate(r.expected_scope()['endpoints']):
        inode=1000+i
        row=udp(inode,'0100007F',e['port'])
        if e['protocol']=='tcp':row=row.replace(' 07 ',' 0A ')
        rows[e['protocol']].append(row)
        (proc/'200/fd'/str(20+i)).symlink_to('socket:['+str(inode)+']')
    for protocol,items in rows.items():put(proc,'self/net/'+protocol,HEADER+''.join(items))
    return proc


def collect(root):
    return r.collect(r.expected_scope(),reader=r.s.Reader(root,clock=FixtureClock()),known_processes={(200,20)})


def test_valid_acquisition_and_endpoint_missing(acquired):
    v=collect(acquired);r.require_acquired(v)
    row=r.unpack(v)['occupied'][0]
    text=(acquired/'self/net'/row['protocol']).read_text()
    put(acquired,'self/net/'+row['protocol'],'\n'.join(l for l in text.splitlines() if not l.startswith('0: '+row['local']['proc_encoding']))+'\n')
    decision=r.acquisition_decision(collect(acquired))
    assert not decision['accepted'] and 'REQUIRED_ENDPOINT_MISSING' in decision['reasons']
    assert [row['protocol'],row['local']['port']] in [list(e) for e in decision['missing_endpoints']]


@pytest.mark.parametrize('kind',['foreign','shared','unknown','not_listening','incomplete','repeated_table','lost_owner_read'])
def test_acquisition_rejects_unsafe_owner_and_coverage(acquired,kind):
    if kind=='not_listening':put(acquired,'self/net/tcp',(acquired/'self/net/tcp').read_text().replace(' 0A ',' 01 '))
    elif kind=='shared':(acquired/'300/fd/99').symlink_to('socket:[1000]')
    elif kind=='unknown':(acquired/'200/fd/20').unlink()
    elif kind=='incomplete':put(acquired,'self/net/tcp',(acquired/'self/net/tcp').read_bytes()[:-1])
    v=collect(acquired)
    if kind=='foreign':
        v=r.collect(r.expected_scope(),reader=r.s.Reader(acquired,clock=FixtureClock()),known_processes=set())
    elif kind=='repeated_table':v['table_reads']=[v['table_reads'][0]]*8
    elif kind=='lost_owner_read':v['reads'][-1]['state']='UNKNOWN'
    with pytest.raises(ValueError,match='acquisition rejected'):r.require_acquired(v)
    assert not r.acquisition_decision(v)['accepted']


def test_verbose_read_redundancy_compacts_losslessly_under_unchanged_limit(acquired):
    for i in range(650):(acquired/'200/fd'/str(100+i)).symlink_to('/dev/null')
    wire=collect(acquired);expanded=r.unpack(wire)
    assert wire['schema']==r.WIRE_SCHEMA
    assert len(json.dumps(expanded).encode())>r.s.MAX_BYTES==262144
    assert len(json.dumps(wire).encode())<=r.s.MAX_BYTES
    assert r.pack(expanded)==wire and expanded['counts']['read_calls']<=2048
    assert len(expanded['owners_before'])==len(expanded['owners_after'])==10
    assert len(expanded['table_reads'])==8
    r.require_acquired(wire)
    # No fabricated provenance: every expanded read and FD owner survives codec.
    assert all(expanded['reads'][i]['operation']=='bytes_to_eof' for i in expanded['table_reads'])


def test_output_budget_insufficient_still_rejects_without_unknown_promotion(acquired,monkeypatch):
    monkeypatch.setattr(r.s,'MAX_BYTES',8192)  # synthetic tighter budget, never operational
    v=collect(acquired)
    assert v['status']=='INCOMPLETE' and v['reasons']==['RESOURCE_OUTPUT_BUDGET']
    assert len(json.dumps(v).encode())<=8192
    with pytest.raises(ValueError,match='RESOURCE_OUTPUT_BUDGET'):r.require_acquired(v)


def test_compact_encoding_corruption_cannot_be_accepted(acquired):
    v=r.pack(collect(acquired));v['encoding']['reads'][0][1]=1000000
    with pytest.raises(ValueError):r.require_acquired(v)


def test_existing_present_consumer_accepts_lossless_encoding_without_new_authorization(review_data):
    from tools.rover_xrce_trace import historical_disposition
    records,current,now=review_data
    current['resources']=r.pack(current['resources'])
    value=historical_disposition.dry_run(records,current,now=now)
    assert value['status']=='DRY_RUN_ELIGIBLE' and not value['opening_authorized']


def test_structured_rejection_keeps_original_observation(acquired,monkeypatch,tmp_path):
    monkeypatch.setattr(supervisor,'verify_start_log',lambda:None)
    monkeypatch.setattr(r,'read_config',lambda:{})
    monkeypatch.setattr(r,'scope',lambda *a:r.expected_scope())
    monkeypatch.setattr(supervisor,'INSTALLED_ROVER_LAUNCH',tmp_path/'launch');(tmp_path/'launch').write_text('fixture')
    monkeypatch.setattr(supervisor,'snapshot',lambda:{})
    monkeypatch.setattr(supervisor,'remembered_identities',lambda:set())
    original=collect(acquired);original['status']='INCOMPLETE';original['reasons']=['SYNTHETIC_COVERAGE_LOSS']
    monkeypatch.setattr(r,'collect',lambda *a,**k:original)
    result=supervisor.verify_acquisition()
    assert not result['success'] and result['resource_observation'] is original
    assert 'SYNTHETIC_COVERAGE_LOSS' in result['error']
    assert result['decision']['coverage']['reader_reasons']==['SYNTHETIC_COVERAGE_LOSS']


def test_current_diagnostic_session_excludes_other_project_tags(model,monkeypatch,tmp_path):
    sha=selection.digest(model)
    current=supervisor.Process(10,1,100,('ros2',),True,False,sha)
    child=supervisor.Process(11,10,110,('child',))
    other=supervisor.Process(20,1,200,('foreign launch',),True,False,'other-session')
    table={p.pid:p for p in (current,child,other)}
    assert set(supervisor.select_owned(table,set()))=={10,11,20}  # reproduced old overbroad basis
    assert set(supervisor.select_session_owned(table,sha))=={10,11}
    pointer=tmp_path/'pointer';selection.atomic_record(pointer,model)
    monkeypatch.setattr(supervisor,'DIAGNOSTIC_STATE',pointer)
    monkeypatch.setenv('TFG_DIAGNOSTIC_AGENT',json.dumps(model))
    monkeypatch.setattr(supervisor,'snapshot',lambda:table)
    monkeypatch.setattr(supervisor,'verify_start_log',lambda:None)
    monkeypatch.setattr(r,'read_config',lambda:{})
    monkeypatch.setattr(r,'scope',lambda *a:r.expected_scope())
    launch=tmp_path/'launch';launch.write_text('fixture');monkeypatch.setattr(supervisor,'INSTALLED_ROVER_LAUNCH',launch)
    def observe(scope,*,known_processes):
        assert known_processes=={(10,100),(11,110)}
        return {'status':'INCOMPLETE','scope':scope,'reasons':['SYNTHETIC_STOP_AFTER_OWNERSHIP_CHECK']}
    monkeypatch.setattr(r,'collect',observe)
    result=supervisor.verify_acquisition()
    assert not result['success'] and result['ownership_context']['descriptor_sha256']==sha


def test_other_session_contradiction_overrides_descendancy_and_remembered_identity():
    root=supervisor.Process(10,1,100,('launch',),True,False,'current')
    other=supervisor.Process(20,10,200,('other',),True,False,'other-session')
    assert set(supervisor.select_session_owned({10:root,20:other},'current',{other.identity}))=={10}


def test_acquisition_rejection_reaches_existing_owner_fenced_close(failed,monkeypatch):
    owner,old,target=failed
    # Synthetic failed start already contains the persisted acquisition failure.
    root=Path(target['operation_path']).parent
    payload={'success':False,'resource_observation':{'status':'INCOMPLETE','reasons':['RESOURCE_OUTPUT_BUDGET']}}
    (root/'acquisition.stdout').write_text(json.dumps(payload)+'\n')
    def backend(action,*args):
        assert action=='stop'
        assert locks.restriction()['closing_failed_start']==old
        assert json.loads((root/'acquisition.stdout').read_text())==payload
        return 0
    monkeypatch.setattr(lifecycle,'_backend',backend)
    result=lifecycle.run_lifecycle('stop',gui=False,profile='two_drones_rover',close_owner=owner)
    assert result['status']=='SUCCESS' and locks.restriction() is None
    assert json.loads(Path(target['operation_path']).read_text())==old


@pytest.mark.parametrize('rc',[0,1])
def test_real_backend_preserves_exact_acquisition_channels_with_fake_commands(tmp_path,rc):
    """Run real shell only against fake Python/Docker/flock; no real SDK access."""
    source=Path(__file__).resolve().parents[1]
    script=tmp_path/'project/simulation/ros2_gazebo/scripts/start_sim_backend.sh';script.parent.mkdir(parents=True)
    script.write_bytes((source/'simulation/ros2_gazebo/scripts/start_sim_backend.sh').read_bytes())
    (script.parent.parent/'launch').mkdir();(script.parent.parent/'launch/tfg_demo.launch.py').write_text('synthetic')
    py=tmp_path/'project/.venv/bin/python';py.parent.mkdir(parents=True)
    py.write_text('''#!/usr/bin/env python3
import sys
if 'tools.simulation_profiles' in sys.argv:
 print({'launch-package':'ardupilot_gz_bringup','launch-file':'tfg_demo.launch.py','ports-json':'[5760,5770,5780]','status-topics':'/ap/v1/status\\n/ap/v2/status\\n/ap/v3/status'}[sys.argv[-1]])
''');py.chmod(0o755)
    fake=tmp_path/'bin';fake.mkdir();docker=fake/'docker'
    docker.write_text('''#!/usr/bin/env python3
import sys,os
args=sys.argv[1:]
if args and args[-1]=='verify-acquisition':
 sys.stdout.buffer.write(b'{"success":false,"resource_observation":{"status":"INCOMPLETE","reasons":["fixture"]}}\\n');sys.stderr.buffer.write(b'original-stderr\\n');sys.exit(int(os.environ['FIXTURE_ACQ_RC']))
if any('ros2 topic list' in a for a in args):print('/ap/v1/status\\n/ap/v2/status\\n/ap/v3/status')
''');docker.chmod(0o755)
    flock=fake/'flock';flock.write_text('#!/bin/sh\nexit 0\n');flock.chmod(0o755)
    resultdir=tmp_path/'receipts';resultdir.mkdir()
    env={k:v for k,v in os.environ.items() if k not in ('TFG_DIAGNOSTIC_AGENT','TFG_DIAGNOSTIC_CLOSE_TARGET')}
    env.update(PATH=str(fake)+os.pathsep+env['PATH'],TFG_SIM_PROFILE='two_drones_rover',TFG_SIM_START_CONTEXT='synthetic',TFG_LIFECYCLE_RESULT_DIR=str(resultdir),FIXTURE_ACQ_RC=str(rc))
    # Avoid the real /tmp mutex even though flock is fake.
    script.write_text(script.read_text().replace('/tmp/tfg_simulation_control.lock',str(tmp_path/'fake-control.lock')))
    p=subprocess.run(['bash',str(script)],env=env,capture_output=True,timeout=10)
    assert p.returncode==rc,p.stderr
    assert (resultdir/'acquisition.stdout').read_bytes()==b'{"success":false,"resource_observation":{"status":"INCOMPLETE","reasons":["fixture"]}}\n'
    assert (resultdir/'acquisition.stderr').read_bytes()==b'original-stderr\n'
    assert (resultdir/'acquisition.returncode').read_text()==str(rc)+'\n'
    assert (b'SIMULATION READY' in p.stdout)==(rc==0)


@pytest.mark.parametrize('bad',[None,'owner','descriptor','action','missing_receipt'])
def test_single_attempt_driver_routes_rejection_to_owner_fenced_stop(failed,monkeypatch,tmp_path,bad):
    from tools.rover_xrce_trace import passive_trial
    owner,old,target=failed
    # Actual LocalPorts.stop + actual run_lifecycle; only start and backend are fake.
    port=passive_trial.LocalPorts.__new__(passive_trial.LocalPorts)
    port.root=tmp_path/'driver';port.root.mkdir(mode=0o700)
    # Isolated fixture tree: LocalPorts' target path is pointed at this fixture.
    port.repo=tmp_path/'project';p=port.repo/'missions/generated/diagnostic_agent_session.json';p.parent.mkdir(parents=True)
    p.write_text(json.dumps(target))
    start={'status':'UNCONFIRMED','operation':copy.deepcopy(old)}
    stored=copy.deepcopy(start)
    if bad=='owner':stored['operation']['owner_id']='different'
    elif bad=='descriptor':stored['operation']['diagnostic_agent']={}
    elif bad=='action':stored['operation']['action']='stop'
    if bad!='missing_receipt':(port.root/'start.stdout').write_text(json.dumps(stored))
    stops=[]
    def backend(action,*args):stops.append(action);return 0
    monkeypatch.setattr(lifecycle,'_backend',backend)
    def command(name,argv,timeout):
        assert name=='stop' and argv[-2:]==['--close-owner',owner]
        value=lifecycle.run_lifecycle('stop',gui=False,profile='two_drones_rover',close_owner=argv[-1])
        (port.root/'stop.stdout').write_text(json.dumps(value));return 0
    port.command=command
    if bad:
        with pytest.raises((ValueError,FileNotFoundError)):port.stop(owner)
        assert stops==[] and locks.restriction()==old
    else:
        port.start=lambda:start
        port.admit=lambda owner:pytest.fail('No admission after rejected start')
        port.reader=lambda owner:pytest.fail('No receiver after rejected start')
        port.post=lambda owner:{'scope':'SYNTHETIC_OFFLINE_NO_QUERY'}
        value=passive_trial.execute_once(port.root,port)
        assert value['start']['status']=='UNCONFIRMED' and value['stop']['status']=='SUCCESS'
        assert stops==['stop'] and locks.restriction() is None
