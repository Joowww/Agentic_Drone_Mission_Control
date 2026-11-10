"""Bounded passive /proc UDP metadata, for the existing diagnostic monitor only.

No ROS, Docker, socket syscalls, payloads, environment or services. No identity
accreditation. Repeated reads detect some races, never establish atomicity/ABA
immunity. Tests inject a temporary proc tree; collection never runs on import.
"""
import errno
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import re
import sys
import time
from datetime import datetime, timezone

try:
    from .budget import SOCKET, journal_rows, encode_row
except ImportError:
    from budget import SOCKET, journal_rows, encode_row

MAX_BYTES = SOCKET.row_bytes
MAX_READS = SOCKET.reads
MAX_PIDS = 128
MAX_FDS = 2048
BUDGET = SOCKET.cooperative_s


class Incomplete(Exception):
    pass


def endpoint(raw, family, byteorder=sys.byteorder):
    if family not in {'udp','udp6'} or byteorder not in {'little','big'}:
        raise ValueError('Unsupported proc endpoint encoding')
    address, port = raw.split(':')
    size = 8 if family == 'udp' else 32
    if not re.fullmatch('[0-9A-Fa-f]{'+str(size)+'}', address) or not re.fullmatch('[0-9A-Fa-f]{4}', port):
        raise ValueError('Invalid proc endpoint')
    packed = b''.join(int(address[n:n+8], 16).to_bytes(4, byteorder) for n in range(0, size, 8))
    ip = ipaddress.ip_address(packed)
    return {'family': 'IPv4' if family == 'udp' else 'IPv6', 'address': ip.compressed,
            'port': int(port, 16), 'wildcard': ip.is_unspecified, 'proc_encoding': raw}


def table(data, family):
    rows = []
    if not data.endswith(b'\n'):raise ValueError('Truncated proc UDP table framing')
    lines = data.decode('ascii').splitlines()
    if not lines or not all(word in lines[0] for word in ('local_address', 'inode')) or not any(word in lines[0] for word in ('rem_address', 'remote_address')):
        raise ValueError('Missing proc UDP header')
    for line in lines[1:]:
        fields = line.split()
        if len(fields) < 10 or not fields[9].isdigit() or int(fields[9]) <= 0:
            raise ValueError('Invalid proc UDP row/inode')
        local, remote = endpoint(fields[1], family), endpoint(fields[2], family)
        rows.append({'source': '/proc/self/net/'+family, 'inode': fields[9], 'local': local, 'remote': remote,
                     'kernel_state_hex': fields[3],
                     'remote_state': 'UNCONNECTED' if remote['wildcard'] and remote['port'] == 0 else 'SPECIFIED'})
    return rows


def argv_permitted(data):
    """Never record arbitrary argv values, bash bodies, credentials or defaults."""
    values = data.decode('utf-8', errors='replace').split('\0')
    answer = {'argv0_basename': Path(values[0]).name if values and Path(values[0]).name in {'ardurover','arducopter','micro_ros_agent','ros2','python3','python3.10','bash','gz','ruby'} else 'NOT_RECORDED', 'permitted_arguments': []}
    numeric = {'--instance', '--sysid', '--port', '--slave', '--speedup'}
    for i, value in enumerate(values[:-1]):
        if value in numeric and re.fullmatch('[0-9]{1,5}', values[i+1]):
            answer['permitted_arguments'].append([value, values[i+1]])
        elif value == '--model' and values[i+1] == 'json':
            answer['permitted_arguments'].append([value, 'json'])
        elif value == '--middleware' and values[i+1] == 'dds':
            answer['permitted_arguments'].append([value, 'dds'])
    answer['other_arguments'] = 'NOT_RECORDED'
    return answer


class Reader:
    def __init__(self, root=Path('/proc'), *, clock=time.monotonic):
        self.root, self.clock = Path(root), clock
        self.deadline = clock()+BUDGET
        self.reads = []
        self.counts = {"visible_pids":0,"fd_entries_listed":0,"fd_lists_completed":0,
                       "read_calls":0}

    def get(self, relative, operation='bytes', limit=65536):
        if self.clock() >= self.deadline or len(self.reads) >= MAX_READS or self.counts['read_calls']>=MAX_READS:
            raise Incomplete('READ_OR_WALL_BUDGET')
        event = {'id': len(self.reads), 'source': '/proc/'+relative, 'operation': operation,
                 'started_monotonic': self.clock(), 'at_utc': datetime.now(timezone.utc).isoformat()}
        self.reads.append(event)
        try:
            path = self.root/relative
            if operation == 'link':
                self.counts['read_calls']+=1
                value = os.readlink(path)
            elif operation == 'list':
                self.counts['read_calls']+=1
                with os.scandir(path) as entries:
                    value = []
                    for entry in entries:
                        if relative == f'{os.getpid()}/fd' and os.readlink(entry.path) == str(path):
                            # Our own live scandir FD would disappear when this
                            # iterator closes. It is a directory, not a socket.
                            # Do not hide any vanished/socket FD from other PIDs.
                            event.setdefault('ignored_query_directory_fds', []).append(entry.name)
                            continue
                        value.append(entry.name)
                        if len(value) > limit:
                            raise Incomplete('DIRECTORY_BUDGET')
            else:
                fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK)
                try:
                    # proc seq_file can return a short, line-complete page even
                    # when more rows exist. Only a zero read establishes EOF.
                    chunks=[];size=0
                    while True:
                        if self.clock()>=self.deadline or self.counts['read_calls']>=MAX_READS:
                            raise Incomplete('READ_OR_WALL_BUDGET_BEFORE_EOF')
                        self.counts['read_calls']+=1
                        chunk=os.read(fd,limit+1-size)
                        if not chunk:break
                        chunks.append(chunk);size+=len(chunk)
                        if size>limit:raise Incomplete('FILE_BUDGET')
                    value=b''.join(chunks);event['operation']='bytes_to_eof'
                finally: os.close(fd)
            if operation=='list':
                if relative=='.':self.counts['visible_pids']=sum(v.isdigit() for v in value)
                elif relative.endswith('/fd'):
                    self.counts['fd_entries_listed']+=len(value);self.counts['fd_lists_completed']+=1
            if self.clock() >= self.deadline:
                raise Incomplete('WALL_BUDGET')
            event['state'] = 'OBSERVED'
            return value, event['id']
        except OSError as exc:
            event['state'] = 'UNKNOWN'
            event['reason'] = errno.errorcode.get(exc.errno, 'OS_ERROR')
            raise Incomplete(event['reason']) from None
        except Incomplete as exc:
            event.update(state='UNKNOWN', reason=str(exc)); raise
        finally:
            event['finished_monotonic'] = self.clock()


def _identity(reader, pid, *, observed_start=None):
    if observed_start is None:
        stat, sid = reader.get(f'{pid}/stat', limit=4096)
        fields = stat.decode().rpartition(')')[2].split()
        if len(fields) < 20 or not fields[19].isdigit() or fields[0] == 'Z':
            raise Incomplete('PROCESS_INVALID_OR_ZOMBIE')
        ticks = int(fields[19])
    else:
        # Only the immediately preceding post-FD stat in THIS sweep is reused.
        # The final stat/identity after argv is still read, never cached.
        ticks, sid = observed_start
    exe, eid = reader.get(f'{pid}/exe', 'link')
    net, nid = reader.get(f'{pid}/ns/net', 'link')
    pns, npid = reader.get(f'{pid}/ns/pid', 'link')
    return {'pid': int(pid), 'start_ticks': ticks, 'executable': exe,
            'net_namespace': net, 'pid_namespace': pns}, [sid, eid, nid, npid]


def _context(reader, expected):
    boot, bid = reader.get('sys/kernel/random/boot_id', limit=128)
    net, nid = reader.get('self/ns/net', 'link')
    pns, npid = reader.get('self/ns/pid', 'link')
    anchor, reads = _identity(reader, str(expected['anchor_process']['pid']))
    wanted = expected['anchor_process']
    if (boot.decode().strip() != wanted['boot_id'] or anchor['start_ticks'] != wanted['start_ticks']
            or anchor['net_namespace'] != net or anchor['pid_namespace'] != pns):
        raise Incomplete('ACCREDITED_CONTEXT_MISMATCH')
    agent = None
    if expected.get('agent_process') is not None:
        wanted_agent = expected['agent_process']
        agent, aids = _identity(reader, str(wanted_agent['pid']))
        reads.extend(aids)
        if (wanted_agent['boot_id'] != boot.decode().strip() or agent['start_ticks'] != wanted_agent['start_ticks']
                or agent['net_namespace'] != net or agent['pid_namespace'] != pns
                or agent['executable'] != expected['agent_executable']):
            raise Incomplete('AGENT_CONTEXT_MISMATCH')
        agent['boot_id'] = boot.decode().strip()
    model=None
    if expected.get('model_process') is not None:
        wanted_model=expected['model_process'];model,mids=_identity(reader,str(wanted_model['pid']));reads.extend(mids)
        if (wanted_model['boot_id']!=boot.decode().strip() or model['start_ticks']!=wanted_model['start_ticks']
                or model['net_namespace']!=net or model['pid_namespace']!=pns
                or model['executable']!=expected['model_executable']):raise Incomplete('MODEL_CONTEXT_MISMATCH')
        model['boot_id']=boot.decode().strip()
    return {'boot_id': boot.decode().strip(), 'net_namespace': net, 'pid_namespace': pns,
            'anchor': anchor, 'agent': agent,**({'model':model} if model else {})}, [bid, nid, npid, *reads]


def _matches_peer(local, peer):
    if local['port']!=peer['port']:return False
    if local['family']==peer['family']:
        return local['address']==peer['address'] or local['wildcard']
    if local['family']=='IPv6' and peer['family']=='IPv4':
        address=ipaddress.ip_address(local['address'])
        # /proc does not expose IPV6_V6ONLY. Never exclude a possible dual-stack
        # or mapped owner, and never promote it to an exact IPv4 attribution.
        return address.is_unspecified or str(address.ipv4_mapped)==peer['address']
    return False


def _tables(reader, peers=None):
    rows, ids = [], []
    for family in ('udp', 'udp6'):
        data, rid = reader.get('self/net/'+family)
        ids.append(rid); rows.extend(table(data, family))
    # An inode unexpectedly reused across two rows is never silently overwritten.
    if len({r['inode'] for r in rows}) != len(rows):
        raise Incomplete('DUPLICATE_SOCKET_INODE')
    full=sorted(rows,key=lambda r:r['inode'])
    if peers is None:return full,ids
    scoped=[row for row in full if any(_matches_peer(row['local'],p) for p in peers)]
    return scoped,ids,{'total_udp_rows':len(full),'relevant_rows':len(scoped),
        'read_completion':'EOF_OBSERVED' if all(reader.reads[n]['operation']=='bytes_to_eof' for n in ids) else 'UNKNOWN_LEGACY_READER',
        'all_rows_sha256':hashlib.sha256(json.dumps(full,sort_keys=True).encode()).hexdigest(),
        # Diagnostic-only bounded examples from the SAME reads. Never match by
        # swapped ports or candidate resemblance; this cannot establish ownership.
        'unmatched_local_endpoints':[{k:r['local'][k] for k in ('family','address','port')} for r in full if r not in scoped][:32],
        'unmatched_endpoints_truncated':len(full)-len(scoped)>32}




def _owners(reader, target_inodes, context, owners):
    if not target_inodes:return owners,[]
    pids, listing = reader.get('.', 'list', MAX_PIDS+64)
    pids = sorted((p for p in pids if p.isdigit()), key=int)
    if len(pids) > MAX_PIDS:
        raise Incomplete('PID_BUDGET')
    fds_seen = 0
    def start(pid):
        data,rid=reader.get(f'{pid}/stat',limit=4096)
        fields=data.decode().rpartition(')')[2].split()
        if len(fields)<20 or not fields[19].isdigit() or fields[0]=='Z':raise Incomplete('PROCESS_INVALID_OR_ZOMBIE')
        return int(fields[19]),rid
    for pid in pids:
        ticks,stat_before=start(pid)
        fds, fid = reader.get(f'{pid}/fd', 'list', MAX_FDS)
        fd_values = []
        for fd in sorted(fds):
            if not fd.isdigit():
                raise Incomplete('INVALID_FD_ENTRY')
            fds_seen += 1
            if fds_seen > MAX_FDS:
                raise Incomplete('FD_BUDGET')
            link, lid = reader.get(f'{pid}/fd/{fd}', 'link')
            match = re.fullmatch(r'socket:\[([0-9]+)\]', link)
            if match and match[1] in target_inodes:
                fd_values.append((int(fd), match[1], lid))
        ticks_after,stat_after=start(pid)
        if ticks!=ticks_after:raise Incomplete('PID_RECYCLED_DURING_FD_SEARCH')
        if fd_values:
            before,before_reads=_identity(reader,pid,observed_start=(ticks_after,stat_after))
            if before['start_ticks']!=ticks:raise Incomplete('PID_RECYCLED_BEFORE_OWNER_DETAILS')
            # Scan every PID even in another namespace: an inherited FD may own
            # the same inode. Keep that owner and its actual namespaces.
            data,aid=reader.get(f'{pid}/cmdline',limit=8192);argv=argv_permitted(data)
            final,final_reads=_identity(reader,pid)
            if final!=before:raise Incomplete('PID_CHANGED_DURING_ARGV_READ')
            for fd,inode,lid in fd_values:
                owners.append({'inode':inode,'fd':fd,'process':{**before,'boot_id':context['boot_id']},
                    'argv':argv,'source_reads':list(dict.fromkeys([listing,stat_before,fid,lid,stat_after,*before_reads,aid,*final_reads]))})
    return owners, pids


def _owner_key(owner):
    return (owner['inode'], owner['fd'], json.dumps(owner['process'], sort_keys=True), json.dumps(owner['argv'], sort_keys=True))


def _validate_context(expected):
    required={'lifecycle_id','environment','anchor_process','agent_process','agent_executable','peers','native_byte_order','transport_source_sha256'}
    if not isinstance(expected, dict) or set(expected) not in (required,required|{'model_process','model_executable'}):
        raise Incomplete('MISSING_OR_UNKNOWN_PROTECTED_CONTEXT_FIELDS')
    if not isinstance(expected['lifecycle_id'],str) or not 0<len(expected['lifecycle_id'])<=64:
        raise Incomplete('INVALID_LIFECYCLE_CONTEXT')
    if len(json.dumps(expected).encode())>8192:raise Incomplete('CONTEXT_SIZE_EXCEEDED')
    if expected['native_byte_order'] not in {'little','big'} or expected['transport_source_sha256']!='0d3d11252c58b65c85762390b5c79f72a2b9f4efdae6547b09da43a611a96217':
        raise Incomplete('UNKNOWN_NATIVE_PORT_INTERPRETATION')
    peers=expected['peers']
    if not isinstance(peers,list) or not peers:raise Incomplete('NO_VALIDATED_NATIVE_PEER')
    for peer in peers:
        if not isinstance(peer,dict) or set(peer)!={'family','address','port'}:raise Incomplete('INVALID_PEER_SCOPE')
        try:address=ipaddress.ip_address(peer['address'])
        except ValueError:raise Incomplete('INVALID_PEER_SCOPE') from None
        if (peer['family']!=('IPv4' if address.version==4 else 'IPv6') or address.is_unspecified
                or str(address)!=peer['address'] or type(peer['port']) is not int or not 0<peer['port']<=65535):
            raise Incomplete('INVALID_PEER_SCOPE')
    if len({json.dumps(v,sort_keys=True) for v in peers})!=len(peers):raise Incomplete('DUPLICATE_PEER_SCOPE')
    env=expected['environment']
    if (not isinstance(env,dict) or set(env)!={'engine_id','container_id','image_id'}
            or any(not isinstance(v,str) or not 0<len(v)<=128 for v in env.values())):
        raise Incomplete('INVALID_ENVIRONMENT_CONTEXT')
    if (expected['agent_process'] is not None and (not isinstance(expected['agent_executable'],str)
            or not expected['agent_executable'].startswith('/') or len(expected['agent_executable'])>4096)):
        raise Incomplete('MISSING_EXPECTED_AGENT_EXECUTABLE')
    if 'model_process' in expected and (not isinstance(expected['model_executable'],str) or not expected['model_executable'].startswith('/')):
        raise Incomplete('MISSING_EXPECTED_MODEL_EXECUTABLE')
    for name in ('anchor_process','agent_process',*(['model_process'] if 'model_process' in expected else [])):
        identity=expected[name]
        if name=='agent_process' and identity is None:
            continue
        if (not isinstance(identity,dict) or set(identity)!={'pid','start_ticks','boot_id'}
                or type(identity['pid']) is not int or identity['pid']<=0
                or type(identity['start_ticks']) is not int or identity['start_ticks']<0
                or not isinstance(identity['boot_id'],str) or not 0<len(identity['boot_id'])<=128):
            raise Incomplete('INVALID_PROCESS_CONTEXT')


# Row-local explicit references: no dependency on another JSONL row surviving.
READ_COLUMNS = ('id','source','operation','started_monotonic','finished_monotonic',
                'at_utc','state','reason','ignored_query_directory_fds')


def pack_inventory(value):
    """Lossless domain representation; never upgrades an incomplete observation."""
    record=dict(value);sources=[];sockets=[];processes=[];argv=[];owners=[]
    source_indices={}
    def intern(pool,item):
        if item not in pool:pool.append(item)
        return pool.index(item)
    reads=[]
    for read in record.pop('reads'):
        if set(read)-set(READ_COLUMNS):raise ValueError('Unknown read fields')
        row=[read.get(k) for k in READ_COLUMNS]
        source=row[1]
        if isinstance(source,str):
            # FD inventories contain many distinct paths. Preserve first-seen
            # wire order without two linear pool scans for every read event.
            if source not in source_indices:
                source_indices[source]=len(sources);sources.append(source)
            row[1]=source_indices[source]
        else:row[1]=intern(sources,source)
        reads.append(row)
    def owner_ref(owner):
        v=dict(owner);v['process_ref']=intern(processes,v.pop('process'))
        v['argv_ref']=intern(argv,v.pop('argv'));return intern(owners,v)
    for field in ('tables_before','tables_after'):
        record[field]=[intern(sockets,v) for v in record[field]]
    for field in ('owners_before','owners_after'):
        record[field]=[owner_ref(v) for v in record[field]]
    associations=[]
    for item in record['associations']:
        socket={k:v for k,v in item.items() if k not in ('owners','association_state')}
        associations.append({'socket_ref':intern(sockets,socket),
            'owner_refs':[owner_ref(v) for v in item['owners']], 'association_state':item['association_state']})
    record['associations']=associations
    return {'schema':'tfg.xrce-sockets/2','record':record,'sources':sources,
            'read_columns':list(READ_COLUMNS),'reads':reads,'sockets':sockets,
            'processes':processes,'argv':argv,'owners':owners}


def _unpack_inventory(wire):
    if wire.get('schema')=='tfg.xrce-sockets/1':return wire
    if (wire.get('schema')!='tfg.xrce-sockets/2' or set(wire)!=
        {'schema','record','sources','read_columns','reads','sockets','processes','argv','owners'}
            or wire['read_columns']!=list(READ_COLUMNS)):
        raise ValueError('Unknown/truncated socket encoding')
    def ref(pool,index):
        if type(index) is not int or index<0 or index>=len(pool):raise ValueError('Missing socket reference')
        return pool[index]
    result=dict(wire['record']);reads=[]
    for row in wire['reads']:
        if not isinstance(row,list) or len(row)!=len(READ_COLUMNS):raise ValueError('Truncated read')
        v={k:x for k,x in zip(READ_COLUMNS,row) if x is not None}
        v['source']=ref(wire['sources'],row[1]);reads.append(v)
    result['reads']=reads
    def owner(index):
        v=dict(ref(wire['owners'],index));v['process']=ref(wire['processes'],v.pop('process_ref'))
        v['argv']=ref(wire['argv'],v.pop('argv_ref'));return v
    for field in ('tables_before','tables_after'):result[field]=[ref(wire['sockets'],n) for n in result[field]]
    for field in ('owners_before','owners_after'):result[field]=[owner(n) for n in result[field]]
    result['associations']=[{**ref(wire['sockets'],v['socket_ref']),
        'owners':[owner(n) for n in v['owner_refs']], 'association_state':v['association_state']}
        for v in result['associations']]
    # Canonical re-encoding catches unused/duplicate/reordered contradictory pools.
    if pack_inventory(result)!=wire:raise ValueError('Noncanonical/contradictory references')
    return result


def unpack_inventory(wire):
    try:
        return _unpack_inventory(wire)
    except (KeyError,TypeError,IndexError,AttributeError) as exc:
        raise ValueError('Missing/malformed socket references') from exc


def validate_inventory(value):
    """Validate provenance and rederive usable associations, never trust a label."""
    value=unpack_inventory(value)
    if value.get('schema')!='tfg.xrce-sockets/1':raise ValueError('Unknown inventory')
    if value.get('snapshot_state')!='REPEATED_READS_AGREE':return value
    _validate_context(value['context_declared_by_protected_monitor'])
    if value['reasons'] or not value['context_before'] or value['context_before']!=value['context_after']:
        raise ValueError('Missing/contradictory context')
    reads=value['reads']
    if not reads or [r['id'] for r in reads]!=list(range(len(reads))):raise ValueError('Missing read provenance')
    for field in ('context_before_reads','context_after_reads','table_before_reads','table_after_reads'):
        if not value.get(field):raise ValueError('Missing provenance references')
        for n in value[field]:
            if type(n) is not int or not 0<=n<len(reads):raise ValueError('Missing read reference')
    context=value['context_before'];declared=value['context_declared_by_protected_monitor']
    for role in ('anchor','agent',*(['model'] if 'model_process' in declared else [])):
        actual=context.get(role);expected=declared[role+'_process']
        if (not isinstance(actual,dict) or not expected or
            any(actual.get(k)!=expected[k] for k in ('pid','start_ticks')) or
            expected['boot_id']!=context.get('boot_id') or
            actual.get('net_namespace')!=context.get('net_namespace') or
            actual.get('pid_namespace')!=context.get('pid_namespace')):
            raise ValueError('Process/context association contradiction')
    if context['agent'].get('executable')!=declared['agent_executable']:raise ValueError('Agent executable contradiction')
    if 'model_process' in declared and context['model'].get('executable')!=declared['model_executable']:
        raise ValueError('Model executable contradiction')
    peers=declared['peers']
    for label in ('before','after'):
        scope=value['table_scope_'+label];table=value['tables_'+label]
        if (type(scope['total_udp_rows']) is not int or scope['total_udp_rows']<len(table)
                or scope['relevant_rows']!=len(table) or not re.fullmatch('[0-9a-f]{64}',scope['all_rows_sha256'])):
            raise ValueError('Missing/inconsistent full table coverage')
        if scope.get('read_completion')=='EOF_OBSERVED' and any(value['reads'][n].get('operation')!='bytes_to_eof' for n in value['table_'+label+'_reads']):
            raise ValueError('EOF completion/provenance contradiction')
        for row in table:
            if not any(_matches_peer(row['local'],p) for p in peers):
                raise ValueError('Socket outside declared peer scope')
    for r in reads:
        if (r.get('state')!='OBSERVED' or not isinstance(r.get('source'),str)
                or not r['source'].startswith('/proc/') or not r.get('at_utc')
                or r['finished_monotonic']<r['started_monotonic']):raise ValueError('Incomplete read provenance')
    if (value['tables_before']!=value['tables_after'] or
        sorted(map(_owner_key,value['owners_before']))!=sorted(map(_owner_key,value['owners_after']))):
        raise ValueError('Changing socket/process state')
    for o in value['owners_before']+value['owners_after']:
        if not o['source_reads'] or any(type(n) is not int or not 0<=n<len(reads) for n in o['source_reads']):
            raise ValueError('Missing owner provenance')
        sources={reads[n]['source'] for n in o['source_reads']};pid=o['process']['pid']
        if (f'/proc/{pid}/fd/{o["fd"]}' not in sources or f'/proc/{pid}/stat' not in sources
                or f'/proc/{pid}/cmdline' not in sources):raise ValueError('Owner/read association contradiction')
    associations=[]
    for row in value['tables_after']:
        owners=[o for o in value['owners_after'] if o['inode']==row['inode']]
        unique={json.dumps(o['process'],sort_keys=True) for o in owners}
        state='NO_VISIBLE_OWNER_UNKNOWN' if not owners else 'SHARED_OWNERS_AMBIGUOUS' if len(unique)>1 else 'FOREIGN_NAMESPACE_OWNER_AMBIGUOUS' if owners and any(o['process']['net_namespace']!=context['net_namespace'] or o['process']['pid_namespace']!=context['pid_namespace'] for o in owners) else 'REPEATED_PROCESS_FD_ASSOCIATION'
        associations.append({**row,'owners':owners,'association_state':state})
    if value['associations']!=associations:raise ValueError('Contradictory derived associations')
    return value


def collect(expected, *, reader=None, diagnostic=None):
    """Only reads proc. Synchronous budget is cooperative; monitor adds timeout.

    expected comes from the protected descriptor + launch PID/start/boot. Engine
    and container fields remain declarations of that caller, not Docker queries.
    """
    reader = Reader() if reader is None else reader
    result = {'schema': 'tfg.xrce-sockets/1', 'status': 'BLOCKED', 'source_association_verified': False,
              'movement_authorized': False, 'snapshot_state': 'INCOMPLETE', 'atomic': False,
              'context_declared_by_protected_monitor': None, 'context_before': None, 'context_after': None,
              'tables_before': [], 'tables_after': [], 'owners_before': [], 'owners_after': [],
              'associations': [], 'reasons': [], 'reads': reader.reads,
              'limits': {'wall_budget_s': BUDGET, 'reads': MAX_READS, 'pids': MAX_PIDS,
                         'fds_per_pass': MAX_FDS, 'serialized_bytes': MAX_BYTES}}
    try:
        _validate_context(expected)
        result['context_declared_by_protected_monitor'] = expected
        context, ids = _context(reader, expected)
        result.update(context_before=context, context_before_reads=ids)
        rows, ids, scope = _tables(reader, expected['peers']); result.update(tables_before=rows, table_before_reads=ids, table_scope_before=scope)
        result['owners_before'], pids_before = _owners(reader, {r['inode'] for r in rows}, context, result['owners_before'])
        result['owners_after'], pids_after = _owners(reader, {r['inode'] for r in rows}, context, result['owners_after'])
        after, ids, scope = _tables(reader, expected['peers']); result.update(tables_after=after, table_after_reads=ids, table_scope_after=scope)
        context_after, ids = _context(reader, expected); result.update(context_after=context_after, context_after_reads=ids)
        if (context != context_after or rows != after or pids_before != pids_after
                or sorted(map(_owner_key, result['owners_before'])) != sorted(map(_owner_key, result['owners_after']))):
            raise Incomplete('TABLE_PROCESS_FD_OR_CONTEXT_CHANGED')
        result['snapshot_state'] = 'REPEATED_READS_AGREE'
        for row in rows:
            owners = [o for o in result['owners_after'] if o['inode'] == row['inode']]
            unique_processes = {json.dumps(o['process'], sort_keys=True) for o in owners}
            state = ('NO_VISIBLE_OWNER_UNKNOWN' if not owners else 'SHARED_OWNERS_AMBIGUOUS'
                     if len(unique_processes) > 1 else 'FOREIGN_NAMESPACE_OWNER_AMBIGUOUS'
                     if owners and any(o['process']['net_namespace']!=context['net_namespace'] or o['process']['pid_namespace']!=context['pid_namespace'] for o in owners) else 'REPEATED_PROCESS_FD_ASSOCIATION')
            result['associations'].append({**row, 'owners': owners, 'association_state': state})
    except (Incomplete, ValueError, KeyError, TypeError, UnicodeError) as exc:
        failed=next((v for v in reversed(reader.reads) if v.get('state')=='UNKNOWN'),None)
        if failed:
            code=failed.get('reason')
            result['search_failure']={'class':'PROC_ENTRY_DISAPPEARED' if code=='ENOENT' else
                'PERMISSION_DENIED' if code in {'EACCES','EPERM'} else 'READ_FAILED',
                'source':failed['source'],'reason':code,'started_monotonic':failed['started_monotonic'],
                'finished_monotonic':failed['finished_monotonic'],'at_utc':failed['at_utc']}
        result['reasons'].append(str(exc) if isinstance(exc, Incomplete) else type(exc).__name__)
    if diagnostic is not None:
        diagnostic('READS_FINISHED', snapshot_state=result['snapshot_state'],
                   read_events=len(reader.reads), read_calls=reader.counts['read_calls'])
    return _account_inventory(result,reader.counts)


def _account_inventory(result,counts):
    """Bound the existing wire record after EOF reads; no new observations."""
    packed=pack_inventory(result)
    sections={key:len(json.dumps(value,separators=(',',':')).encode()) for key,value in packed.items()}
    encoded=json.dumps(packed,separators=(',',':')).encode()
    result['size_diagnostics']={'before_fallback_wire_bytes':len(encoded)+1,'section_value_bytes':sections,
        'retained_read_events':len(result['reads']),'owners_before':len(result['owners_before']),
        'owners_after':len(result['owners_after']),'target_socket_rows':len(result['tables_before']),'search_counts':counts,
        'wire_bytes_before_accounting':len(encoded)+1,'framing_bytes':len(encoded)-sum(sections.values())}
    # Only this accounting dictionary changes during the fixed-point passes.
    # Reuse the lossless packed pools instead of rebuilding all read references
    # on each pass. Fallbacks below still repack their changed evidence.
    packed['record']['size_diagnostics']=result['size_diagnostics']
    for _ in range(3):
        result['size_diagnostics']['before_fallback_wire_bytes']=len(json.dumps(packed,separators=(',',':')).encode())+1
    encoded=json.dumps(packed,separators=(',',':')).encode()+b'\n'
    if len(encoded) > MAX_BYTES:
        # Do not serialize truncated rows as a usable ownership proof. Explicitly
        # retain only the bounded early read provenance and mark lost coverage.
        result.update(snapshot_state='INCOMPLETE', associations=[], owners_before=[], owners_after=[],
                      reads=result['reads'][:32], reasons=[*result['reasons'],'OUTPUT_BUDGET_DATA_INCOMPLETE'],
                      tables_before=[], tables_after=[])
        encoded=json.dumps(pack_inventory(result),separators=(',',':')).encode()+b'\n'
    if len(encoded)>MAX_BYTES:
        for side in ('before','after'):
            scope=result.get('table_scope_'+side,{})
            if scope.pop('unmatched_local_endpoints',None):
                scope['unmatched_endpoints_omitted_for_output_budget']=True
        encoded=json.dumps(pack_inventory(result),separators=(',',':')).encode()+b'\n'
    while len(encoded)>MAX_BYTES and result['reads']:
        result['reads'].pop()
        encoded=json.dumps(pack_inventory(result),separators=(',',':')).encode()+b'\n'
    return result


def fdm_targets(events,model,lifecycle_id):
    """Actual successful send destinations; never reuse an XRCE port as FDM."""
    if not model or model.get('verified_overlay_library') is not True:return []
    targets=[]
    for e in events:
        if e.get('event')!='fdm_send':continue
        if (e.get('schema')!='tfg.model-source/1' or e.get('incomplete') or e.get('lifecycle_id')!=lifecycle_id or any(str(e.get(a))!=str(model[b]) for a,b in
                [('pid','pid'),('process_start_ticks','start_ticks'),('boot_id','boot_id')])):
            raise ValueError('Foreign model send context')
        if e.get('bytes_expected',0)<=0 or e.get('bytes_sent')!=e['bytes_expected']:
            continue  # no successful send, never a receiver association
        address=ipaddress.ip_address(e['destination_address']);port=e['destination_port']
        if address.is_unspecified or type(port) is not int or not 0<port<=65535:raise ValueError('Unknown FDM destination')
        target={'family':'IPv4' if address.version==4 else 'IPv6','address':str(address),'port':port}
        if target not in targets:targets.append(target)
    return targets


def match_fdm_receiver(inventory,send,model,lifecycle_id,*,expected_sitl=None):
    """Kernel endpoint/FD ownership candidate, NOT proof of payload reception."""
    r={'state':'UNKNOWN','candidates':[],'payload_received':False,'effective_sysid_verified':False,'movement_authorized':False}
    try:
        v=validate_inventory(inventory);context=v['context_declared_by_protected_monitor']
        targets=fdm_targets([send],model,lifecycle_id)
        if len(targets)!=1:raise ValueError('No successful FDM send')
        endpoint=targets[0]
        if context['lifecycle_id']!=lifecycle_id or v['snapshot_state']!='REPEATED_READS_AGREE':raise ValueError('Session or repeated coverage incomplete')
        expected=context.get('model_process')
        if not expected or any(str(expected[k])!=str(model[k]) for k in ('pid','start_ticks','boot_id')):
            raise ValueError('Model not bound to collector namespace/context')
        reads=v['reads'];begin=min(x['started_monotonic'] for x in reads);end=max(x['finished_monotonic'] for x in reads)
        if type(send.get('steady_ns')) is not int or send['steady_ns']<=0 or send['steady_ns']/1e9>end:
            raise ValueError('Missing/future send observation clock')
        r['temporal_scope']={'ownership_read_monotonic':[begin,end],'send_monotonic':send['steady_ns']/1e9,
            'interpretation':'Repeated ownership observations after a successful send; not atomic with that send or proof of reception'}
        if endpoint not in context['peers']:raise ValueError('FDM destination not in actual search scope')
        if any(v['table_scope_'+side].get('read_completion')!='EOF_OBSERVED' for side in ('before','after')):
            raise ValueError('Full UDP table EOF not established')
        if not ipaddress.ip_address(endpoint['address']).is_loopback:
            raise ValueError('Remote/non-loopback locality not established by this inventory')
        matches=[a for a in v['associations'] if _matches_peer(a['local'],endpoint)]
        r['candidates']=matches
        if len(matches)!=1:raise ValueError('No unique receiving socket')
        a=matches[0]
        if a['local']['family']!=endpoint['family']:raise ValueError('Dual-stack receiver ambiguous')
        remote=a['remote'];source=send['socket_observation']
        if not (remote['wildcard'] and remote['port']==0) and (remote['address'],remote['port'])!=(source['address'],source['port']):
            raise ValueError('Connected receiver filters another source')
        if a['association_state']!='REPEATED_PROCESS_FD_ASSOCIATION':raise ValueError('Shared/unknown receiver ownership')
        owner=a['owners'][0]['process']
        if expected_sitl is None:raise ValueError('Receiver PID observed but expected SITL instance not bound')
        if Path(expected_sitl.get('executable','')).name!='ardurover':raise ValueError('Receiver is not a rover SITL executable')
        if any(owner.get(k)!=expected_sitl.get(k) for k in ('pid','start_ticks','boot_id','executable','net_namespace','pid_namespace')):
            raise ValueError('Receiver differs from current expected SITL process')
        r.update(state='FDM_DESTINATION_TO_VISIBLE_SITL_SOCKET_OBSERVED',receiver=owner,
            inode=a['inode'],fds=[o['fd'] for o in a['owners']],destination=endpoint)
    except (Incomplete,KeyError,TypeError,ValueError) as exc:r['reason']=str(exc)
    return r


def match_peer(inventory, writer, lifecycle_id):
    """Metadata candidate only, not proof of packet origin or effective SYSID."""
    result = {'status': 'BLOCKED', 'movement_authorized': False,
              'source_association_verified': False, 'packet_origin_verified': False,
              'link_state': 'UNKNOWN', 'candidates': []}
    try:
        inventory = validate_inventory(inventory)
        context = inventory['context_declared_by_protected_monitor']
        if context['lifecycle_id'] != lifecycle_id or inventory['snapshot_state'] != 'REPEATED_READS_AGREE':
            raise ValueError('Session mismatch or incomplete/changing inventory')
        agent = inventory['context_before']['agent']
        if not agent or any(str(agent[a]) != str(writer[b]) for a,b in (
                ('pid','pid'),('start_ticks','process_start_ticks'),('boot_id','boot_id'))):
            raise ValueError('Agent process identity mismatch or unavailable')
        peer = writer['transport_peer']
        if (peer is None or peer.get('generation_binding') != 'SAME_PROXYCLIENT_REFERENCE'
                or peer.get('source') != 'Processor InputMessage metadata before session queue'):
            raise ValueError('No generation-bound peer')
        try:
            from .analyze import normalized_udp_peer
        except ImportError:
            from analyze import normalized_udp_peer
        peer = normalized_udp_peer(writer,native_byte_order=context['native_byte_order'],
            transport_source_sha256=context['transport_source_sha256'])
        result['peer_interpretation']={
            'raw_recorded':{k:writer['transport_peer'][k] for k in ('family','address','port')},
            'transformation':'Native uint16_t storing sin_port -> network-order bytes -> host-order port',
            'native_elf_byte_order':context['native_byte_order'],
            'transport_source_sha256':context['transport_source_sha256'],
            'normalized_derived':dict(peer),'normalized_endpoint_is_direct_observation':False,
            'kernel_table_matches':[], 'full_tables_eof':False,
            'not_observed_does_not_prove_absence':True}
        address = ipaddress.ip_address(peer['address'])
        if address.is_unspecified or type(peer['port']) is not int or not 0 < peer['port'] <= 65535:
            raise ValueError('Invalid peer endpoint')
        family = 'IPv4' if address.version == 4 else 'IPv6'
        if {'family':family,'address':address.compressed,'port':peer['port']} not in context['peers']:
            raise ValueError('Writer peer not included in observed search scope')
        if family != peer['family']:
            raise ValueError('Peer family mismatch')
        candidates = [r for r in inventory['associations'] if _matches_peer(r['local'],{'family':family,'address':address.compressed,'port':peer['port']})]
        result['candidates'] = candidates
        complete=all(inventory['table_scope_'+side].get('read_completion')=='EOF_OBSERVED' for side in ('before','after'))
        result['peer_interpretation'].update(kernel_table_matches=[r['local'] for r in candidates],full_tables_eof=complete)
        if len(candidates) > 1:
            result['link_state'] = 'MULTIPLE_SOCKETS_AMBIGUOUS'
        elif not candidates:
            result['link_state'] = 'NOT_OBSERVED_NOT_ABSENCE_PROOF'
        elif not complete:
            result['link_state']='TABLE_COMPLETENESS_NOT_ESTABLISHED'
        elif candidates[0]['local']['family']!=family:
            result['link_state']='DUAL_STACK_SOCKET_AMBIGUOUS'
        elif candidates[0]['local']['wildcard']:
            result['link_state'] = 'WILDCARD_BIND_CANDIDATE_ONLY'
        elif candidates[0]['association_state'] == 'REPEATED_PROCESS_FD_ASSOCIATION':
            result['link_state'] = 'EXACT_ENDPOINT_UNIQUE_VISIBLE_PROCESS_CANDIDATE'
        else:
            result['link_state'] = candidates[0]['association_state']
    except (Incomplete, KeyError, TypeError, ValueError) as exc:
        result['reason'] = str(exc)
    return result


def analyze_series(data, monitor_summary, writer, lifecycle_id, *, receipt_wall_ns=None, closure_evidence=None, fdm_sends=(), model=None):
    """Offline JSONL reader: never cherry-pick a stable row from a changing file."""
    result = {'status': 'BLOCKED', 'source_association_verified': False, 'movement_authorized': False,
              'series_state': 'UNCERTAIN_OR_INCOMPLETE', 'rows': [], 'errors': [],
              'usable_windows': [], 'partial_table_windows': [], 'terminal_context_loss': None, 'fdm_rows': [],
              'covers_entire_monitor_interval': False,
              'sampling_limit_reached': bool(monitor_summary.get('sampling_limit_reached',False))}
    try:
        if monitor_summary.get('error') or monitor_summary.get('peer_waiting'):
            raise ValueError('Monitor/socket journal error contradiction')
        declared_budget=monitor_summary.get('budget')
        if declared_budget is not None and declared_budget!=SOCKET.record():
            raise ValueError('Monitor/reader budget mismatch')
        owners = set();windows=[];count=0;serialized_bytes=0;last_row=None
        for line in journal_rows(data):
            count+=1;serialized_bytes+=len(line)
            row = unpack_inventory(json.loads(line))
            last_row=row;window=None
            if (row.get('schema') != 'tfg.xrce-sockets/1' or row.get('status') != 'BLOCKED'
                    or row.get('source_association_verified') is not False or row.get('movement_authorized') is not False):
                raise ValueError('Unknown socket schema/state')
            if row.get('reads'):
                wall=[]
                for read in row['reads']:
                    at=datetime.fromisoformat(read['at_utc'])
                    if at.tzinfo is None:raise ValueError('Unknown wall reception timezone')
                    begin=int(at.timestamp()*1_000_000_000)
                    wall.append((begin,begin+int((read['finished_monotonic']-read['started_monotonic'])*1_000_000_000)))
                if any(wall[i][0]>wall[i+1][0] for i in range(len(wall)-1)):
                    raise ValueError('Wall reception clock moved backwards')
                window=(min(v[0] for v in wall),max(v[1] for v in wall));windows.append(window)
            match = match_peer(row, writer, lifecycle_id)
            result['rows'].append(match)
            if match['link_state']=='TABLE_COMPLETENESS_NOT_ESTABLISHED' and window is not None:
                result['partial_table_windows'].append({'observation':count,'wall_ns':window,
                    'processes':[o['process'] for candidate in match['candidates'] for o in candidate['owners']],
                    'scope':'RETAINED_PREFIX_CANDIDATES_NO_EOF_NO_UNIQUENESS'})
            if fdm_sends:
                # Same row, same namespaces and two owner sweeps for both
                # transports. Never substitute a similarly named SITL PID.
                expected=None
                if match['link_state']=='EXACT_ENDPOINT_UNIQUE_VISIBLE_PROCESS_CANDIDATE':
                    expected=match['candidates'][0]['owners'][0]['process']
                result['fdm_rows'].append({'observation':count,'sends':[
                    {'sequence':send.get('sequence'),'model_entity':send.get('model_entity'),
                     **match_fdm_receiver(row,send,model,lifecycle_id,expected_sitl=expected)} for send in fdm_sends]})
            if match['link_state'] == 'EXACT_ENDPOINT_UNIQUE_VISIBLE_PROCESS_CANDIDATE':
                if window is not None:
                    result['usable_windows'].append({'observation':count,'wall_ns':window,
                        'processes':[o['process'] for o in match['candidates'][0]['owners']],
                        'scope':'LOCALLY_VALIDATED_SWEEP_NOT_ATOMIC_PACKET_ORIGIN'})
                for owner in match['candidates'][0]['owners']:
                    owners.add(json.dumps(owner['process'], sort_keys=True))
        result['serialized_bytes']=serialized_bytes
        result['observations']=count
        if ('journal_bytes_written' in monitor_summary
                and monitor_summary['journal_bytes_written']!=serialized_bytes):
            raise ValueError('Monitor/socket persisted byte count contradiction')
        if count!=monitor_summary['snapshots']:
            raise ValueError('Monitor/socket journal count contradiction')
        if last_row and last_row.get('snapshot_state')=='INCOMPLETE':
            failure=last_row.get('search_failure',{})
            if failure.get('class')=='PROC_ENTRY_DISAPPEARED':
                loss={'classification':'UNATTRIBUTED_TERMINAL_CONTEXT_LOSS','failure':failure,
                      'does_not_complete_series':True}
                result['terminal_context_loss']=loss
                if closure_evidence is not None:
                    monitor=closure_evidence['monitor'];stop=closure_evidence['stop_operation'];target=closure_evidence['target']
                    context=last_row['context_declared_by_protected_monitor'];agent=context['agent_process']
                    expected={'pid':writer['pid'],'start_ticks':int(writer['process_start_ticks']),'boot_id':writer['boot_id']}
                    at=datetime.fromisoformat(failure['at_utc'])
                    start=datetime.fromisoformat(stop['started_at']);end=datetime.fromisoformat(stop['finished_at'])
                    if (monitor['lifecycle_id']==lifecycle_id and monitor['phase']=='CLOSED'
                            and monitor['closure_requested'] is True and monitor['capture_complete'] is True
                            and monitor['socket_inventory']==monitor_summary
                            and stop['action']=='stop' and stop['state']=='FINISHED'
                            and target['state']=='CLOSED' and target['closed_by']==stop['owner_id']
                            and target['descriptor']['lifecycle_id']==lifecycle_id
                            and context['lifecycle_id']==lifecycle_id and agent==expected
                            and failure['source']==f"/proc/{agent['pid']}/stat" and start<=at<=end):
                        loss['classification']='AGENT_CONTEXT_LOST_DURING_RECORDED_PROTECTED_CLOSURE'
                    else:raise ValueError('Terminal loss closure evidence contradiction')
        if (len(owners) == 1 and result['rows'] and all(r['link_state'] ==
                'EXACT_ENDPOINT_UNIQUE_VISIBLE_PROCESS_CANDIDATE' for r in result['rows'])):
            result['series_state'] = 'REPEATED_ENDPOINT_PROCESS_CANDIDATE_ONLY'
        elif len(owners) > 1:
            result['errors'].append('Peer endpoint has changing visible process owners across observations')
        result['reception_coverage']={'state':'NOT_CHECKED','windows':windows,
            'interpretation':'Wall reception times in the same accredited environment; not source/simulated timestamps or atomic packet attribution.'}
        if receipt_wall_ns is not None:
            if (not receipt_wall_ns or any(type(v) is not int or v<=0 for v in receipt_wall_ns)
                    or len(windows)!=count or not windows):raise ValueError('Missing reception coverage')
            covered=all(windows[0][0]<=v<=windows[-1][1] for v in receipt_wall_ns)
            result['reception_coverage']['state']='WITHIN_SAMPLED_SPAN_NOT_ATOMIC' if covered else 'OUTSIDE_SAMPLED_SPAN'
            result['reception_coverage']['sample_receipt_wall_ns']=receipt_wall_ns
            usable=[v['wall_ns'] for v in result['usable_windows']]
            result['reception_coverage']['within_usable_sampled_span']=(bool(usable) and len(owners)==1
                and all(usable[0][0]<=v<=usable[-1][1] for v in receipt_wall_ns))
            result['reception_coverage']['inside_individual_usable_sweeps']=[
                any(a<=v<=b for a,b in usable) for v in receipt_wall_ns]
            if not covered:
                result['series_state']='UNCERTAIN_OR_INCOMPLETE'
                result['errors'].append('Status reception is outside socket observation coverage')
    except (OSError, ValueError, KeyError, TypeError) as exc:
        result['series_state']='UNCERTAIN_OR_INCOMPLETE'
        result['errors'].append(str(exc))
    return result


def main():
    # Internal monitor helper. No ROS, shell, services or controls.
    if os.environ.get('TFG_SIM_PROJECT') != 'Agentic_Drone_Mission_Control':
        raise SystemExit('Protected diagnostic context required')
    def stage(name, **fields):
        # Six fixed, small records on the already-captured stderr pipe. No proc
        # reads, alternate collector, arbitrary environment, or context payload.
        row={'schema':'tfg.socket-query-stage/1','stage':name,
             'pid':os.getpid(),'monotonic':time.monotonic(),**fields}
        sys.stderr.buffer.write(json.dumps(row,separators=(',',':')).encode()+b'\n')
        sys.stderr.buffer.flush()
    stage('INPUT')
    data = sys.stdin.buffer.read(8193)
    if len(data) > 8192:
        raise SystemExit('Context size exceeded')
    expected = json.loads(data)
    stage('COLLECT', input_bytes=len(data), input_sha256=hashlib.sha256(data).hexdigest())
    result=collect(expected, diagnostic=stage)
    stage('COLLECT_RETURNED', snapshot_state=result['snapshot_state'])
    output=encode_row(pack_inventory(result))
    stage('OUTPUT', bytes=len(output))
    if sys.stdout.buffer.write(output)!=len(output):raise SystemExit('Socket output short write')
    sys.stdout.buffer.flush()
    stage('OUTPUT_FLUSHED')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
