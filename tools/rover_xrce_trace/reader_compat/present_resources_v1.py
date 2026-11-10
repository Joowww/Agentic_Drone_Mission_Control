"""Bounded pre-session resource reads. No binds, signals, ROS or native peer claims."""
import hashlib
import json
import re
from pathlib import Path

from . import socket_inventory as s
from .budget import SOCKET

SCHEMA = 'tfg.present-resources/1'
WIRE_SCHEMA = 'tfg.present-resources/2'
# Fixed local endpoints of the reviewed two_drones_rover launch contract.
# Config bytes are verified in the exact SDK and bound into every review scope.
CONFIG_PATHS = {
    'top':'/root/ardu_ws/install/ardupilot_gz_bringup/share/ardupilot_gz_bringup/launch/tfg_demo.launch.py',
    'robot':'/root/ardu_ws/install/ardupilot_gz_bringup/share/ardupilot_gz_bringup/launch/robots/robot.launch.py',
    'iris':'/root/ardu_ws/install/ardupilot_gz_bringup/share/ardupilot_gz_bringup/launch/robots/iris.launch.py',
    'rover':'/root/ardu_ws/install/ardupilot_gz_bringup/share/ardupilot_gz_bringup/launch/robots/wildthumper.launch.py',
    'iris_sdf':'/root/ardu_ws/install/ardupilot_gazebo/share/ardupilot_gazebo/models/iris_with_gimbal/model.sdf',
    'rover_sdf':'/root/ardu_ws/install/ardupilot_sitl_models/share/ardupilot_sitl_models/models/wildthumper_with_lidar/model.sdf',
    'sitl':'/root/ardu_ws/install/ardupilot_sitl/local/lib/python3.10/dist-packages/ardupilot_sitl/launch.py',
}


# Reviewed installed configuration versions; reject drift instead of guessing.
CONFIG_HASHES = {'top': '69bf4c278295625841ab1bd1578f4cdde2fc4d1512c7eaaafe5a63e876070ba4',
 'robot': '7f7172b879db43ab72be70575d9469b1c5b29e5d905d1fb7846ba74c01d1d465',
 'iris': '1e9a177b021d05fb76e988ccfcf678758b696bca0be9ea1790739546508615de',
 'rover': 'ede33db7bd6217f42eaac0c44fcd1fd7dd0b8e201c2ed854e6ef6361c4c947f1',
 'sitl': '73bfae61370efaeef74ec50cd6d3f618aee7638d1c6592b019a04b40aa2ef31c',
 'iris_sdf': '16ce12d9cd931efd55a1bda7553835b78b4618b649406be0d5659307a40fc7e5',
 'rover_sdf': '16bf49cff0a128b9f378c8263b2628ff1490c84f31194d9ae8efb596a3d82c6a'}


def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()


def read_config():
    result={}
    for key,path in CONFIG_PATHS.items():
        with Path(path).open('rb') as stream:data=stream.read(SOCKET.row_bytes+1)
        if len(data)>SOCKET.row_bytes:raise ValueError('Resource config file budget: '+key)
        result[key]=data.decode('utf-8')
    return result


def scope(host_launch, config):
    """Reviewed effective source contract; never executes launch code or invents peers."""
    if set(config)!=set(CONFIG_PATHS):raise ValueError('Incomplete effective configuration')
    for key,text in config.items():
        if hashlib.sha256(text.encode()).hexdigest()!=CONFIG_HASHES[key]:
            raise ValueError('Effective resource configuration changed: '+key)
    if config['top']!=host_launch:raise ValueError('Host/installed launch resource scope differs')
    return expected_scope()


def _context(reader):
    boot,_=reader.get('sys/kernel/random/boot_id',limit=128)
    net,_=reader.get('self/ns/net','link');pid,_=reader.get('self/ns/pid','link')
    clock,_=reader.get('self/ns/time','link')
    stat,_=reader.get('self/stat',limit=4096)
    anchor,_=s._identity(reader,stat.decode().split(' ',1)[0])
    if anchor['net_namespace']!=net or anchor['pid_namespace']!=pid:raise s.Incomplete('RESOURCE_ANCHOR_NAMESPACE_MISMATCH')
    return {'boot_id':boot.decode().strip(),'net_namespace':net,'pid_namespace':pid,
            'time_namespace':clock,'anchor':anchor}


def _tcp(data,family):
    if not data.endswith(b'\n'):raise ValueError('Truncated proc TCP table framing')
    lines=data.decode('ascii').splitlines()
    if not lines or not all(w in lines[0] for w in ('local_address','inode')) or not any(w in lines[0] for w in ('rem_address','remote_address')):raise ValueError('Missing TCP header')
    rows=[]
    for line in lines[1:]:
        f=line.split()
        if len(f)<10 or not f[9].isdigit() or not re.fullmatch('[0-9A-Fa-f]{2}',f[3]):raise ValueError('Malformed TCP table')
        rows.append({'source':'/proc/self/net/'+family,'inode':f[9],
            'local':s.endpoint(f[1],'udp6' if family=='tcp6' else 'udp'),
            'remote':s.endpoint(f[2],'udp6' if family=='tcp6' else 'udp'),'kernel_state_hex':f[3]})
    return rows


def pack(value):
    """Reuse the socket reader's lossless, row-local reference encoding."""
    record=dict(value)
    record['associations']=[{**row,'association_state':row['ownership']} for row in record.pop('occupied')]
    record.update(tables_before=[],tables_after=[])
    wire=s.pack_inventory(record)
    return {**wire['record'],'schema':WIRE_SCHEMA,
            'encoding':{k:v for k,v in wire.items() if k not in {'schema','record'}}}


def unpack(value):
    if value.get('schema')!=WIRE_SCHEMA:return value
    metadata={k:v for k,v in value.items() if k!='encoding'}
    metadata['schema']=SCHEMA
    record=s.unpack_inventory({'schema':'tfg.xrce-sockets/2','record':metadata,**value['encoding']})
    if record.pop('tables_before') or record.pop('tables_after'):raise ValueError('Unexpected resource tables')
    record['occupied']=[]
    for row in record.pop('associations'):
        row=dict(row)
        if row.pop('association_state')!=row['ownership']:raise ValueError('Contradictory resource ownership')
        record['occupied'].append(row)
    if record.get('schema')!=SCHEMA or pack(record)!=value:raise ValueError('Noncanonical resource encoding')
    return record


def collect(resource_scope, *, reader=None, known_processes=()):
    """Same .25 s / 2048 reads / 128 PIDs / 2048 FDs / 256 KiB output bounds.

    Tables read to EOF twice, same namespace; relevant inode owners swept twice.
    Any occupied endpoint rejects, including known/shared/foreign/unknown owners.
    """
    reader=reader or s.Reader();started=reader.clock()
    value={'schema':SCHEMA,'scope':resource_scope,'scope_sha256':digest(resource_scope),
           'status':'INCOMPLETE','reasons':[],'started_monotonic':started,'occupied':[],
           'budget':SOCKET.record(),'max_pids':s.MAX_PIDS,'max_fds':s.MAX_FDS}
    try:
        context=_context(reader);value['context']=context
        def tables():
            all_rows=[];ids=[]
            for name in ('udp','udp6','tcp','tcp6'):
                data,rid=reader.get('self/net/'+name);ids.append(rid)
                rows=s.table(data,name) if name.startswith('udp') else _tcp(data,name)
                protocol='udp' if name.startswith('udp') else 'tcp'
                for row in rows:row['protocol']=protocol
                all_rows.extend(rows)
            relevant=[r for r in all_rows if any(e['protocol']==r['protocol'] and e['port']==r['local']['port'] for e in resource_scope['endpoints'])]
            return sorted(relevant,key=lambda r:(r['protocol'],r['local']['family'],r['inode'])),ids,digest(all_rows)
        before,ids1,hash1=tables()
        value['occupied']=[{**r,'ownership':'UNKNOWN','owners':[]} for r in before]
        inodes={r['inode'] for r in before if r['inode']!='0'}
        owners1,pids1=s._owners(reader,inodes,context,[])
        owners2,pids2=s._owners(reader,inodes,context,[])
        after,ids2,hash2=tables()
        if before!=after or pids1!=pids2 or sorted(map(s._owner_key,owners1))!=sorted(map(s._owner_key,owners2)) or _context(reader)!=context:
            raise s.Incomplete('RESOURCE_PROCESS_OR_NAMESPACE_CHANGED')
        if any(reader.reads[n].get('operation')!='bytes_to_eof' for n in ids1+ids2):raise s.Incomplete('TABLE_EOF_UNVERIFIED')
        value.update(table_reads=ids1+ids2,table_hashes=[hash1,hash2],owners_before=owners1,owners_after=owners2)
        value['occupied']=[]
        for row in after:
            owners=[o for o in owners2 if o['inode']==row['inode']]
            unique={json.dumps(o['process'],sort_keys=True) for o in owners}
            state=('UNKNOWN' if not owners else 'SHARED' if len(unique)>1 else
                   'FOREIGN_NAMESPACE' if any(o['process']['net_namespace']!=context['net_namespace'] or o['process']['pid_namespace']!=context['pid_namespace'] for o in owners) else
                   'KNOWN' if all((o['process']['pid'],o['process']['start_ticks']) in known_processes for o in owners) else 'FOREIGN')
            value['occupied'].append({**row,'owners':owners,'ownership':state,
                'possible_dual_stack':row['local']['family']=='IPv6' and (row['local']['wildcard'] or 'ffff:' in row['local']['address'])})
        for row in value['occupied']:
            group={json.dumps(o['process'],sort_keys=True) for other in value['occupied']
                   if other['protocol']==row['protocol'] and other['local']['port']==row['local']['port'] for o in other['owners']}
            row['endpoint_owner_count']=len(group)
            if len(group)>1:row['ownership']='SHARED'
        value['status']='OCCUPIED' if after else 'FREE'
        if after:value['reasons'].append('RELEVANT_LOCAL_ENDPOINT_OCCUPIED')
    except (s.Incomplete,OSError,ValueError,KeyError,TypeError) as exc:
        value['reasons'].append(str(exc));value['status']='INCOMPLETE'
    value.update(finished_monotonic=reader.clock(),reads=reader.reads,counts=reader.counts)
    if len(json.dumps(value).encode())>s.MAX_BYTES:
        if {'owners_before','owners_after'}<=value.keys():
            wire=pack(value)
            if len(json.dumps(wire).encode())<=s.MAX_BYTES:return wire
        value.update(status='INCOMPLETE',reasons=['RESOURCE_OUTPUT_BUDGET'],reads=[],owners_before=[],owners_after=[],
            occupied=[{k:r[k] for k in ('protocol','inode','local') if k in r} for r in value['occupied'][:32]],occupied_truncated=True)
    return value



def expected_scope():
    # Construct the same reviewed contract without reading SDK files in the host.
    # Actual bytes are checked by scope() in the exact SDK on every observation.
    from tools.simulation_profiles import get_profile
    p=get_profile('two_drones_rover')
    if p.sitl_ports_awaited_before_start!=(5760,5770,5780) or [v.robot_name for v in p.vehicles]!=['drone1','drone2','rover1']:
        raise ValueError('Profile differs from reviewed effective endpoint derivation')
    endpoints=[{'protocol':'udp','port':2019,'role':'single micro_ros_agent udp4'}]
    for i,v in enumerate(p.vehicles):
        endpoints.extend([{'protocol':'tcp','port':p.sitl_ports_awaited_before_start[i],'role':v.robot_name+' SITL primary'},
            {'protocol':'udp','port':5501+10*i,'role':v.robot_name+' declared RC input'},
            {'protocol':'udp','port':9002+10*i,'role':v.robot_name+' FDM plugin input'}])
    return {'schema':'tfg.present-resource-scope/1','profile':p.name,'endpoints':endpoints,
            'address_policy':'ALL_LOCAL_ADDRESSES_BOTH_FAMILIES_CONSERVATIVE',
            'config_hashes':{CONFIG_PATHS[k]:v for k,v in CONFIG_HASHES.items()},'host_launch_sha256':CONFIG_HASHES['top'],
            'profile_sha256':digest({'ports':p.sitl_ports_awaited_before_start,'vehicles':[v.__dict__ for v in p.vehicles]}),
            'not_covered':'Remote-only MAVLink destinations, ephemeral DDS/Gazebo/JSON source ports; runtime bind/liveness checks remain mandatory'}


def acquisition_decision(value):
    """Exact rejection facts from this observation, without discarding its bytes."""
    value=unpack(value)
    reasons=[]
    wanted={(e['protocol'],e['port']) for e in expected_scope()['endpoints']}
    got={(r['protocol'],r['local']['port']) for r in value.get('occupied',[])}
    listening={(r['protocol'],r['local']['port']) for r in value.get('occupied',[]) if r.get('kernel_state_hex')=='0A'}
    missing=sorted(wanted-got);not_listening=sorted({e for e in wanted if e[0]=='tcp'}-listening)
    unsafe=[{'protocol':r['protocol'],'port':r['local']['port'],'inode':r.get('inode'),
             'ownership':r.get('ownership','UNKNOWN')} for r in value.get('occupied',[]) if r.get('ownership')!='KNOWN']
    reads=value.get('reads',[]);ids=value.get('table_reads',[])
    expected_sources=['/proc/self/net/'+name for name in ('udp','udp6','tcp','tcp6')]*2
    eof=(len(ids)==8 and all(type(i) is int and 0<=i<len(reads) for i in ids)
         and len(set(ids))==8 and [reads[i].get('source') for i in ids]==expected_sources
         and all(row.get('state')=='OBSERVED' for row in reads)
         and all(reads[i].get('operation')=='bytes_to_eof' for i in ids))
    if value.get('status')!='OCCUPIED':reasons.extend(value.get('reasons') or ['RESOURCE_STATUS_'+str(value.get('status'))])
    if value.get('scope')!=expected_scope():reasons.append('RESOURCE_SCOPE_CHANGED')
    if not eof:reasons.append('TABLE_EOF_UNVERIFIED')
    if missing:reasons.append('REQUIRED_ENDPOINT_MISSING')
    if not_listening:reasons.append('REQUIRED_TCP_NOT_LISTENING')
    if got-wanted:reasons.append('UNEXPECTED_SCOPED_ENDPOINT')
    if unsafe:reasons.append('ENDPOINT_OWNER_NOT_UNIQUE_KNOWN')
    return {'accepted':not reasons,'reasons':reasons,'missing_endpoints':missing,
            'tcp_not_listening':not_listening,'unsafe_owners':unsafe,
            'coverage':{'table_eof':eof,'table_reads':ids,'status':value.get('status'),
                        'reader_reasons':value.get('reasons',[]),'counts':value.get('counts',{}),
                        'budget':value.get('budget')}}


def require_acquired(value):
    """Late bind race guard. Does not authorize movement or future availability."""
    decision=acquisition_decision(value)
    if not decision['accepted']:
        raise ValueError('Runtime endpoint acquisition rejected: '+', '.join(decision['reasons']))


