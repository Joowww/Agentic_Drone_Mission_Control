"""Offline fault injection: no Docker, ROS, receiver or lifecycle execution."""
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import Mock

import pytest

from tools.rover_xrce_trace import passive_trial as d, selection as s
from tools import rover_observation_stream as stream

OWNER='12345678-1234-4234-8234-123456789abc'
REQUIRED=['tools/rover_identity_probe/observation_receiver.cpp',
          'tools/rover_identity_probe/session_context.hpp',
          'tools/rover_identity_probe/parameter_rpc.hpp',
          'tools/rover_observation_stream.py','tools/rover_xrce_trace/passive_trial.py','tools/rover_xrce_trace/selection.py',
          'tools/rover_identity_probe/CMakeLists.txt','tools/rover_passive_rclcpp/collector_core.hpp',
          'tools/rover_passive_rclcpp/observer.hpp']

@pytest.fixture
def selection(tmp_path):
    agent=json.loads(Path('tools/rover_xrce_trace/diagnostic-agent.rpc.json').read_text())
    for name in REQUIRED:
        p=tmp_path/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_text('synthetic')
    reader=dict(schema='tfg.rover-transport-reader/1',prepared=True,
        agent_selection_sha256=s.digest(agent),max_samples=20,duration_s=120,max_wire_bytes=448*1024,
        binary={'path':'/tmp/synthetic/rover_observation_receiver','sha256':'a'*64},
        native_dependencies={'/opt/ros/humble/lib/synthetic.so':'b'*64},
        source_hashes={name:hashlib.sha256((tmp_path/name).read_bytes()).hexdigest() for name in REQUIRED})
    ap=tmp_path/'agent.json';rp=tmp_path/'reader.json'
    ap.write_text(json.dumps(agent));rp.write_text(json.dumps(reader))
    return tmp_path,ap,rp,agent,reader

@pytest.mark.parametrize('case',['unprepared','pair','digest','source','bounds','dependencies','schema'])
def test_selection_rejected_before_any_command(selection,case,monkeypatch):
    root,ap,rp,agent,reader=selection
    if case=='unprepared':reader['prepared']=False
    elif case=='pair':
        agent.update(dict(zip((k+'_sha256' for k in ('wrapper','library','bridge','bridge_library')),s.IDENTITY_ARTIFACTS)))
        ap.write_text(json.dumps(agent));reader['agent_selection_sha256']=s.digest(agent)
    elif case=='digest':reader['agent_selection_sha256']='0'*64
    elif case=='source':(root/REQUIRED[0]).write_text('changed')
    elif case=='bounds':reader['max_samples']=21
    elif case=='dependencies':reader['native_dependencies']={}
    else:reader['schema']='unknown'
    rp.write_text(json.dumps(reader));command=Mock();monkeypatch.setattr(d.LocalPorts,'command',command)
    with pytest.raises(ValueError):d.LocalPorts(root,root,ap,rp)
    command.assert_not_called()

@pytest.mark.parametrize('case',['missing','altered'])
def test_binary_precheck_failure_never_opens(selection,case):
    root,ap,rp,_,_=selection;ports=d.LocalPorts(root,root,ap,rp)
    # The container-side precheck reports either missing or altered pinned ELF.
    ports.command=Mock(return_value=2)
    assert ports.start()['status']=='BLOCKED'
    assert [call.args[0] for call in ports.command.call_args_list]==['receiver-precheck']


def test_sources_rechecked_before_start(selection):
    root,ap,rp,_,_=selection;ports=d.LocalPorts(root,root,ap,rp);ports.command=Mock()
    (root/REQUIRED[0]).write_text('changed after constructor')
    with pytest.raises(ValueError):ports.start()
    ports.command.assert_not_called()

@pytest.mark.parametrize('failure',[OSError('disk'),KeyboardInterrupt()])
def test_start_receipt_failure_or_interrupt_stops_once_and_preserves_result(tmp_path,monkeypatch,failure):
    ports=NS(start=Mock(return_value={'status':'SUCCESS','operation':{'owner_id':OWNER}}),
        admit=Mock(),reader=Mock(),stop=Mock(return_value={'status':'SUCCESS'}),post=Mock(return_value={'status':'OFFLINE'}))
    original=d.write_once
    def write(path,value):
        if path.name=='start-result.json':raise failure
        return original(path,value)
    monkeypatch.setattr(d,'write_once',write)
    if isinstance(failure,KeyboardInterrupt):
        with pytest.raises(KeyboardInterrupt):d.execute_once(tmp_path/'driver',ports)
    else:d.execute_once(tmp_path/'driver',ports)
    result=json.loads((tmp_path/'driver/driver-result.json').read_text())
    assert result['error']['type']==type(failure).__name__ and result['start']['status']=='SUCCESS'
    ports.stop.assert_called_once_with(OWNER);ports.reader.assert_not_called()
    with pytest.raises(FileExistsError):d.execute_once(tmp_path/'driver',ports)
    ports.start.assert_called_once()

@pytest.mark.parametrize('case',['success','parse','interrupt','disk'])
def test_capture_closes_preserves_raw_and_attempts_all_receipts(tmp_path,monkeypatch,case):
    tmp_path.chmod(0o700);prefix=tmp_path/'prefix';prefix.mkdir()
    (prefix/'selection.json').write_text(json.dumps({'descriptor':{'lifecycle_id':OWNER}}))
    monkeypatch.setattr(d,'admit_from_prefix',lambda p:{'measurement_allowed':True})
    source=NS(footer=None,close_attempted=False,close_result=None,frames=NS(stderr=b'diagnostic'))
    def close(**kw):
        source.close_attempted=True;source.close_result={'return_code':0,'receiver_closed':True}
    source.close=Mock(side_effect=close)
    def start(*args,**kw):
        kw['raw_sink'](b'original wire bytes\n')
        return source
    monkeypatch.setattr(stream,'start_receiver',start)
    def next_record(*args,**kw):
        if case=='parse':raise ValueError('synthetic parse error')
        if case=='interrupt':raise KeyboardInterrupt()
        source.footer={'reader_closed':True}
    source._next=next_record
    original=d.write_once;attempts=[]
    def write(path,value):
        attempts.append(path.name)
        if case=='disk' and path.name=='transfer-events.json':raise OSError('synthetic disk error')
        return original(path,value)
    monkeypatch.setattr(d,'write_once',write)
    if case=='interrupt':
        with pytest.raises(KeyboardInterrupt):d.capture_transport_from_prefix(prefix,'/unused','a'*64,tmp_path)
    else:result=d.capture_transport_from_prefix(prefix,'/unused','a'*64,tmp_path)
    source.close.assert_called_once()
    receipt=json.loads((tmp_path/'receiver-receipt.json').read_text())
    assert (tmp_path/'journal.jsonl').read_bytes()==b'original wire bytes\n'
    assert receipt['return_code']==0 and receipt['movement_authorized'] is False
    assert 'receiver-receipt.json' in attempts
    if case in {'parse','interrupt'}:assert 'reason' in receipt
    if case=='disk':assert result['persistence']=='UNCERTAIN' and receipt['persistence_errors']


def test_prepare_interruption_preserves_command_and_blocks_replay(selection,monkeypatch):
    root,ap,rp,_,_=selection;ports=d.LocalPorts(root,root,ap,rp)
    monkeypatch.setattr(d.subprocess,'run',Mock(side_effect=KeyboardInterrupt()))
    with pytest.raises(KeyboardInterrupt):ports.command('reader-prepare',['synthetic'],1)
    assert json.loads((root/'reader-prepare-command.json').read_text())['error']=='KeyboardInterrupt'
    with pytest.raises(FileExistsError):ports.command('reader-prepare',['synthetic'],1)
    d.subprocess.run.assert_called_once()


def test_dry_run_never_executes_or_opens(selection,monkeypatch):
    root,ap,rp,_,reader=selection
    command=Mock(side_effect=AssertionError('No commands in dry-run'))
    monkeypatch.setattr(d.LocalPorts,'command',command)
    result=d.selection_dry_run(root,ap,rp)
    assert result['selection_files_valid'] and result['status']=='BLOCKED' and not result['executed']
    reader['prepared']=False;rp.write_text(json.dumps(reader))
    assert not d.selection_dry_run(root,ap,rp)['selection_files_valid']
    command.assert_not_called()


def socket_review_selection(selection):
    root,ap,rp,agent,reader=selection
    helpers=['tools/rover_xrce_trace/monitor.py','tools/rover_xrce_trace/socket_inventory.py']
    for name in helpers:
        (root/name).write_text('explicitly synthetic socket helper')
        reader['source_hashes'][name]=hashlib.sha256((root/name).read_bytes()).hexdigest()
    review={'schema':'tfg.socket-helper-review/1','binary_manifests_byte_identical_to_parent':True,
        'source_changes':{k:{'before':'a'*64,'after':reader['source_hashes'][k]} for k in helpers},
        'query_timeout_s':.75,'cooperative_s':.25,'interval_s':5.,'samples':64,
        'row_bytes':262144,'journal_bytes':16777216}
    path=root/'socket-helper-review.json';path.write_text(json.dumps(review))
    reader['socket_helper_review_sha256']=hashlib.sha256(path.read_bytes()).hexdigest();rp.write_text(json.dumps(reader))
    return root,ap,rp,reader,path,review


def test_socket_review_is_explicit_pinned_consumed_and_rechecked(selection,monkeypatch):
    root,ap,rp,reader,path,review=socket_review_selection(selection)
    command=Mock();monkeypatch.setattr(d.LocalPorts,'command',command)
    assert not d.selection_dry_run(root,ap,rp)['selection_files_valid']
    assert d.selection_dry_run(root,ap,rp,socket_helper_review=path)['selection_files_valid']
    ports=d.LocalPorts(root,root,ap,rp,socket_helper_review=path)
    path.write_text(json.dumps({**review,'extra':'changed after selection'}))
    with pytest.raises(ValueError,match='hash differs'):ports.start()
    command.assert_not_called()


@pytest.mark.parametrize('case',['no_binding','missing','altered','wrong_pin','helper_changed','limits','unreviewed_helper'])
def test_socket_review_mismatch_never_reaches_commands(selection,monkeypatch,case):
    root,ap,rp,reader,path,review=socket_review_selection(selection)
    if case=='no_binding':reader.pop('socket_helper_review_sha256')
    elif case=='missing':path.unlink()
    elif case=='altered':path.write_text('{}')
    elif case=='wrong_pin':reader['socket_helper_review_sha256']='0'*64
    elif case=='helper_changed':(root/'tools/rover_xrce_trace/monitor.py').write_text('altered')
    else:
        if case=='limits':review['query_timeout_s']=1.
        else:review['source_changes'].pop('tools/rover_xrce_trace/monitor.py')
        path.write_text(json.dumps(review));reader['socket_helper_review_sha256']=hashlib.sha256(path.read_bytes()).hexdigest()
    rp.write_text(json.dumps(reader));command=Mock();monkeypatch.setattr(d.LocalPorts,'command',command)
    with pytest.raises((ValueError,OSError)):d.LocalPorts(root,root,ap,rp,socket_helper_review=path)
    command.assert_not_called()


@pytest.mark.parametrize('bad',[None,'digest','binary','dependencies','snapshot','contract','socket_binding','missing'])
def test_new_native_receiver_uses_explicit_build_review_without_unchanged_claim(selection,monkeypatch,bad):
    root,ap,rp,reader,path,review=socket_review_selection(selection)
    build={'schema':'tfg.rover-transport-build-review/1','preparation_valid':True,'snapshot_unchanged':True,
           'artifacts':{'receiver':dict(reader['binary'])},'native_dependencies':dict(reader['native_dependencies']),
           'contract':{'pure_cpp_contract':'PASSED','dds_participant_created':False,'ros_initialized':False}}
    if bad=='binary':build['artifacts']['receiver']['sha256']='f'*64
    elif bad=='dependencies':build['native_dependencies']={}
    elif bad=='snapshot':build['snapshot_unchanged']=False
    elif bad=='contract':build['contract']['dds_participant_created']=True
    provenance=root/'build-review.json';provenance.write_text(json.dumps(build))
    sha=hashlib.sha256(provenance.read_bytes()).hexdigest()
    reader.update(provenance=str(provenance),provenance_sha256=sha,helper_review={'receiver_build_review_sha256':sha})
    review.update(binary_manifests_byte_identical_to_parent=False,receiver_build_review_sha256=sha)
    if bad=='digest':reader['helper_review']['receiver_build_review_sha256']='0'*64
    elif bad=='socket_binding':review['receiver_build_review_sha256']='0'*64
    elif bad=='missing':provenance.unlink()
    path.write_text(json.dumps(review));reader['socket_helper_review_sha256']=hashlib.sha256(path.read_bytes()).hexdigest();rp.write_text(json.dumps(reader))
    command=Mock();monkeypatch.setattr(d.LocalPorts,'command',command)
    if bad is None:assert d.selection_dry_run(root,ap,rp,socket_helper_review=path)['selection_files_valid']
    else:
        with pytest.raises((ValueError,OSError)):d.LocalPorts(root,root,ap,rp,socket_helper_review=path)
    command.assert_not_called()
