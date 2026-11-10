"""Fake /proc only; never runs an operational collector or queries real sockets."""
import json
from pathlib import Path
from types import SimpleNamespace
import subprocess

import pytest

from tools.rover_xrce_trace import socket_inventory as s
from tools.rover_xrce_trace.monitor import SocketRecorder


def write_trace(prefix,identity,port=35242):
    # Evidence-derived fixture: retained writer/commit structure; process IDs and
    # selected peer changed for fake /proc. Never operational evidence.
    from pathlib import Path
    source=Path(__file__).resolve().parents[1]/'simulation/ros2_gazebo/results/rover_xrce_trial_2026_10_24/cedfd5c5-9955-4ca0-b61a-0a4bda305098'
    owner='c974c925-db90-4874-acaa-21c862efa53f'
    data=(source/'container_after/container_copies/tmp/tfg_diagnostic_agents'/owner/'capture/trace.log').read_text()
    rows=[]
    for line in data.splitlines():
        row=json.loads(line.split('TFG_XRCE_TRACE ',1)[1]);row.update(pid=identity['pid'],process_start_ticks=str(identity['start_ticks']),boot_id=identity['boot_id'])
        if row['client_instance']==1 and row.get('transport_peer'):
            row['transport_peer'].update(address='127.0.0.1',port=int.from_bytes(port.to_bytes(2,'big'),'little'))
        rows.append('TFG_XRCE_TRACE '+json.dumps(row))
    (prefix/'capture').mkdir(parents=True,exist_ok=True)
    (prefix/'capture/trace.log').write_text('\n'.join(rows)+'\n')


def put(root, name, data):
    p=root/name; p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(data if isinstance(data,bytes) else data.encode())


def stat(pid, ticks):
    fields=['S','1']+['0']*17+[str(ticks)]
    return f'{pid} (name with spaces) '+ ' '.join(fields)


def process(root, pid, ticks, executable='ardurover', argv=None):
    put(root,f'{pid}/stat',stat(pid,ticks))
    p=root/str(pid); (p/'fd').mkdir(exist_ok=True)
    (p/'ns').mkdir(exist_ok=True)
    (p/'exe').symlink_to('/usr/bin/'+executable)
    (p/'ns/net').symlink_to('net:[42]'); (p/'ns/pid').symlink_to('pid:[43]')
    put(root,f'{pid}/cmdline',argv or (executable+'\0--sysid\03\0').encode())


def udp(inode=42, address='0100007F', port=35242):
    return f'0: {address}:{port:04X} 00000000:0000 07 00000000:00000000 00:00000000 00000000 0 0 {inode} 2 0000000000000000 0\n'


HEADER='sl local_address rem_address st tx_queue rx_queue tr tm->when retrnsmt uid timeout inode\n'


@pytest.fixture
def tree(tmp_path):
    root=tmp_path/'proc'; root.mkdir()
    put(root,'sys/kernel/random/boot_id','boot')
    (root/'self/ns').mkdir(parents=True)
    (root/'self/ns/net').symlink_to('net:[42]');(root/'self/ns/pid').symlink_to('pid:[43]')
    put(root,'self/net/udp',HEADER+udp()+udp(43,'00000000',2019))
    put(root,'self/net/udp6',HEADER.replace('rem_address','remote_address'))
    process(root,100,10,'ros2',b'ros2\0launch\0')
    process(root,200,20,argv=b'ardurover\0--sysid\x003\0--password\0SECRET\0--api-key\0PRIVATE\0')
    process(root,300,30,'micro_ros_agent',b'micro_ros_agent\0udp4\0--port\x002019\0')
    (root/'200/fd/7').symlink_to('socket:[42]'); (root/'300/fd/8').symlink_to('socket:[43]')
    context={'lifecycle_id':'trial','environment':{'container_id':'declared-container','engine_id':'declared-engine','image_id':'declared-image'},
             'anchor_process':{'pid':100,'start_ticks':10,'boot_id':'boot'},
             'agent_process':{'pid':300,'start_ticks':30,'boot_id':'boot'},'agent_executable':'/usr/bin/micro_ros_agent','peers':[{'family':'IPv4','address':'127.0.0.1','port':35242}],
             'native_byte_order':'little','transport_source_sha256':'0d3d11252c58b65c85762390b5c79f72a2b9f4efdae6547b09da43a611a96217'}
    return root,context


class FixtureClock:
    """Synthetic realistic-width reception times, not observed latency."""
    def __init__(self):self.n=0
    def __call__(self):
        self.n+=1;return 155000.123456789+self.n/10000000


def collect(tree, reader=None):
    root,context=tree
    return s.collect(context,reader=reader or s.Reader(root,clock=FixtureClock()))


def writer():
    return {'pid':300,'process_start_ticks':'30','boot_id':'boot','client_instance':1,'client_key':3,
            'session_id':129,'transport_peer':{'family':'IPv4','address':'127.0.0.1','port':int.from_bytes((35242).to_bytes(2,'big'),'little'),
            'source':'Processor InputMessage metadata before session queue','generation_binding':'SAME_PROXYCLIENT_REFERENCE'}}


def test_correct_unconnected_udp_is_metadata_not_packet_origin(tree):
    result=collect(tree)
    assert result['snapshot_state']=='REPEATED_READS_AGREE',result['reasons']
    row=next(r for r in result['associations'] if r['inode']=='42')
    assert row['local']['address']=='127.0.0.1' and row['local']['port']==35242
    assert row['remote_state']=='UNCONNECTED'
    assert row['owners'][0]['fd']==7 and row['owners'][0]['process']['start_ticks']==20
    assert row['owners'][0]['process']['boot_id']=='boot'
    assert row['owners'][0]['argv']['permitted_arguments']==[['--sysid','3']]
    assert all(r['at_utc'] and r['finished_monotonic']>=r['started_monotonic'] for r in result['reads'])
    assert 'SECRET' not in json.dumps(result) and 'PRIVATE' not in json.dumps(result)
    match=s.match_peer(result,writer(),'trial')
    assert match['link_state']=='EXACT_ENDPOINT_UNIQUE_VISIBLE_PROCESS_CANDIDATE'
    assert match['packet_origin_verified'] is False and match['status']=='BLOCKED'


def test_shared_socket_keeps_every_owner_and_fd(tree):
    root,_=tree
    (root/'100/fd/9').symlink_to('socket:[42]');(root/'200/fd/10').symlink_to('socket:[42]')
    result=collect(tree);row=next(r for r in result['associations'] if r['inode']=='42')
    assert {(o['process']['pid'],o['fd']) for o in row['owners']}=={(100,9),(200,7),(200,10)}
    assert s.match_peer(result,writer(),'trial')['link_state']=='SHARED_OWNERS_AMBIGUOUS'


def test_no_visible_owner_does_not_prove_absence(tree):
    (tree[0]/'200/fd/7').unlink()
    result=collect(tree)
    assert s.match_peer(result,writer(),'trial')['link_state']=='NO_VISIBLE_OWNER_UNKNOWN'


def test_reuseport_duplicate_endpoint_not_silently_selected(tree):
    root,_=tree
    put(root,'self/net/udp',HEADER+udp()+udp(99))
    (root/'100/fd/9').symlink_to('socket:[99]')
    assert s.match_peer(collect(tree),writer(),'trial')['link_state']=='MULTIPLE_SOCKETS_AMBIGUOUS'


def test_wildcard_bind_remains_candidate(tree):
    put(tree[0],'self/net/udp',HEADER+udp(address='00000000'))
    assert s.match_peer(collect(tree),writer(),'trial')['link_state']=='WILDCARD_BIND_CANDIDATE_ONLY'


@pytest.mark.parametrize('kind',['pid','fd','table','namespace','argv'])
def test_changes_across_reads_block_association(tree,kind):
    root,_=tree
    class Changing(s.Reader):
        hits=0
        def get(self,relative,operation='bytes',limit=65536):
            value=super().get(relative,operation,limit)
            trigger={'pid':'200/stat','fd':'200/fd/7','table':'self/net/udp','namespace':'self/ns/net','argv':'200/cmdline'}[kind]
            if relative==trigger:
                self.hits+=1
                if self.hits==1:
                    if kind in ('pid','argv'):put(root,'200/stat',stat(200,999))
                    elif kind=='fd':
                        (root/'200/fd/7').unlink();(root/'200/fd/7').symlink_to('socket:[43]')
                    elif kind=='table':put(root,'self/net/udp',HEADER+udp(43,'00000000',2019))
                    else:
                        (root/'self/ns/net').unlink();(root/'self/ns/net').symlink_to('net:[999]')
            return value
    result=collect(tree,Changing(root,clock=lambda:0))
    assert result['snapshot_state']=='INCOMPLETE' and result['reasons']
    assert not result['associations']
    assert s.match_peer(result,writer(),'trial')['link_state']=='UNKNOWN'


@pytest.mark.parametrize('error',[PermissionError(13,'denied'),FileNotFoundError(2,'disappeared')])
def test_unreadable_or_disappeared_fd_unknown_not_empty(tree,monkeypatch,error):
    original=s.os.readlink
    def read(path):
        if str(path).endswith('/200/fd/7'):raise error
        return original(path)
    monkeypatch.setattr(s.os,'readlink',read)
    result=collect(tree)
    assert result['snapshot_state']=='INCOMPLETE' and result['reasons']
    assert any(r.get('state')=='UNKNOWN' for r in result['reads'])


def test_context_wrong_or_missing_blocks(tree):
    root,ctx=tree;ctx['anchor_process']['start_ticks']=999
    assert collect(tree)['reasons']==['ACCREDITED_CONTEXT_MISMATCH']
    assert s.collect({},reader=s.Reader(root,clock=lambda:0))['snapshot_state']=='INCOMPLETE'


def test_foreign_process_namespace_cannot_be_ignored(tree):
    root,_=tree;(root/'200/ns/net').unlink();(root/'200/ns/net').symlink_to('net:[999]')
    report=collect(tree)
    assert s.match_peer(report,writer(),'trial')['link_state']=='FOREIGN_NAMESPACE_OWNER_AMBIGUOUS'
    assert report['associations'][0]['owners'][0]['process']['pid']==200


def test_ipv6_and_endian_contract():
    assert s.endpoint('0100007F:89AA','udp','little')['address']=='127.0.0.1'
    assert s.endpoint('7F000001:89AA','udp','big')['address']=='127.0.0.1'
    assert s.endpoint('00000000000000000000000001000000:ABCD','udp6','little')['address']=='::1'
    assert s.endpoint('0000000000000000FFFF00000100007F:ABCD','udp6','little')['family']=='IPv6'
    with pytest.raises(ValueError):s.endpoint('bad:0000','udp')


def test_malformed_and_duplicate_inode_unknown(tree):
    root,_=tree;put(root,'self/net/udp',HEADER+udp()+udp())
    assert collect(tree)['reasons']==['DUPLICATE_SOCKET_INODE']
    put(root,'self/net/udp',HEADER+'broken\n')
    assert collect(tree)['snapshot_state']=='INCOMPLETE'


def test_read_and_wall_budgets(tree,monkeypatch):
    monkeypatch.setattr(s,'MAX_READS',2)
    assert collect(tree)['reasons']==['READ_OR_WALL_BUDGET']
    clock=iter([0.,1.,1.,1.])
    assert collect(tree,s.Reader(tree[0],clock=lambda:next(clock)))['snapshot_state']=='INCOMPLETE'


def test_peer_rejects_mixed_sessions_or_agent_pid(tree):
    result=collect(tree)
    assert s.match_peer(result,writer(),'different')['link_state']=='UNKNOWN'
    w=writer();w['process_start_ticks']='999'
    assert s.match_peer(result,w,'trial')['link_state']=='UNKNOWN'
    w=writer();w['transport_peer']=None
    assert s.match_peer(result,w,'trial')['link_state']=='UNKNOWN'


def test_internal_monitor_sampling_separate_and_bounded(tmp_path):
    value={'lifecycle_id':'trial','manifest':{'engine_id':'e','container_id':'c','image_id':'i'}}
    (tmp_path/'capture').mkdir()
    calls=[]
    def runner(args,**kw):
        calls.append((args,kw));ctx=json.loads(kw['input'])
        return SimpleNamespace(returncode=0,stdout=json.dumps({'schema':'tfg.xrce-sockets/1','status':'BLOCKED',
            'movement_authorized':False,'source_association_verified':False,'context_declared_by_protected_monitor':ctx,
            'snapshot_state':'REPEATED_READS_AGREE'}).encode())
    rec=SocketRecorder(tmp_path,value,runner=runner)
    root={'pid':100,'start_ticks':10,'boot_id':'b'};agent={'pid':300,'start_ticks':30,'boot_id':'b','executable':'/usr/bin/micro_ros_agent','native_byte_order':'little'}
    write_trace(tmp_path,agent)
    rec.sample(root,agent,0);rec.sample(root,agent,1);rec.sample(root,agent,5);rec.close()
    assert len(calls)==2
    assert all(c[1]['timeout']==.75 for c in calls)
    assert len((tmp_path/'capture/sockets.jsonl').read_text().splitlines())==2
    assert (tmp_path/'capture/sockets.jsonl').stat().st_mode & 0o777==0o600


def test_monitor_timeout_never_retries_or_alters_agent(tmp_path):
    (tmp_path/'capture').mkdir()
    calls=[]
    def runner(*a,**kw):
        calls.append(1);raise subprocess.TimeoutExpired('passive child',.75)
    rec=SocketRecorder(tmp_path,{'lifecycle_id':'x','manifest':{'engine_id':'e','container_id':'c','image_id':'i'}},runner=runner)
    identity={'pid':1,'start_ticks':1,'boot_id':'b','executable':'/usr/bin/micro_ros_agent','native_byte_order':'little'}
    write_trace(tmp_path,identity)
    rec.sample(identity,identity,0);rec.sample(identity,identity,10);rec.close()
    assert len(calls)==1 and rec.summary()['state']=='UNKNOWN'



def test_arbitrary_context_and_argv_never_copied(tree):
    root,ctx=tree;ctx['credentials']='SECRET'
    report=collect(tree)
    assert report['snapshot_state']=='INCOMPLETE' and report['context_declared_by_protected_monitor'] is None
    assert 'SECRET' not in json.dumps(report)
    assert s.argv_permitted(b'SECRET\0--token\0PRIVATE\0')['argv0_basename']=='NOT_RECORDED'


def test_output_budget_preserves_explicit_incompleteness(tree,monkeypatch):
    monkeypatch.setattr(s,'MAX_BYTES',4096)
    report=collect(tree)
    assert report['snapshot_state']=='INCOMPLETE' and not report['associations']
    assert len(json.dumps(s.pack_inventory(report),separators=(',',':')).encode())<=4096



def test_only_query_directory_fd_is_excluded_not_its_socket(tree,monkeypatch):
    root,_=tree
    (root/'200/fd/11').symlink_to(root/'200/fd')
    monkeypatch.setattr(s.os,'getpid',lambda:200)
    result=collect(tree)
    assert result['snapshot_state']=='REPEATED_READS_AGREE'
    assert any(event.get('ignored_query_directory_fds')==['11'] for event in result['reads'])
    assert next(r for r in result['associations'] if r['inode']=='42')['owners'][0]['fd']==7



def test_fd_budget_is_unknown_not_empty(tree,monkeypatch):
    monkeypatch.setattr(s,'MAX_FDS',1)
    assert collect(tree)['snapshot_state']=='INCOMPLETE'


def test_socket_recorder_write_failure_does_not_recollect(tmp_path):
    from unittest.mock import Mock
    value={'lifecycle_id':'trial','manifest':{'engine_id':'e','container_id':'c','image_id':'i'}}
    calls=[]
    def runner(*args,**kw):
        calls.append(1);ctx=json.loads(kw['input'])
        return SimpleNamespace(returncode=0,stdout=json.dumps({'schema':'tfg.xrce-sockets/1','status':'BLOCKED',
            'movement_authorized':False,'source_association_verified':False,'context_declared_by_protected_monitor':ctx,
            'snapshot_state':'REPEATED_READS_AGREE'}).encode())
    rec=SocketRecorder(tmp_path,value,runner=runner);rec.output=Mock()
    (tmp_path/'capture').mkdir()
    probe=(tmp_path/'capture/probe').open('wb')
    rec.output.fileno.return_value=probe.fileno()
    rec.output.write.side_effect=OSError('fake disk failure')
    identity={'pid':1,'start_ticks':1,'boot_id':'b','executable':'/usr/bin/micro_ros_agent','native_byte_order':'little'}
    write_trace(tmp_path,identity)
    rec.sample(identity,identity,0);rec.sample(identity,identity,10)
    assert len(calls)==1 and rec.count==0 and rec.summary()['state']=='UNKNOWN'
    probe.close()


def test_planned_incomplete_samples_are_kept_separate(tmp_path):
    (tmp_path/'capture').mkdir()
    value={'lifecycle_id':'trial','manifest':{'engine_id':'e','container_id':'c','image_id':'i'}}
    def runner(*args,**kw):
        return SimpleNamespace(returncode=0,stdout=json.dumps({'schema':'tfg.xrce-sockets/1','status':'BLOCKED',
            'movement_authorized':False,'source_association_verified':False,'context_declared_by_protected_monitor':json.loads(kw['input']),
            'snapshot_state':'INCOMPLETE','reasons':['PROCESS_DISAPPEARED']}).encode())
    rec=SocketRecorder(tmp_path,value,runner=runner);identity={'pid':1,'start_ticks':1,'boot_id':'b','executable':'/usr/bin/micro_ros_agent','native_byte_order':'little'}
    write_trace(tmp_path,identity)
    rec.sample(identity,identity,0);rec.sample(identity,identity,5);rec.close()
    assert rec.summary()['state']=='PARTIAL_SNAPSHOTS' and rec.incomplete==2
    assert all(json.loads(line)['snapshot_state']=='INCOMPLETE' for line in (tmp_path/'capture/sockets.jsonl').read_text().splitlines())



def test_series_cannot_cherry_pick_changed_or_truncated_records(tree):
    first=collect(tree)
    root,_=tree
    put(root,'200/stat',stat(200,999))
    second=collect(tree)
    data=b'\n'.join(json.dumps(row).encode() for row in (first,second))+b'\n'
    report=s.analyze_series(data,{'snapshots':2,'error':None},writer(),'trial')
    assert report['series_state']=='UNCERTAIN_OR_INCOMPLETE' and report['errors']
    assert s.analyze_series(data[:-1],{'snapshots':2},writer(),'trial')['errors']
    assert s.analyze_series(data,{'snapshots':3},writer(),'trial')['errors']


def test_repeated_series_is_candidate_not_identity(tree):
    row=collect(tree);data=(json.dumps(row)+'\n').encode()*2
    report=s.analyze_series(data,{'snapshots':2,'error':None},writer(),'trial')
    assert report['series_state']=='REPEATED_ENDPOINT_PROCESS_CANDIDATE_ONLY'
    assert report['source_association_verified'] is False and report['movement_authorized'] is False



def test_agent_exec_change_without_pid_recycle_is_unknown(tree):
    root,_=tree
    (root/'300/exe').unlink();(root/'300/exe').symlink_to('/usr/bin/other-agent')
    assert collect(tree)['reasons']==['AGENT_CONTEXT_MISMATCH']


def test_representative_fixture_compacts_without_raising_limits(tree):
    # SYNTHETIC fixture, not reconstructed historical /proc. 32 visible processes,
    # 3 FDs each approximate launch+SITL+bridges seen in f338; same read limits.
    root,_=tree
    for pid in range(400,429):
        process(root,pid,pid*10,'python3',b'python3\0')
        for fd in range(3):(root/f'{pid}/fd/{fd}').symlink_to('/dev/null')
    row=collect(tree)
    assert row['snapshot_state']=='REPEATED_READS_AGREE',row['reasons']
    wire=s.pack_inventory(row)
    raw=len(json.dumps(row,separators=(',',':')).encode())
    packed=len(json.dumps(wire,separators=(',',':')).encode())
    assert raw>packed and packed+1<=s.MAX_BYTES,(raw,packed)
    assert s.unpack_inventory(wire)==row
    assert s.match_peer(wire,writer(),'trial')['link_state']=='EXACT_ENDPOINT_UNIQUE_VISIBLE_PROCESS_CANDIDATE'


def pipeline(tmp_path,tree,row,expected_writer=None):
    """Real monitor serialization, persisted JSONL and existing offline reader; fake transport only."""
    root,ctx=tree;prefix=tmp_path/'monitor';(prefix/'capture').mkdir(parents=True)
    value={'lifecycle_id':ctx['lifecycle_id'],'manifest':ctx['environment']}
    def runner(args,**kw):
        assert json.loads(kw['input'])==ctx
        return SimpleNamespace(returncode=0,stdout=json.dumps(s.pack_inventory(row),separators=(',',':')).encode())
    write_trace(prefix,{**ctx['agent_process'],'executable':ctx['agent_executable'],'native_byte_order':'little'},port=ctx['peers'][0]['port'])
    recorder=SocketRecorder(prefix,value,runner=runner)
    recorder.sample(ctx['anchor_process'],{**ctx['agent_process'],'executable':ctx['agent_executable'],'native_byte_order':'little'},0)
    recorder.close();data=(prefix/'capture/sockets.jsonl').read_bytes()
    return data,recorder.summary(),s.analyze_series(data,recorder.summary(),expected_writer or writer(),ctx['lifecycle_id'])


def test_monitor_wire_reader_analysis_end_to_end(tmp_path,tree):
    data,summary,report=pipeline(tmp_path,tree,collect(tree))
    assert json.loads(data)['schema']=='tfg.xrce-sockets/2'
    assert report['series_state']=='REPEATED_ENDPOINT_PROCESS_CANDIDATE_ONLY'
    assert report['source_association_verified'] is False
    assert s.analyze_series(data[:-3],summary,writer(),'trial')['errors']


@pytest.mark.parametrize('mutation',['source','owner','process','context','truncated_pool','association','missing_declared_context'])
def test_missing_or_contradictory_references_fail_closed(tree,mutation):
    row=collect(tree);wire=s.pack_inventory(row)
    if mutation=='source':wire['sources']=[]
    elif mutation=='owner':wire['owners'][0]['source_reads']=[999999]
    elif mutation=='process':
        changed={**wire['processes'][0],'start_ticks':999};wire['processes'].append(changed)
        old=wire['record']['owners_after'][0]
        wire['owners'].append({**wire['owners'][old],'process_ref':len(wire['processes'])-1})
        wire['record']['owners_after'][0]=len(wire['owners'])-1
    elif mutation=='context':wire['record']['context_after']=None
    elif mutation=='missing_declared_context':wire['record']['context_declared_by_protected_monitor']=None
    elif mutation=='truncated_pool':wire['processes']=[]
    else:wire['record']['associations'][0]['association_state']='MADE_UP'
    report=s.analyze_series((json.dumps(wire)+'\n').encode(),{'snapshots':1},writer(),'trial')
    assert report['series_state']=='UNCERTAIN_OR_INCOMPLETE'
    assert report['source_association_verified'] is False


@pytest.mark.parametrize('kind',['shared','disappeared','pid','volume'])
def test_incomplete_and_ambiguous_pipeline(tmp_path,tree,monkeypatch,kind):
    root,_=tree
    if kind=='shared':(root/'100/fd/10').symlink_to('socket:[42]')
    elif kind=='disappeared':(root/'200/fd/7').unlink();(root/'200/fd/7').symlink_to('missing')
    elif kind=='volume':monkeypatch.setattr(s,'MAX_BYTES',4096)
    if kind=='pid':
        class Reused(s.Reader):
            count=0
            def get(self,name,*args,**kwargs):
                value=super().get(name,*args,**kwargs)
                if name=='200/stat':
                    self.count+=1
                    if self.count==1:put(root,'200/stat',stat(200,999))
                return value
        row=collect(tree,Reused(root,clock=lambda:0))
    else:row=collect(tree)
    data,summary,report=pipeline(tmp_path,tree,row)
    assert report['series_state']=='UNCERTAIN_OR_INCOMPLETE'
    assert not report['source_association_verified']


def stress(tree, background=20, unrelated_sockets=100, unrelated_fds=3):
    """SYNTHETIC stress. FD/inode topology was not retained in the live fallback."""
    root,_=tree
    for n in range(background):
        pid=400+n;process(root,pid,1000+n,'python3',b'python3\0')
        for fd in range(unrelated_fds):(root/f'{pid}/fd/{fd}').symlink_to('/dev/null')
    put(root,'self/net/udp',HEADER+udp()+udp(43,'00000000',2019)+''.join(udp(1000+n,port=40000+n) for n in range(unrelated_sockets)))
    for n in range(unrelated_sockets):(root/f'300/fd/{100+n}').symlink_to(f'socket:[{1000+n}]')


def old_measure(tree):
    # Execute only frozen Python algorithm on the FAKE proc. Never import/write
    # caches into historical evidence. Captured before fallback for this fixture.
    import types,hashlib
    source=Path(__file__).resolve().parents[1]/'simulation/ros2_gazebo/results/rover_xrce_trial_2026_10_24/cedfd5c5-9955-4ca0-b61a-0a4bda305098/source_snapshots/tools/rover_xrce_trace/socket_inventory.py'
    data=source.read_bytes()
    assert hashlib.sha256(data).hexdigest()=='8f541fde54bb6f0d9fb0344913012012891b6429088dd4ef5da75eb83ea82907'
    mod=types.ModuleType('frozen_algorithm_offline_fixture');mod.__file__=str(source)
    exec(compile(data,str(source),'exec'),mod.__dict__)
    observed=[]
    def dumps(value,*args,**kwargs):
        encoded=json.dumps(value,*args,**kwargs)
        if isinstance(value,dict) and value.get('schema')=='tfg.xrce-sockets/2':
            observed.append({'wire_bytes':len(encoded.encode())+1,'section_value_bytes':
                {k:len(json.dumps(v,separators=(',',':')).encode()) for k,v in value.items()},
                'read_events':len(value['reads']),'owners':len(value['owners']),
                'processes':len(value['processes']),'sockets':len(value['sockets']),
                'pre_fallback_reasons':value['record']['reasons'][:]})
        return encoded
    mod.json=types.SimpleNamespace(dumps=dumps,loads=json.loads)
    expected={k:v for k,v in tree[1].items() if k not in {'peers','native_byte_order','transport_source_sha256'}}
    result=mod.collect(expected,reader=mod.Reader(tree[0],clock=FixtureClock()))
    return result,max(observed,key=lambda v:v['wire_bytes'])


def test_cause_reproduced_with_many_unrelated_udp_owners_and_full_pipeline(tmp_path,tree):
    stress(tree)
    old,accounting=old_measure(tree)
    assert accounting['wire_bytes']>128*1024  # historical executed cap
    assert accounting['pre_fallback_reasons']==[]
    assert 'OUTPUT_BUDGET_DATA_INCOMPLETE' in old['reasons']
    row=collect(tree)
    assert row['snapshot_state']=='REPEATED_READS_AGREE',row['reasons']
    assert row['table_scope_before']['total_udp_rows']==102
    assert len(row['tables_before'])==1
    assert {v['process']['pid'] for v in row['owners_after']}=={200}
    data,summary,report=pipeline(tmp_path,tree,row)
    assert len(data)<=s.MAX_BYTES
    assert report['series_state']=='REPEATED_ENDPOINT_PROCESS_CANDIDATE_ONLY'
    assert report['source_association_verified'] is False


def test_unknown_process_owner_is_never_excluded_by_name(tmp_path,tree):
    root,_=tree;process(root,999,123,'unrelated-binary',b'unrelated-binary\0')
    (root/'999/fd/27').symlink_to('socket:[42]')
    row=collect(tree)
    data,summary,report=pipeline(tmp_path,tree,row)
    assert report['rows'][0]['link_state']=='SHARED_OWNERS_AMBIGUOUS'
    assert {o['process']['pid'] for o in row['owners_after']}=={200,999}


@pytest.mark.parametrize('failure',['process_gone','fd_gone','permission','budget'])
def test_incomplete_global_owner_search_cannot_claim_unique(tmp_path,tree,monkeypatch,failure):
    root,_=tree;stress(tree,background=15,unrelated_sockets=20)
    original=s.os.readlink
    if failure=='budget':monkeypatch.setattr(s,'MAX_READS',80)
    elif failure=='process_gone':(root/'400/stat').unlink()
    else:
        def link(path):
            if str(path).endswith('/400/fd/0'):
                raise FileNotFoundError(2,'gone') if failure=='fd_gone' else PermissionError(13,'denied')
            return original(path)
        monkeypatch.setattr(s.os,'readlink',link)
    row=collect(tree);data,summary,report=pipeline(tmp_path,tree,row)
    assert row['snapshot_state']=='INCOMPLETE' and report['series_state']=='UNCERTAIN_OR_INCOMPLETE'
    if failure!='budget':assert row['search_failure']['class'] in {'PROC_ENTRY_DISAPPEARED','PERMISSION_DENIED'}


def test_volume_fallback_preserves_prior_reason_and_size_counts(tree,monkeypatch):
    stress(tree);monkeypatch.setattr(s,'MAX_READS',100);monkeypatch.setattr(s,'MAX_BYTES',4096)
    row=collect(tree)
    assert 'READ_OR_WALL_BUDGET' in row['reasons'] and 'OUTPUT_BUDGET_DATA_INCOMPLETE' in row['reasons']
    assert row['size_diagnostics']['before_fallback_wire_bytes']>4096
    assert len(json.dumps(s.pack_inventory(row),separators=(',',':')).encode())+1<=4096
    assert s.match_peer(row,writer(),'trial')['link_state']=='UNKNOWN'


def test_scope_must_include_validated_writer_peer(tree):
    row=collect(tree);w=writer();w['transport_peer']['port']=1
    assert s.match_peer(row,w,'trial')['link_state']=='UNKNOWN'


def test_abundant_background_and_many_foreign_fds_keep_bounded_complete_search(tmp_path,tree):
    stress(tree,background=40,unrelated_sockets=100,unrelated_fds=5)
    row=collect(tree)
    assert row['snapshot_state']=='REPEATED_READS_AGREE',row['reasons']
    assert row['size_diagnostics']['search_counts']['visible_pids']==43
    assert row['size_diagnostics']['search_counts']['fd_entries_listed']>=600
    data,summary,report=pipeline(tmp_path,tree,row)
    assert len(data)<=s.MAX_BYTES and report['series_state']=='REPEATED_ENDPOINT_PROCESS_CANDIDATE_ONLY'


def test_background_beyond_read_limit_is_reported_not_silently_skipped(tmp_path,tree,monkeypatch):
    monkeypatch.setattr(s,'MAX_READS',1024)  # historical exhaustion remains tested
    stress(tree,background=60,unrelated_sockets=100,unrelated_fds=6)
    row=collect(tree)
    assert row['snapshot_state']=='INCOMPLETE' and 'READ_OR_WALL_BUDGET' in row['reasons']
    _,_,report=pipeline(tmp_path,tree,row)
    assert report['series_state']=='UNCERTAIN_OR_INCOMPLETE'


def test_monitor_waits_for_native_peer_without_scanning_proc(tmp_path):
    (tmp_path/'capture').mkdir()
    def forbidden(*args,**kwargs):raise AssertionError('No native peer: no proc query')
    rec=SocketRecorder(tmp_path,{'lifecycle_id':'x','manifest':{'engine_id':'e','container_id':'c','image_id':'i'}},runner=forbidden)
    p={'pid':1,'start_ticks':1,'boot_id':'b','executable':'/usr/bin/micro_ros_agent','native_byte_order':'little'}
    rec.sample(p,p,0)
    assert rec.summary()['state']=='WAITING_NATIVE_PEER' and rec.count==0


@pytest.mark.parametrize('address',['00000000000000000000000000000000','0000000000000000FFFF00000100007F'])
def test_possible_ipv6_dual_stack_owner_prevents_false_ipv4_uniqueness(tmp_path,tree,address):
    root,_=tree
    put(root,'self/net/udp6',HEADER+udp(99,address,35242).replace(' 00000000:0000 ',' 00000000000000000000000000000000:0000 '))
    (root/'100/fd/15').symlink_to('socket:[99]')
    row=collect(tree);_,_,report=pipeline(tmp_path,tree,row)
    assert len(row['tables_after'])==2
    assert report['rows'][0]['link_state']=='MULTIPLE_SOCKETS_AMBIGUOUS'
    assert {o['process']['pid'] for socket in row['associations'] for o in socket['owners']}=={100,200}


@pytest.mark.parametrize('placement',['within','after','missing'])
def test_status_reception_outside_sampled_time_span_cannot_be_credited(tree,placement):
    from datetime import datetime
    row=collect(tree);data=(json.dumps(s.pack_inventory(row))+'\n').encode()
    begin=int(datetime.fromisoformat(row['reads'][0]['at_utc']).timestamp()*1_000_000_000)
    values=[begin] if placement=='within' else [begin+1_000_000_000] if placement=='after' else []
    result=s.analyze_series(data,{'snapshots':1},writer(),'trial',receipt_wall_ns=values)
    if placement=='within':assert result['reception_coverage']['state']=='WITHIN_SAMPLED_SPAN_NOT_ATOMIC'
    else:assert result['series_state']=='UNCERTAIN_OR_INCOMPLETE' and result['errors']


def evidence_8076_tree(tmp_path, *, reduced=False):
    """First-sweep PID/FD topology from evidence; unknown values filled explicitly.

    Second sweep is a SYNTHETIC stable repetition, NOT recovered historical data.
    Reduced=True is a separate synthetic lower-load case, not the observed tree.
    """
    import copy
    fixture=json.loads((Path(__file__).parent/'fixtures/rover_socket_8076_topology.json').read_bytes())
    ctx=copy.deepcopy(fixture['context']);root=tmp_path/'proc';root.mkdir()
    put(root,'sys/kernel/random/boot_id',ctx['anchor_process']['boot_id'])
    (root/'self/ns').mkdir(parents=True)
    owner=fixture['owner'];net=owner['process']['net_namespace'];pns=owner['process']['pid_namespace']
    (root/'self/ns/net').symlink_to(net);(root/'self/ns/pid').symlink_to(pns)
    known={ctx['anchor_process']['pid']:ctx['anchor_process']['start_ticks'],
           ctx['agent_process']['pid']:ctx['agent_process']['start_ticks'],
           owner['process']['pid']:owner['process']['start_ticks']}
    for item in fixture['processes']:
        pid=item['pid'];process(root,pid,known.get(pid,pid*10),'python3',b'python3\0')
        for name,target in [('ns/net',net),('ns/pid',pns)]:
            (root/str(pid)/name).unlink();(root/str(pid)/name).symlink_to(target)
        fds=item['fds'][::2] if reduced else item['fds']
        if pid==owner['process']['pid'] and owner['fd'] not in fds:fds=[*fds,owner['fd']]
        for fd in fds:
            relevant=pid==owner['process']['pid'] and fd==owner['fd']
            (root/f'{pid}/fd/{fd}').symlink_to('socket:['+owner['inode']+']' if relevant else '/dev/null')
    for pid,exe in [(ctx['agent_process']['pid'],ctx['agent_executable']),
                    (owner['process']['pid'],owner['process']['executable'])]:
        (root/f'{pid}/exe').unlink();(root/f'{pid}/exe').symlink_to(exe)
    args=['ardurover']+[v for pair in owner['argv']['permitted_arguments'] for v in pair]
    put(root,str(owner['process']['pid'])+'/cmdline',('\0'.join(args)+'\0').encode())
    socket=fixture['socket'];selected=udp(int(socket['inode']),port=ctx['peers'][0]['port']).replace('00000000:0000',socket['remote']['proc_encoding']).replace(' 07 ',' '+socket['kernel_state_hex']+' ')
    put(root,'self/net/udp',HEADER+selected+''.join(udp(300000+n,port=40000+n) for n in range(29)))
    put(root,'self/net/udp6',HEADER.replace('rem_address','remote_address'))
    return (root,ctx),fixture


def writer_8076(ctx):
    value=writer();value.update(pid=ctx['agent_process']['pid'],process_start_ticks=str(ctx['agent_process']['start_ticks']),
                              boot_id=ctx['agent_process']['boot_id'])
    value['transport_peer']['port']=int.from_bytes(ctx['peers'][0]['port'].to_bytes(2,'big'),'little')
    return value


def frozen_8076_reader():
    import types,hashlib
    source=Path(__file__).resolve().parents[1]/'simulation/ros2_gazebo/results/rover_xrce_trial_2026_10_24/b9ee5ec5-049d-47cc-b22f-26535b972b5f/offline_correction_sources/tools/rover_xrce_trace/socket_inventory.py'
    data=source.read_bytes()
    assert hashlib.sha256(data).hexdigest()=='eb8b70d6cefe766a492f6cb2ebfb36b14bc1b48e0692f28e2da06c9771367493'
    recorded=source.parents[4]/'8076e735-81bb-4542-afda-8db2fe54acef'/'source_hashes.json'
    # Exact retained correction bytes, bound to the hash actually used in 8076.
    assert any(Path(v['path']).name=='socket_inventory.py' and v['sha256']==hashlib.sha256(data).hexdigest() for v in json.loads(recorded.read_bytes()))
    module=types.ModuleType('old_8076_fake_proc_only');module.__package__='tools.rover_xrce_trace'
    exec(compile(data,str(source),'exec'),module.__dict__)
    return module


def test_real_first_sweep_reconstruction_now_fits_reviewed_budget(tmp_path):
    tree,fixture=evidence_8076_tree(tmp_path)
    old=frozen_8076_reader();before=old.collect(tree[1],reader=old.Reader(tree[0],clock=FixtureClock()))
    after=collect(tree)
    assert len(fixture['processes'])==24 and sum(len(p['fds']) for p in fixture['processes'])==497
    assert before['snapshot_state']=='INCOMPLETE' and len(before['reads'])==1024
    assert before['reasons']==['READ_OR_WALL_BUDGET']
    assert after['snapshot_state']=='REPEATED_READS_AGREE' and len(after['reads'])==1182
    assert s.MAX_READS==2048 and after['reasons']==[]
    before_lists=[v['id'] for v in before['reads'] if v['source']=='/proc/.']
    after_lists=[v['id'] for v in after['reads'] if v['source']=='/proc/.']
    assert before_lists==[13,592] and after_lists==[13,591]
    assert after['owners_before'][0]['process']['pid']==fixture['owner']['process']['pid']
    data,_,report=pipeline(tmp_path/'wire',tree,after,writer_8076(tree[1]))
    assert len(data)<=s.MAX_BYTES and report['series_state']=='REPEATED_ENDPOINT_PROCESS_CANDIDATE_ONLY'
    assert not report['source_association_verified']


def test_one_stat_per_owner_per_sweep_saved_without_fabricated_provenance(tmp_path):
    tree,_=evidence_8076_tree(tmp_path,reduced=True)
    old=frozen_8076_reader();before=old.collect(tree[1],reader=old.Reader(tree[0],clock=FixtureClock()))
    after=collect(tree)
    assert before['snapshot_state']==after['snapshot_state']=='REPEATED_READS_AGREE'
    assert len(before['reads'])-len(after['reads'])==2
    assert before['associations'][0]['owners'][0]['process']==after['associations'][0]['owners'][0]['process']
    owner=after['owners_before'][0]
    assert len(owner['source_reads'])==len(set(owner['source_reads']))
    stat_refs=[v for v in owner['source_reads'] if after['reads'][v]['source']==f"/proc/{owner['process']['pid']}/stat"]
    assert len(stat_refs)==3  # before FD, reused post-FD, final after argv; all real reads
    assert all(0<=v<len(after['reads']) for v in owner['source_reads'])
    _,_,report=pipeline(tmp_path/'wire',tree,after,writer_8076(tree[1]))
    assert report['series_state']=='REPEATED_ENDPOINT_PROCESS_CANDIDATE_ONLY'
    assert not report['movement_authorized'] and not report['source_association_verified']


@pytest.mark.parametrize('change',['late_owner','pid_after_reused_stat','fd_during_close','agent_during_close'])
def test_reconstruction_changes_and_shutdown_never_credit_partial_association(tmp_path,change):
    tree,fixture=evidence_8076_tree(tmp_path,reduced=True);root,ctx=tree
    target=fixture['owner']['process']['pid'];other=fixture['processes'][0]['pid']
    class Changing(s.Reader):
        listings=0;stats=0
        def get(self,relative,operation='bytes',limit=65536):
            value=super().get(relative,operation,limit)
            if relative=='.':
                self.listings+=1
                if self.listings==2:
                    if change=='late_owner':(root/f'{other}/fd/999').symlink_to('socket:['+fixture['owner']['inode']+']')
                    if change=='fd_during_close':(root/f'{target}/fd/{fixture["owner"]["fd"]}').unlink()
                    if change=='agent_during_close':(root/f'{ctx["agent_process"]["pid"]}/stat').unlink()
            if relative==f'{target}/stat':
                self.stats+=1
                if change=='pid_after_reused_stat' and self.stats==2:put(root,f'{target}/stat',stat(target,999))
            return value
    row=collect(tree,Changing(root,clock=FixtureClock()))
    assert row['snapshot_state']=='INCOMPLETE' and row['reasons']
    _,_,report=pipeline(tmp_path/'wire',tree,row,writer_8076(ctx))
    assert report['series_state']=='UNCERTAIN_OR_INCOMPLETE'
    if change=='late_owner':assert len(row['owners_after'])==2


def test_8076_topology_fixture_is_bound_to_retained_events_not_only_counts():
    import hashlib,re
    project=Path(__file__).resolve().parents[1]
    fixture=json.loads((Path(__file__).parent/'fixtures/rover_socket_8076_topology.json').read_bytes())
    source=project/fixture['source_socket_journal'];raw=source.read_bytes()
    assert hashlib.sha256(raw).hexdigest()==fixture['source_socket_sha256']
    trial=project/'simulation/ros2_gazebo/results/rover_xrce_trial_2026_10_24/8076e735-81bb-4542-afda-8db2fe54acef'
    assert hashlib.sha256((trial/'manifest.json').read_bytes()).hexdigest()==fixture['source_manifest_sha256']
    row=s.unpack_inventory(json.loads(raw.splitlines()[0]));topology={}
    for event in row['reads'][13:592]:
        m=re.fullmatch(r'/proc/(\d+)/fd',event['source'])
        if m and event['operation']=='list':topology[int(m[1])]=[]
        m=re.fullmatch(r'/proc/(\d+)/fd/(\d+)',event['source'])
        if m and event['operation']=='link':topology[int(m[1])].append(int(m[2]))
    assert fixture['processes']==[{'pid':pid,'fds':sorted(fds)} for pid,fds in topology.items()]
    assert fixture['owner']==row['owners_before'][0] and fixture['socket']==row['tables_before'][0]


@pytest.mark.parametrize('reads,kib', [(1024,128),(1280,160),(2048,256)])
@pytest.mark.parametrize('case', ['background','shared','changed','gone','permission','missing_context','bytes','time'])
def test_offline_budget_candidates_full_pipeline(tmp_path,tree,monkeypatch,reads,kib,case):
    """Synthetic stress only. Overrides expire with test; no runtime selector added.

    Stable 8076 replay is deliberately NOT repeated: its measurements are frozen.
    """
    monkeypatch.setattr(s,'MAX_READS',reads)
    monkeypatch.setattr(s,'MAX_BYTES',kib*1024)
    monkeypatch.setattr(SocketRecorder,'MAX_ROW',kib*1024)
    stress(tree,background=60,unrelated_sockets=100,unrelated_fds=6)
    root,_=tree
    if case=='shared':(root/'400/fd/99').symlink_to('socket:[42]')
    if case=='gone':(root/'400/stat').unlink()
    if case=='permission':
        original=s.os.readlink
        def denied(path):
            if str(path).endswith('/400/fd/0'):raise PermissionError(13,'synthetic denial')
            return original(path)
        monkeypatch.setattr(s.os,'readlink',denied)
    class Changing(s.Reader):
        hits=0
        def get(self,relative,operation='bytes',limit=65536):
            value=super().get(relative,operation,limit)
            if relative=='200/stat':
                self.hits+=1
                if self.hits==2:put(root,'200/stat',stat(200,999))
            return value
    if case=='bytes':monkeypatch.setattr(s,'MAX_BYTES',4096)
    if case=='time':
        class Expired:
            n=0
            def __call__(self):self.n+=1;return float(self.n)
        reader=s.Reader(root,clock=Expired())
    else:reader=(Changing if case=='changed' else s.Reader)(root,clock=FixtureClock())
    row=collect(tree,reader=reader)
    if case=='missing_context':
        # Missing provenance reference must survive persistence as a rejection.
        row['context_after']=None
    data,summary,report=pipeline(tmp_path,tree,row)
    unique=report['series_state']=='REPEATED_ENDPOINT_PROCESS_CANDIDATE_ONLY'
    assert report['status']=='BLOCKED' and report['movement_authorized'] is False
    if case!='background':assert not unique
    print('OFFLINE_BUDGET',json.dumps({'reads_cap':reads,'kib':kib,'case':case,
          'reads':len(row['reads']),'bytes':len(data),'snapshot':row['snapshot_state'],
          'series':report['series_state'],'reasons':row['reasons']}))


def test_offline_candidate_aggregate_arithmetic():
    """Proposal feasibility, NOT a production budget override or admission gate."""
    aggregate=8*1024*1024
    # MAX_ROW already includes newline in the monitor's persisted byte limit.
    for kib,maximum in [(128,64),(160,51),(256,32)]:
        row=kib*1024
        assert aggregate//row==maximum
        assert maximum*row<=aggregate<(maximum+1)*row
    # Existing capture_window reserves 140 s outer capture plus 60 s stop.
    # A 32-row schedule at 5s cannot conservatively cover both, even at outset.
    assert 32*5 < 140+60 < 51*5


@pytest.mark.parametrize('overflow',['rows','bytes'])
def test_current_series_budget_rejects_overflow_from_file(tmp_path,tree,overflow):
    """Current bounded reader; persisted row/count/byte excess must fail closed."""
    assert s.MAX_BYTES==256*1024 and SocketRecorder.LIMIT==64
    row=collect(tree)
    line=json.dumps(s.pack_inventory(row),separators=(',',':')).encode()+b'\n'
    data=line*65 if overflow=='rows' else b' '*(64*(s.MAX_BYTES+1))+b'\n'
    path=tmp_path/'over_budget.jsonl';path.write_bytes(data)
    report=s.analyze_series(path,{'snapshots':65 if overflow=='rows' else 1},writer(),'trial')
    assert report['series_state']=='UNCERTAIN_OR_INCOMPLETE'
    assert report['movement_authorized'] is False


def test_reviewed_contract_single_source_and_validation():
    from dataclasses import replace
    from tools.rover_xrce_trace.budget import SOCKET
    assert (s.MAX_READS,s.MAX_BYTES,SocketRecorder.MAX_ROW,SocketRecorder.LIMIT)==(2048,262144,262144,64)
    assert SOCKET.journal_bytes==16*1024*1024
    for changes in ({'reads':True},{'row_bytes':0},{'observations':65},
                    {'journal_bytes':8*1024*1024},{'query_timeout_s':5.},{'query_timeout_s':1.},
                    {'monitor_s':601.},{'interval_s':6.},
                    {'cooperative_s':float('nan')}):
        with pytest.raises(ValueError):replace(SOCKET,**changes)


def test_monitor_enforces_aggregate_before_append(tmp_path):
    from tools.rover_xrce_trace.budget import SOCKET
    value={'lifecycle_id':'trial','manifest':{'engine_id':'e','container_id':'c','image_id':'i'}}
    calls=[]
    def runner(args,**kw):
        calls.append(1)
        return SimpleNamespace(returncode=0,stdout=json.dumps({'schema':'tfg.xrce-sockets/1',
            'status':'BLOCKED','movement_authorized':False,'source_association_verified':False,
            'context_declared_by_protected_monitor':json.loads(kw['input']),
            'snapshot_state':'REPEATED_READS_AGREE'}).encode())
    identity={'pid':1,'start_ticks':1,'boot_id':'b','executable':'/usr/bin/micro_ros_agent','native_byte_order':'little'}
    write_trace(tmp_path,identity)
    rec=SocketRecorder(tmp_path,value,runner=runner)
    rec.output=(tmp_path/'capture/sockets.jsonl').open('xb')
    rec.output.truncate(SOCKET.journal_bytes-1)
    rec.output.seek(0,2);rec.bytes_written=SOCKET.journal_bytes-1
    rec.sample(identity,identity,0);rec.sample(identity,identity,5);rec.close()
    assert len(calls)==1 and rec.failed and rec.count==0
    assert (tmp_path/'capture/sockets.jsonl').stat().st_size==SOCKET.journal_bytes-1
    report=s.analyze_series(tmp_path/'capture/sockets.jsonl',rec.summary(),writer(),'trial')
    assert report['series_state']=='UNCERTAIN_OR_INCOMPLETE'


def test_bounded_reader_rejects_large_sparse_file_before_read(tmp_path,monkeypatch):
    from tools.rover_xrce_trace.budget import SOCKET
    path=tmp_path/'huge.jsonl'
    with path.open('wb') as f:f.truncate(SOCKET.journal_bytes+1)
    from tools.rover_xrce_trace import budget
    monkeypatch.setattr(budget.os,'fdopen',lambda *a,**kw:pytest.fail('oversized file opened before fstat rejection'))
    report=s.analyze_series(path,{'snapshots':1},writer(),'trial')
    assert report['errors'] and report['series_state']=='UNCERTAIN_OR_INCOMPLETE'


def test_path_reader_accepts_framed_roundtrip_and_rejects_truncation(tmp_path,tree):
    row=collect(tree);path=tmp_path/'journal.jsonl'
    data=json.dumps(s.pack_inventory(row),separators=(',',':')).encode()+b'\n';path.write_bytes(data)
    assert s.analyze_series(path,{'snapshots':1},writer(),'trial')['series_state']=='REPEATED_ENDPOINT_PROCESS_CANDIDATE_ONLY'
    path.write_bytes(data[:-1])
    assert s.analyze_series(path,{'snapshots':1},writer(),'trial')['errors']


def test_reader_rejects_oversized_row_even_below_journal_limit(tmp_path):
    from tools.rover_xrce_trace.budget import SOCKET
    path=tmp_path/'row.jsonl';path.write_bytes(b' ' * SOCKET.row_bytes+b'\n')
    assert s.analyze_series(path,{'snapshots':1},writer(),'trial')['errors']


def test_framing_counts_utf8_and_newline_exactly():
    from tools.rover_xrce_trace.budget import SOCKET, encode_row
    # JSON quotes are two bytes and newline one byte. Boundary MUST count all 3.
    data=encode_row('x'*(SOCKET.row_bytes-3))
    assert len(data)==SOCKET.row_bytes and data.endswith(b'\n')
    with pytest.raises(ValueError):encode_row('x'*(SOCKET.row_bytes-2))


def test_budget_header_mismatch_cannot_reuse_series(tree):
    row=collect(tree);data=json.dumps(s.pack_inventory(row)).encode()+b'\n'
    report=s.analyze_series(data,{'snapshots':1,'budget':{'row_bytes':128*1024}},writer(),'trial')
    assert report['series_state']=='UNCERTAIN_OR_INCOMPLETE' and report['errors']


@pytest.mark.parametrize('closing_offset',[-1,1])
def test_closure_receipt_is_not_coverage_proof(tree,closing_offset):
    row=collect(tree);data=json.dumps(s.pack_inventory(row)).encode()+b'\n'
    report=s.analyze_series(data,{'snapshots':1,'closed_wall_ns':1700000000000000000+closing_offset},writer(),'trial')
    # The socket-only API cannot certify lifecycle closure, on either side of its
    # final observation. Preserve the separate monitor/lifecycle receipt.
    assert report['covers_entire_monitor_interval'] is False
    assert report['movement_authorized'] is False


def test_persisted_byte_counter_contradiction_rejected(tree):
    row=collect(tree);data=json.dumps(s.pack_inventory(row)).encode()+b'\n'
    assert s.analyze_series(data,{'snapshots':1,'journal_bytes_written':len(data)-1},writer(),'trial')['errors']


def test_zero_match_retains_bounded_endpoint_diagnostics_without_association(tree):
    expected=tree[1] if isinstance(tree,tuple) else None
    # Same table read path as the monitor. No widened/swapped-port matching.
    root=tree[0] if isinstance(tree,tuple) else tree
    reader=s.Reader(root,clock=FixtureClock())
    selected,refs,scope=s._tables(reader,[{'family':'IPv4','address':'127.0.0.1','port':54321}])
    assert selected==[] and scope['relevant_rows']==0
    assert scope['unmatched_local_endpoints'] and refs
    assert len(scope['unmatched_local_endpoints'])<=32


def test_zero_match_diagnostic_survives_monitor_file_reader_pipeline(tmp_path,tree):
    root,context=tree
    context['peers'][0]['port']=54321
    row=collect(tree);w=writer();w['transport_peer']['port']=int.from_bytes((54321).to_bytes(2,'big'),'little')
    data,summary,report=pipeline(tmp_path,tree,row,expected_writer=w)
    decoded=s.unpack_inventory(json.loads(data))
    assert decoded['table_scope_before']['unmatched_local_endpoints']
    assert report['rows'][0]['link_state']=='NOT_OBSERVED_NOT_ABSENCE_PROOF'
    assert report['series_state']=='UNCERTAIN_OR_INCOMPLETE' and not report['source_association_verified']
