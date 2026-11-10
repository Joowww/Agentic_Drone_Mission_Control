"""Passive, bounded log drain and process/library observation. Never starts an agent."""
import hashlib
import json
import os
from pathlib import Path
import signal
import sys
import time
import subprocess
import re
import base64
try:
    from .selection import read_json, verify_overlay, atomic_record
except ImportError:
    from selection import read_json, verify_overlay, atomic_record

try:
    from .budget import SOCKET, encode_row
except ImportError:
    from budget import SOCKET, encode_row

TRACE_LIMIT=512
BYTE_LIMIT=2*1024*1024
SCAN_LIMIT=64*1024*1024
DURATION=SOCKET.monitor_s
SOURCE=Path('/tmp/tfg_demo.log')


class SocketRecorder:
    """Separate passive channel; no retries after a failed/uncertain sample.

    Runs only inside the already-selected diagnostic monitor. The outer timeout
    bounds a hung /proc read by terminating only its own query child; never an
    agent, SITL, worker or process discovered in the inventory.
    """
    INTERVAL = SOCKET.interval_s
    LIMIT = SOCKET.observations
    MAX_ROW = SOCKET.row_bytes
    TIMEOUT = SOCKET.query_timeout_s

    def __init__(self, prefix, value, *, runner=subprocess.run):
        self.prefix, self.value, self.runner = Path(prefix), value, runner
        self.count, self.next_at, self.failed, self.incomplete = 0, 0., None, 0
        self.output = None
        self.peer_waiting = None
        self.bytes_written = 0
        self.last_started = self.last_finished = None
        self.query_diagnostic = None

    def _stage(self, name):
        if self.query_diagnostic is not None:
            self.query_diagnostic['stage'] = name
            self.query_diagnostic['stage_elapsed_s'][name] = time.monotonic()-self.query_diagnostic['started_monotonic']

    def _query_streams(self, stdout, stderr, *, complete):
        # Preserve bounded original bytes, including TimeoutExpired partial pipes.
        # A partial/truncated pipe is diagnostic only, never an inventory row.
        for name, data in (('stdout', stdout), ('stderr', stderr)):
            if data is None: data = b''
            if isinstance(data, str): data = data.encode()
            self.query_diagnostic[name] = {
                'available_bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest(),
                'prefix_base64': base64.b64encode(data[:2048]).decode(),
                'prefix_limit_bytes': 2048, 'truncated': len(data)>2048,
                'complete_pipe_observed': complete}

    def summary(self):
        return {'path': str(self.prefix/'capture/sockets.jsonl'), 'snapshots': self.count,
                'peer_waiting':self.peer_waiting,
                'state': 'UNKNOWN' if self.failed else 'WAITING_NATIVE_PEER' if self.peer_waiting else 'PARTIAL_SNAPSHOTS' if self.incomplete else 'BOUNDED_METADATA_ONLY',
                'incomplete_snapshots': self.incomplete, 'sampling_limit_reached': self.count >= self.LIMIT,
                'error': self.failed, 'sample_limit': self.LIMIT, 'interval_s': self.INTERVAL,
                'query_timeout_s': self.TIMEOUT, 'atomic': False,
                'budget':SOCKET.record(), 'journal_bytes_written':self.bytes_written,
                'next_observation_monotonic':self.next_at,
                'last_started_monotonic':self.last_started,'last_finished_monotonic':self.last_finished,
                'query_diagnostic':self.query_diagnostic,
                'source_association_verified': False, 'movement_authorized': False}

    def sample(self, root, agent, now, model=None, model_events=()):
        if root is None or agent is None or self.failed or now < self.next_at or self.count >= self.LIMIT:
            return
        self.next_at = now + self.INTERVAL
        self.last_started=now
        self.query_diagnostic = {
            'schema': 'tfg.socket-query-diagnostic/1',
            'started_monotonic': time.monotonic(), 'stage_elapsed_s': {},
            'return_code': None, 'persisted': False}
        self._stage('PREPARE_CONTEXT')
        context = {'lifecycle_id': self.value['lifecycle_id'],
                   'environment': {k:self.value['manifest'][k] for k in ('engine_id','container_id','image_id')},
                   'anchor_process': {k:root[k] for k in ('pid','start_ticks','boot_id')},
                   'agent_executable': agent['executable'],
                   'agent_process': {k:agent[k] for k in ('pid','start_ticks','boot_id')} if agent else None}
        try:
            try:
                from tools.rover_xrce_trace.analyze import analyze, normalized_udp_peer, UDP_PORT_SOURCE_SHA256
            except ModuleNotFoundError:
                from analyze import analyze, normalized_udp_peer, UDP_PORT_SOURCE_SHA256
            trace_path=self.prefix/'capture/trace.log'
            if not trace_path.exists():self.peer_waiting='NO_TRACE_YET';return
            with trace_path.open('rb') as trace_stream:
                data=trace_stream.read(BYTE_LIMIT+1)
            if len(data)>BYTE_LIMIT:raise ValueError('TRACE_SIZE_EXCEEDED')
            report=analyze(data.decode().splitlines())
            if not report['trace_valid']:self.peer_waiting='NATIVE_PREFIX_NOT_YET_VALID';return
            peers=[]
            for writer in report['correlations']:
                if writer['topic']!='rt/ap/v3/status' or writer.get('transport_peer') is None:continue
                if any(str(writer[a])!=str(agent[b]) for a,b in [('pid','pid'),('process_start_ticks','start_ticks'),('boot_id','boot_id')]):
                    raise ValueError('NATIVE_AGENT_CONTEXT_MISMATCH')
                peer=normalized_udp_peer(writer,native_byte_order=agent.get('native_byte_order'),transport_source_sha256=UDP_PORT_SOURCE_SHA256)
                if peer not in peers:peers.append(peer)
            if not peers:self.peer_waiting='NO_CONFIRMED_STATUS_PEER';return
            if model:
                try:
                    from tools.rover_xrce_trace.socket_inventory import fdm_targets
                except ModuleNotFoundError:
                    from socket_inventory import fdm_targets
                for peer in fdm_targets(model_events,model,self.value['lifecycle_id']):
                    if peer not in peers:peers.append(peer)
                context.update(model_process={k:model[k] for k in ('pid','start_ticks','boot_id')},model_executable=model['executable'])
            self.peer_waiting=None;context.update(peers=peers,native_byte_order=agent.get('native_byte_order'),transport_source_sha256=UDP_PORT_SOURCE_SHA256)
            if len(json.dumps(context).encode())>8192:raise ValueError('PEER_CONTEXT_SIZE_EXCEEDED')
            argv = [sys.executable, str(self.prefix/'socket_inventory.py')]
            payload = json.dumps(context).encode()
            self.query_diagnostic.update({
                'command': argv,
                'helper_sha256': self.value.get('helpers', {}).get('socket_inventory.py'),
                'transport': 'LOCAL_CHILD_STDIN_STDOUT_STDERR_PIPES',
                'cwd': os.getcwd(), 'project_context': os.environ.get('TFG_SIM_PROJECT'),
                'environment_policy': 'INHERITED_NO_OVERRIDES_NO_FULL_ENV_CAPTURE',
                'context': context, 'input_sha256': hashlib.sha256(payload).hexdigest(),
                'input_bytes': len(payload), 'timeout_s': self.TIMEOUT})
            self._stage('OPEN_JOURNAL')
            if self.output is None:
                self.output = (self.prefix/'capture/sockets.jsonl').open('xb')
                os.chmod(self.prefix/'capture/sockets.jsonl', 0o600)
            self._stage('QUERY')
            outcome = self.runner(argv,
                                  input=payload, capture_output=True,
                                  timeout=self.TIMEOUT, check=False)
            self.query_diagnostic['return_code'] = outcome.returncode
            self._query_streams(outcome.stdout, getattr(outcome, 'stderr', b''), complete=True)
            self._stage('VALIDATE_QUERY')
            if outcome.returncode or len(outcome.stdout)>self.MAX_ROW:
                raise ValueError('SOCKET_QUERY_FAILED_OR_OUTPUT_LIMIT')
            try:
                from tools.rover_xrce_trace.socket_inventory import unpack_inventory
            except ModuleNotFoundError:
                from socket_inventory import unpack_inventory
            wire = json.loads(outcome.stdout)
            row = unpack_inventory(wire)
            if (not isinstance(row,dict) or row.get('schema') != 'tfg.xrce-sockets/1' or row.get('status') != 'BLOCKED'
                    or row.get('movement_authorized') is not False or row.get('source_association_verified') is not False
                    or row.get('context_declared_by_protected_monitor') != context):
                raise ValueError('SOCKET_QUERY_CONTEXT_OR_SCHEMA_MISMATCH')
            self._stage('ENCODE_ROW')
            data = encode_row(wire)
            if (len(data)>self.MAX_ROW or self.bytes_written+len(data)>SOCKET.journal_bytes
                    or os.fstat(self.output.fileno()).st_size!=self.bytes_written):
                raise OSError('SOCKET_RECORD_OR_JOURNAL_LIMIT_OR_EXTERNAL_CHANGE')
            self._stage('PERSIST_WRITE')
            if self.output.write(data)!=len(data):
                raise OSError('SOCKET_OUTPUT_SHORT_WRITE_OR_LIMIT')
            self.bytes_written+=len(data)
            self._stage('PERSIST_FLUSH'); self.output.flush()
            self._stage('PERSIST_FSYNC'); os.fsync(self.output.fileno())
            self.count += 1
            self.query_diagnostic['persisted'] = True
            self._stage('PERSISTED')
            self.last_finished=time.monotonic()
            if row.get('snapshot_state') != 'REPEATED_READS_AGREE':
                self.incomplete += 1
        except (OSError, ValueError, subprocess.SubprocessError) as exc:
            if self.query_diagnostic is not None:
                if isinstance(exc, subprocess.TimeoutExpired):
                    self._query_streams(exc.output, exc.stderr, complete=False)
                self.query_diagnostic['failure'] = {
                    'stage': self.query_diagnostic['stage'], 'class': type(exc).__name__,
                    'message': str(exc)[:512], 'errno': getattr(exc, 'errno', None),
                    'observed_monotonic': time.monotonic()}
            self.failed = type(exc).__name__+':SOCKET_QUERY_OR_PERSISTENCE_UNCERTAIN'

    def close(self):
        if self.output is not None:
            try:
                self.output.flush(); os.fsync(self.output.fileno()); self.output.close()
            except OSError as exc:
                # Closing must not erase the earlier query/persistence diagnosis.
                if self.query_diagnostic is not None:
                    self.query_diagnostic['close_error'] = {
                        'class': type(exc).__name__, 'message': str(exc)[:512],
                        'errno': exc.errno, 'observed_monotonic': time.monotonic()}
                if self.failed is None: self.failed = 'SOCKET_CLOSE_UNCERTAIN'


def capture_window(record, *, now, observed_boot_id, outer_capture_s=140, stop_s=60, passive_measurement=False):
    """Pure diagnostic admission check for the future local evidence driver.

    Invoke inside the accredited container immediately before executing the
    collector. Does not authorize movement, query processes or extend a budget.
    140/60 are the existing outer capture/lifecycle timeout bounds, not new waits.
    """
    if (record.get('phase')!='OBSERVING' or record.get('errors') or
        record.get('monitor',{}).get('boot_id')!=observed_boot_id):
        raise ValueError('Monitor context/phase not current and verified')
    if now<record['observation_monotonic'] or now-record['observation_monotonic']>SocketRecorder.INTERVAL:
        raise ValueError('Stale monitor observation')
    import math
    values=(now,record['started_monotonic'],record['duration_limit_s'],outer_capture_s,stop_s)
    if any(type(v) not in (int,float) or not math.isfinite(v) for v in values) or min(outer_capture_s,stop_s)<=0:
        raise ValueError('Invalid diagnostic timing')
    deadline=record['started_monotonic']+record['duration_limit_s']
    remaining=deadline-now
    socket=record.get('socket_inventory',{})
    if passive_measurement:
        count=socket.get('snapshots');written=socket.get('journal_bytes_written')
        if (socket.get('budget')!=SOCKET.record() or type(count) is not int or not 0<=count<SOCKET.observations
                or type(written) is not int or not 0<=written<=SOCKET.journal_bytes):
            raise ValueError('Unknown diagnostic resource counters')
        if remaining<outer_capture_s+stop_s+SOCKET.query_timeout_s:raise ValueError('Insufficient capture AND close time')
        return {'monitor_remaining_s':remaining,'capture_budget_s':outer_capture_s,'close_budget_s':stop_s,
            'socket_ownership':'UNKNOWN_OR_PARTIAL' if socket.get('error') or socket.get('peer_waiting') or socket.get('incomplete_snapshots') or not count else 'NOT_CREDITED_BY_ADMISSION',
            'socket_collection_error':socket.get('error'),'movement_authorized':False,
            'meaning':'PASSIVE_MEASUREMENT_ONLY_NOT_IDENTITY_OR_UNIQUENESS','scheduled_not_observed':True}
    if (socket.get('error') or socket.get('peer_waiting') or socket.get('incomplete_snapshots') or
        socket.get('sampling_limit_reached') or not socket.get('snapshots') or
        socket.get('budget')!=SOCKET.record() or socket.get('sample_limit')!=SOCKET.observations
            or socket.get('interval_s')!=SOCKET.interval_s):
        raise ValueError('Socket coverage incomplete/exhausted or budget unknown')
    count=socket['snapshots'];written=socket.get('journal_bytes_written')
    next_at=socket.get('next_observation_monotonic');last=socket.get('last_finished_monotonic')
    if (type(count) is not int or not 0<count<SOCKET.observations or type(written) is not int
            or not count<=written<=min(SOCKET.journal_bytes,count*SOCKET.row_bytes) or
            any(type(v) not in (int,float) or not math.isfinite(v) for v in (next_at,last))
            or not record['started_monotonic']<=last<=now or now-last>SOCKET.interval_s
            or not now<next_at<=last+SOCKET.interval_s):
        raise ValueError('Stale, contradictory or missed socket schedule')
    # Capacity uses WORST-CASE framed rows, not expected small rows. Future times
    # are a schedule conditional on timely queries, not observed future coverage.
    slots=min(SOCKET.observations-count,(SOCKET.journal_bytes-written)//SOCKET.row_bytes)
    time_slots=max(0,math.floor((deadline-SOCKET.query_timeout_s-next_at)/SOCKET.interval_s)+1)
    slots=min(slots,time_slots)
    last_at=next_at+(slots-1)*SOCKET.interval_s if slots else None
    required=outer_capture_s+stop_s
    if remaining<required+SOCKET.query_timeout_s or last_at is None or last_at<now+required:
        raise ValueError('Insufficient remaining diagnostic coverage through capture AND close')
    if record.get('gui_observation',{}).get('state') in {'EXITED','CONTRADICTORY'}:
        raise ValueError('GUI exit observed')
    return {'monitor_remaining_s':remaining,'socket_schedule_remaining_s':last_at-now,
            'next_observation_monotonic':next_at,'last_programmable_observation_monotonic':last_at,
            'remaining_observations':slots,'capture_budget_s':outer_capture_s,'close_budget_s':stop_s,
            'scheduled_not_observed':True,'last_observed_finished_monotonic':last,
            'movement_authorized':False,'meaning':'CONDITIONAL_SCHEDULE_NOT_COVERAGE_OR_CONSENT'}


class GuiObservation:
    """Passive launch-log evidence only; no lifecycle gate or visual approval."""
    def __init__(self):
        self.value={'state':'UNKNOWN','exit_code':None,'pid':None,'visual_confirmation':'OPERATOR_REQUIRED',
                    'source':'/tmp/tfg_demo.log','observation_kind':'LAUNCH_LOG_NOT_PROCESS_LIVENESS'}
    def feed(self,line):
        text=line.decode('utf-8',errors='replace')
        match=re.search(r"\[([^]]+)\]: process has died \[pid (\d+), exit code (-?\d+), cmd '([^']+)'",text)
        if match and re.search(r'(?:^|\s)(?:/usr/bin/)?gz sim(?:\s|$)',match[4]) and re.search(r'(?:^|\s)(?:-g|--gui)(?:\s|$)',match[4]):
            observed={'state':'EXITED','pid':int(match[2]),'exit_code':int(match[3]),'launch_tag':match[1],
                      'received_monotonic':time.monotonic(),'received_wall_unix_ns':time.time_ns()}
            if self.value['state']=='EXITED' and any(self.value[k]!=observed[k] for k in ('pid','exit_code')):
                self.value.update(state='CONTRADICTORY',exit_code=None)
            elif self.value['state']!='CONTRADICTORY':self.value.update(observed)
    def summary(self):return dict(self.value)


class Drain:
    def __init__(self, output, gui=None, *, status_diagnostic=False):
        if type(status_diagnostic) is not bool:raise ValueError('Explicit Status diagnostic selection required')
        # Same aggregate 2 MiB: the new discovery file consumes a reservation,
        # never extra bytes outside the existing admission calculation.
        self.byte_limit=BYTE_LIMIT-(32768 if status_diagnostic else 0)
        self.gui=gui if gui is not None else GuiObservation()
        self.model_events=[];self.cap_reached=False
        self.output=output;self.pending=b'';self.bytes=0;self.records=0;self.errors=[];self.scanned=0
    def feed(self,data):
        self.scanned+=len(data)
        if self.scanned>SCAN_LIMIT:
            raise ValueError('Diagnostic source scan budget exhausted')
        for piece in data.splitlines(keepends=True):
            self.pending+=piece
            if len(self.pending)>8192:
                self.errors[:]=['Overlong source line; trace coverage unknown'];self.pending=b''
                continue
            if not self.pending.endswith(b'\n'): continue
            line=self.pending;self.pending=b''
            self.gui.feed(line)
            prefix=next((p for p in (b'TFG_XRCE_TRACE ',b'TFG_IDENTITY_TRACE ',b'TFG_MODEL_TRACE ') if p in line),None)
            if prefix is None: continue
            trace=line[line.index(prefix):]
            if self.records>=TRACE_LIMIT or self.bytes+len(trace)>self.byte_limit:
                self.cap_reached=True
                if 'Diagnostic output cap reached' not in self.errors:self.errors.append('Diagnostic output cap reached')
                continue
            # Preserve raw bytes; interpretation remains a separate offline step.
            try:
                row=json.loads(trace.split(prefix,1)[1])
                if row.get('event') in {'status_limit','trace_limit'} or (prefix==b'TFG_MODEL_TRACE ' and row.get('event')=='limit'):
                    self.cap_reached=True
                if prefix==b'TFG_MODEL_TRACE ':
                    if row.get('schema')!='tfg.model-source/1' or row.get('movement_authorized') is not False:raise ValueError('Bad model diagnostic flags')
                    if len(self.model_events)>=32:raise ValueError('Model record budget exhausted')
                    self.model_events.append(row)
                if (self.cap_reached or row.get('incomplete') or row.get('timing_lost') or
                        row.get('lost') or row.get('diagnostic_lost') or
                        row.get('event') in {'trace_limit','trace_error','unbound_writer'}):
                    if 'Native diagnostic reports incomplete coverage' not in self.errors:
                        self.errors.append('Native diagnostic reports incomplete coverage')
            except (ValueError,AttributeError):
                if 'Malformed diagnostic JSON' not in self.errors:self.errors.append('Malformed diagnostic JSON')
            if self.output.write(trace)!=len(trace):raise OSError('Short diagnostic write')
            self.output.flush()
            self.bytes+=len(trace);self.records+=1
    def finish(self):
        prefix=next((p for p in (b'TFG_XRCE_TRACE ',b'TFG_IDENTITY_TRACE ',b'TFG_MODEL_TRACE ') if p in self.pending),None)
        if prefix is not None:
            self.errors.append('Truncated final trace line')
            partial=self.pending[self.pending.index(prefix):]
            if self.records<TRACE_LIMIT and self.bytes+len(partial)<=self.byte_limit:
                if self.output.write(partial)!=len(partial):raise OSError('Short diagnostic tail write')
                self.bytes+=len(partial)
        if not self.records: self.errors.append('No diagnostic records observed')
        self.output.flush();os.fsync(self.output.fileno())


def process(pid,proc=Path('/proc')):
    directory=proc/str(pid)
    fields=(directory/'stat').read_text().rpartition(')')[2].split()
    return {'pid':pid,'ppid':int(fields[1]),'start_ticks':int(fields[19]),
            'boot_id':(proc/'sys/kernel/random/boot_id').read_text().strip(),
            'executable':os.readlink(directory/'exe'),
            'argv':[s.decode(errors='replace') for s in (directory/'cmdline').read_bytes().split(b'\0') if s]}


def agents(proc=Path('/proc'), *, executable='micro_ros_agent'):
    found=[]
    for directory in proc.iterdir():
        if not directory.name.isdigit(): continue
        first=None
        try:
            # Zombies have no usable executable link; an unrelated exiting CLI
            # must not abort draining. Require an observed stable zombie state.
            stat_path=directory/'stat'
            first=stat_path.read_text().rpartition(')')[2].split()
            if first[0]=='Z':
                second=stat_path.read_text().rpartition(')')[2].split()
                if second[0]=='Z' and first[19]==second[19]:continue
                raise ValueError('Process changed while checking zombie state')
            if Path(os.readlink(directory/'exe')).name==executable:
                found.append(process(int(directory.name),proc))
        except (FileNotFoundError,ProcessLookupError): continue
        except PermissionError as exc:
            # exe can become inaccessible AFTER the first stat as a process
            # exits. Only two positive zombie reads of the SAME incarnation
            # resolve that race; disappearance/denial/reuse remain UNKNOWN.
            after=[]
            try:
                for _ in range(2):after.append((directory/'stat').read_text().rpartition(')')[2].split())
                if first and len(first)>19 and all(len(v)>19 and v[0]=='Z' and v[19]==first[19] for v in after):
                    continue
            except (OSError,ValueError,IndexError) as later:
                after.append({'read_error':type(later).__name__})
            found.append({'pid':int(directory.name),'observation_state':'UNKNOWN',
                'reason':type(exc).__name__+': '+str(exc),
                'state_before':{'state':first[0],'start_ticks':first[19]} if first and len(first)>19 else None,
                'states_after_denial':[{'state':v[0],'start_ticks':v[19]} if isinstance(v,list) and len(v)>19 else v for v in after]})
        except (ValueError,IndexError) as exc:
            # UNKNOWN is not absence, nor an invented agent identity. Keep draining
            # and let verification/closure remain incomplete with an explicit reason.
            found.append({'pid':int(directory.name),'observation_state':'UNKNOWN',
                          'reason':type(exc).__name__+': '+str(exc)})
    return found


def launch_candidates(root,proc=Path('/proc')):
    """Only the kernel children of the exact protected launch, never global exe.

    cmdline selects candidates; exe/maps/ancestry are still verified for each
    essential role. Unknown children block; unrelated processes are not read.
    This is OWNED_SUBTREE discovery, not a global uniqueness assertion.
    """
    if root is None or not root_alive(root,proc):return []
    queue=[root['pid']];seen=set();found=[]
    while queue:
        pid=queue.pop()
        if pid in seen:raise ValueError('Protected process ancestry cycle')
        seen.add(pid)
        if len(seen)>512:raise ValueError('Protected process tree bound exceeded')
        directory=proc/str(pid);args=None
        try:
            first=(directory/'stat').read_text().rpartition(')')[2].split()
            if first[0]=='Z':continue
            args=[v.decode(errors='replace') for v in (directory/'cmdline').read_bytes().split(b'\0') if v]
            children=(directory/'task'/str(pid)/'children').read_text().split()
            second=(directory/'stat').read_text().rpartition(')')[2].split()
            if first[19]!=second[19]:raise ValueError('Protected PID recycled during discovery')
            if second[0]=='Z':continue
            queue.extend(int(v) for v in children)
            if args and Path(args[0]).name in {'micro_ros_agent','parameter_bridge'}:
                actual=process(pid,proc)
                if str(actual['start_ticks'])!=first[19] or actual['argv']!=args:raise ValueError('Protected role changed during discovery')
                found.append(actual)
        except (FileNotFoundError,ProcessLookupError):
            # A nonessential child disappeared. Known roles are independently
            # checked on every iteration; never replace an observed incarnation.
            continue
        except (PermissionError,ValueError,IndexError) as exc:
            found.append({'pid':pid,'observation_state':'UNKNOWN','role_hint':Path(args[0]).name if args else None,'reason':type(exc).__name__+': '+str(exc)})
    return found


def role_candidates(candidates,name):
    actual=[p for p in candidates if p.get('observation_state')!='UNKNOWN' and Path(p['executable']).name==name]
    unknown=[p for p in candidates if p.get('observation_state')=='UNKNOWN' and (p.get('role_hint')==name or not actual)]
    return actual+unknown


def descendants(candidate,root,reader=process):
    seen=set();current=candidate
    while current['pid'] not in seen:
        if current['pid']==root['pid']:
            return all(current[k]==root[k] for k in ('pid','start_ticks','boot_id'))
        seen.add(current['pid'])
        if current['ppid']<=1:return False
        current=reader(current['ppid'])
    return False


class ObservationPending(ValueError):
    pass


def root_alive(root,proc=Path('/proc')):
    if root is None:return False
    try:
        # Liveness needs stat/boot only. A zombie has no executable and is not
        # a running protected launch; inaccessible stat is still UNKNOWN/error.
        fields=(proc/str(root['pid'])/'stat').read_text().rpartition(')')[2].split()
        boot=(proc/'sys/kernel/random/boot_id').read_text().strip()
        return fields[0]!='Z' and int(fields[19])==root['start_ticks'] and boot==root['boot_id']
    except (FileNotFoundError,ProcessLookupError):return False


def verify_agent(value,root,candidates,*,maps_reader=None,process_reader=process, verify_files=True):
    unknown=[p for p in candidates if p.get('observation_state')=='UNKNOWN']
    if unknown:raise ValueError('Agent inventory UNKNOWN: '+unknown[0]['reason'])
    if len(candidates)!=1: raise ValueError('Absent or multiple agent processes')
    p=candidates[0]
    prefix=Path(value['prefix'])
    if p['executable']!=str(prefix/'lib/micro_ros_agent/micro_ros_agent') or not descendants(p,root,process_reader):
        raise ValueError('Agent executable/launch ancestry mismatch')
    argv=p['argv']
    def flag(name,value):
        return argv.count(name)==1 and argv.index(name)+1<len(argv) and argv[argv.index(name)+1]==value
    if (len(argv)<2 or argv[1]!='udp4' or not flag('--middleware','dds') or not flag('--port','2019')
            or argv.count('__ns:=/drone1')!=1 or sum(a.startswith('__ns:=') for a in argv)!=1):
        raise ValueError('Agent transport/namespace arguments differ')
    maps=(maps_reader or (lambda pid:Path(f'/proc/{pid}/maps').read_text()))(p['pid'])
    libraries={line.split(None,5)[5] for line in maps.splitlines()
               if len(line.split(None,5))==6 and 'libmicroxrcedds_agent.so' in line.split(None,5)[5]}
    expected=str(prefix/'lib/libmicroxrcedds_agent.so.2.4')
    if not libraries:raise ObservationPending('Native library mapping not available yet')
    if libraries!={expected}: raise ValueError('Native diagnostic library absent/mixed/replaced')
    if verify_files:verify_overlay(value)
    with (prefix/'lib/micro_ros_agent/micro_ros_agent').open('rb') as stream:header=stream.read(6)
    byte_order={1:'little',2:'big'}.get(header[5]) if len(header)==6 and header[:4]==b'\x7fELF' else None
    after=process_reader(p['pid'])
    if any(after[k]!=p[k] for k in ('pid','start_ticks','boot_id','executable','argv')):raise ValueError('Agent changed during verification')
    return {**p,'uniqueness_scope':'PROTECTED_LAUNCH_SUBTREE_ONLY','native_byte_order':byte_order,'mapped_native_library':expected,'library_sha256':value['manifest']['library_sha256']}


def verify_bridge(value,root,candidates,*,maps_reader=None,process_reader=process):
    """Only the explicitly selected /2 overlay; graph names never identify a PID."""
    if any(p.get('observation_state')=='UNKNOWN' for p in candidates):raise ValueError('Bridge process inventory UNKNOWN')
    candidates=[p for p in candidates if '__ns:=/rover1' in p['argv']]
    if len(candidates)!=1:raise ObservationPending('Absent or ambiguous rover bridge')
    p=candidates[0];prefix=Path(value['prefix'])
    if sum(a.startswith('__ns:=') for a in p['argv'])!=1:raise ValueError('Bridge namespace ambiguous')
    if p['executable']!=str(prefix/'lib/ros_gz_bridge/parameter_bridge') or not descendants(p,root,process_reader):
        raise ValueError('Bridge executable/ancestry differs')
    maps=(maps_reader or (lambda pid:Path(f'/proc/{pid}/maps').read_text()))(p['pid'])
    libraries={line.split(None,5)[5] for line in maps.splitlines()
        if len(line.split(None,5))==6 and 'libros_gz_bridge.so' in line.split(None,5)[5]}
    expected=str(prefix/'lib/libros_gz_bridge.so')
    if not libraries:raise ObservationPending('Bridge library not mapped yet')
    if libraries!={expected}:raise ValueError('Bridge library absent/mixed/replaced')
    after=process_reader(p['pid'])
    if any(after[k]!=p[k] for k in ('pid','start_ticks','boot_id','executable','argv')):raise ValueError('Bridge changed during reading')
    return {**p,'mapped_bridge_library':expected,'verified_overlay_library':True,
            'library_sha256':value['manifest']['bridge_library_sha256']}


def verify_model_library(value,root,events,*,process_reader=process,maps_reader=None):
    configured=[e for e in events if e.get('event')=='configured']
    if any(e.get('lifecycle_id')!=value['lifecycle_id'] for e in configured):raise ValueError('Model events belong to another session')
    if not configured:raise ObservationPending('Model source plugin not observed yet')
    identities={(e['pid'],str(e['process_start_ticks']),e['boot_id']) for e in configured}
    if len(identities)!=1:raise ValueError('Multiple Gazebo process contexts')
    entities=[e['model_entity'] for e in configured]
    if len(entities)!=len(set(entities)):raise ValueError('Duplicate ArduPilot plugin instances on entity')
    pid,ticks,boot=identities.pop();p=process_reader(pid)
    if str(p['start_ticks'])!=ticks or p['boot_id']!=boot or not descendants(p,root,process_reader):raise ValueError('Model source process changed/foreign')
    maps=(maps_reader or (lambda n:Path(f'/proc/{n}/maps').read_text()))(pid)
    libraries={line.split(None,5)[5] for line in maps.splitlines() if len(line.split(None,5))==6 and
               any(k in line for k in ('libArduPilotPlugin.so','libTFGArduPilotIdentity.so'))}
    expected=str(Path(value['prefix'])/'lib/libArduPilotPlugin.so')
    if libraries!={expected} or 'libgz-sim8.so.8' not in maps:raise ValueError('Normal/diagnostic model plugin mixed or missing')
    after=process_reader(pid)
    if any(after[k]!=p[k] for k in ('pid','start_ticks','boot_id','argv','executable')):raise ValueError('Model process changed during maps read')
    return {**p,'mapped_model_library':expected,'library_sha256':value['manifest']['model_library_sha256'],
            'verified_overlay_library':True,'entities_observed':entities,'global_uniqueness':'NOT_ASSERTED'}


def managed_closure(prefix,value,request):
    """Read coordination only. Cleanup owns signals; monitor owns observation."""
    path=prefix/'capture/closure-request.json'
    if request is None and path.exists():
        if path.is_symlink() or path.stat().st_uid!=os.getuid():raise ValueError('Unsafe cleanup request')
        request=read_json(path)
        if (request.get('lifecycle_id')!=value['lifecycle_id'] or request.get('selection_sha256')!=value['selection_sha256']
                or request.get('source')!='PROTECTED_PROCESS_CLEANUP'):raise ValueError('Cleanup request scope changed')
    if request is None:return None,None
    path=prefix/'capture/cleanup-finished.json'
    if path.exists():
        if path.is_symlink():raise ValueError('Unsafe cleanup outcome')
        done=read_json(path)
        if any(done.get(k)!=v for k,v in request.items()):raise ValueError('Cleanup request/outcome mismatch')
        if type(done.get('infrastructure_cleanup_complete')) is not bool:raise ValueError('Unknown cleanup outcome')
        return request,done
    if not root_alive(request['cleanup_owner']):raise ValueError('Cleanup owner lost before outcome')
    return request,None


def run(prefix):
    prefix=Path(prefix);value=read_json(prefix/'selection.json')['descriptor'];verify_overlay(value)
    if os.environ.get('TFG_SIM_PROJECT')!='Agentic_Drone_Mission_Control':
        raise ValueError('Monitor lacks project context')
    claim=os.open(prefix/'capture/monitor.claim',os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600);os.close(claim)
    stop=[False]
    for sig in (signal.SIGINT,signal.SIGTERM): signal.signal(sig,lambda *a:stop.__setitem__(0,True))
    started=time.monotonic();deadline=started+DURATION;stop_deadline=None;observed=None;errors=[]
    last_scan=started-1;candidates=[];discovery_unknown=[];bridge=None;model=None;cleanup_request=None;cleanup_result=None;identity_variant=value['manifest']['schema'] in {'tfg.xrce-agent-selection/2','tfg.xrce-agent-selection/3','tfg.xrce-agent-selection/4'};model_variant=value['manifest']['schema'] in {'tfg.xrce-agent-selection/3','tfg.xrce-agent-selection/4'}
    def error(message):
        if message not in errors and len(errors)<32:errors.append(message)
    source=SOURCE;original=source.stat();root=None
    sockets=SocketRecorder(prefix,value)
    gui=GuiObservation()
    status_diagnostic=value['manifest']['schema']=='tfg.xrce-agent-selection/4'
    state={'capture_semantics':'SEPARATE_CHANNELS_V2','cleanup_protocol':'DEFERRED_OBSERVER_SHUTDOWN_V1','kind':'PASSIVE_DIAGNOSTIC_MONITOR','lifecycle_id':value['lifecycle_id'],
           'monitor':process(os.getpid()),'phase':'WAITING','trace_path':str(prefix/'capture/trace.log'),
           'source_path':str(source),'started_monotonic':started,'source_generation_time':'UNKNOWN',
           'duration_limit_s':DURATION,'byte_limit':BYTE_LIMIT,'record_limit':TRACE_LIMIT,
           'trace_byte_limit':BYTE_LIMIT-(32768 if status_diagnostic else 0),
           'status_discovery_byte_reservation':32768 if status_diagnostic else 0}
    cap_reached=[False]
    def record(**fields):
        atomic_record(prefix/'capture/monitor.json',{**state,**fields,'errors':list(errors),
            'observation_monotonic':time.monotonic(),'observation_wall_unix_ns':time.time_ns(),
            'socket_inventory':sockets.summary(),'gui_observation':gui.summary(),
            'identity_bridge':bridge,'model_source':model,'global_executable_uniqueness':'NOT_ASSERTED',
            'diagnostic_cap_reached':cap_reached[0],
            'cleanup_request':cleanup_request,'cleanup_result':cleanup_result,
            'supervision_scope':'EXACT_LAUNCH_DESCENDANTS_AND_KNOWN_IDENTITIES','discovery_uncertainties':discovery_unknown})
    record()
    with source.open('rb') as stream, (prefix/'capture/trace.log').open('xb') as output:
        os.chmod(prefix/'capture/trace.log',0o600);drain=Drain(output,gui,status_diagnostic=status_diagnostic)
        while time.monotonic()<deadline:
            now=time.monotonic()
            cleanup_request,cleanup_result=managed_closure(prefix,value,cleanup_request)
            if cleanup_request:
                stop[0]=True
                if cleanup_request.get('observer_errors'):error('Diagnostic observer context incomplete at cleanup')
            if stop[0] and stop_deadline is None and not cleanup_request: stop_deadline=now+10
            chunk=stream.read(65536)
            if chunk: drain.feed(chunk)
            cap_reached[0]=drain.cap_reached
            for message in drain.errors:error(message)
            current=source.stat()
            if (current.st_dev,current.st_ino)!=(original.st_dev,original.st_ino) or current.st_size<stream.tell():
                raise ValueError('Source log replaced/truncated during diagnostic capture')
            if root is None:
                if (prefix/'launch.json').exists():root=read_json(prefix/'launch.json')['process']
                elif now-started>8:raise ValueError('Protected launch identity unavailable')
            sockets.sample(root,observed,now,model,drain.model_events)
            if cleanup_result and not chunk:
                if not cleanup_result['infrastructure_cleanup_complete']:error('Protected infrastructure cleanup incomplete')
                break
            if now-last_scan<1:
                if stop_deadline and now>=stop_deadline:break
                time.sleep(.1);continue
            last_scan=now
            if observed and (not identity_variant or bridge):
                owned=[]
                for known in (observed,bridge):
                    if known is None:continue
                    try:owned.append(process(known['pid']))
                    except (FileNotFoundError,ProcessLookupError):pass
                    except OSError as exc:owned.append({'pid':known['pid'],'role_hint':Path(known['executable']).name,'observation_state':'UNKNOWN','reason':type(exc).__name__})
            else:owned=launch_candidates(root)
            discovery_unknown[:]=[p for p in owned if p.get('observation_state')=='UNKNOWN']
            candidates=role_candidates(owned,"micro_ros_agent")
            if candidates:
                try:
                    if stop[0] and observed:
                        # Expected reparenting after launch exit cannot recreate
                        # ancestry. Continue checking the pinned incarnation;
                        # never adopt a replacement or ignore denied observation.
                        if len(candidates)!=1 or any(candidates[0].get(k)!=observed[k] for k in ('pid','start_ticks','boot_id','argv','executable')):
                            raise ValueError('Agent identity changed/unknown during closure')
                        p=None
                    else:p=verify_agent(value,root,candidates,verify_files=observed is None,process_reader=process) if root else None
                    if p:
                        if observed and any(p[k]!=observed[k] for k in ('pid','start_ticks','boot_id')):
                            raise ValueError('Agent was replaced/restarted')
                        observed=p
                except ObservationPending as exc:
                    if observed is not None or now-started>8:error(str(exc))
                except ValueError as exc:
                    error(str(exc))
                    record(phase='FAILED',agent=observed)
                    # Do not restart/kill controls or change gates. Keep draining.
            elif observed is not None and not stop[0]:
                error('Agent disappeared without requested lifecycle closure')
            if now-started>8 and observed is None and not stop[0]:
                error('Diagnostic agent identity not confirmed at startup')
                record(phase='FAILED',agent=observed)
            if identity_variant and root and not stop[0]:
                try:
                    current_bridge=verify_bridge(value,root,role_candidates(owned,'parameter_bridge'),process_reader=process)
                    if bridge and any(current_bridge[k]!=bridge[k] for k in ('pid','start_ticks','boot_id')):
                        raise ValueError('Bridge replaced/restarted')
                    bridge=current_bridge
                except ObservationPending as exc:
                    if bridge is not None or now-started>8:
                        error(str(exc));record(phase='FAILED',agent=observed)
                except (ValueError,OSError) as exc:
                    error('Identity bridge observation: '+str(exc));record(phase='FAILED',agent=observed)
            if model_variant and root and not stop[0]:
                try:
                    current_model=verify_model_library(value,root,drain.model_events,process_reader=process)
                    if model and any(current_model[k]!=model[k] for k in ('pid','start_ticks','boot_id')):raise ValueError('Model server restarted')
                    model=current_model
                except ObservationPending as exc:
                    if model or now-started>8:error(str(exc))
                except (ValueError,OSError) as exc:error(str(exc))
            if errors:record(phase='FAILED',agent=observed)
            if stop_deadline and (now>=stop_deadline or (not candidates and not root_alive(root) and not (model and root_alive(model)) and not chunk)):break
            if not errors:record(phase='OBSERVING' if observed and (not identity_variant or bridge) and (not model_variant or model) else 'WAITING',agent=observed)
            time.sleep(.1)
        if time.monotonic()>=deadline:errors.append('Diagnostic wall-time budget exhausted')
        sockets.close()
        drain.finish();verify_overlay(value)
        errors.extend(drain.errors[:32])
        if observed and root_alive(observed):errors.append('Known agent exit not observed by monitor')
        if model and root_alive(model):errors.append('Model server exit not observed by monitor')
        if root_alive(root):errors.append('Protected launch exit not observed by monitor')
        if observed is None:errors.append('No diagnostic agent identity was observed')
        socket_state=sockets.summary()
        sockets_complete=bool(socket_state.get('snapshots')) and not any(socket_state.get(k) for k in ('error','peer_waiting','incomplete_snapshots'))
        core_complete=not errors and stop[0]
        record(phase='CLOSED' if core_complete else 'INCOMPLETE',agent=observed,
               trace_records=drain.records,trace_bytes=drain.bytes,scanned_bytes=drain.scanned,
               closure_requested=stop[0],finished_monotonic=time.monotonic(),
               core_capture_complete=core_complete,socket_capture_complete=sockets_complete,
               capture_complete=bool(core_complete and sockets_complete))
    return 0 if core_complete and sockets_complete else 1


def supervise(prefix, *, popen=None, process_reader=process, persist=atomic_record):
    """Retain the actual monitor Popen wait handle beyond startup.

    No agent is started here. Signals from protected lifecycle shutdown are
    forwarded only to this exact child; wait/persistence failure stays uncertain.
    Existing 600 s capture budget is unchanged, no restart and no forced cleanup.
    """
    prefix=Path(prefix);child=None;identity=None;observed_rc=None
    receipt=prefix/'capture/monitor_supervisor.json'
    handlers={}
    try:
        value=read_json(prefix/'selection.json')['descriptor'];verify_overlay(value)
        try:
            fd=os.open(prefix/'capture/monitor_supervisor.claim',os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
        except FileExistsError:
            return 1  # never restart a consumed overlay or rewrite its receipts
        os.close(fd)
        child=(popen or subprocess.Popen)([sys.executable,str(prefix/'monitor.py'),'--observe-child',str(prefix)],
            stdin=subprocess.DEVNULL)  # inherit project context and retained supervisor log
        identity=process_reader(child.pid)
        if identity is None:raise ValueError('Monitor child identity unavailable')
        def forward(signum,frame):
            try:current=process_reader(child.pid)
            except FileNotFoundError:return
            if current and all(current[k]==identity[k] for k in ('pid','start_ticks','boot_id')):
                child.send_signal(signum)
        for sig in (signal.SIGINT,signal.SIGTERM):
            handlers[sig]=signal.signal(sig,forward)
        persist(receipt,{'phase':'WAITING_CHILD','child':identity,'supervisor':process_reader(os.getpid())})
        rc=child.wait(timeout=DURATION)
        if type(rc) is not int:raise ValueError('No actual monitor child return code')
        observed_rc=rc
        persist(prefix/'capture/monitor_exit.json',{'state':'PARENT_WAIT_STATUS_OBSERVED',
            'return_code':rc,'pid':identity['pid'],'start_ticks':identity['start_ticks'],
            'boot_id':identity['boot_id'],'observed_monotonic':time.monotonic(),
            'observed_at_utc':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()),
            'source':'RETAINED_MONITOR_PARENT_POPEN_WAIT'})
        persist(receipt,{'phase':'CHILD_REAPED','child':identity,'return_code':rc})
        return rc
    except Exception as exc:
        # Never infer a return code from CLOSED, absence, or a failed wait/write.
        persist(receipt,{'phase':'UNCERTAIN','child':identity,'return_code':observed_rc,
                         'error_class':type(exc).__name__})
        return 1
    finally:
        for sig,handler in handlers.items():signal.signal(sig,handler)


def main(argv=None):
    args=sys.argv[1:] if argv is None else argv
    if len(args)==2 and args[0]=='--supervise':return supervise(args[1])
    if len(args)==2 and args[0]=='--observe-child':args=args[1:]
    try:
        return run(args[0])
    except Exception as exc:
        path=Path(args[0])/'capture/monitor.json'
        try:previous=read_json(path)
        except (OSError,ValueError):previous={}
        atomic_record(path,{**previous,'phase':'FAILED','capture_complete':False,
                            'error':f'{type(exc).__name__}: {exc}'})
        return 1


if __name__=='__main__':
    raise SystemExit(main())
