"""Bounded local C++ observation pipe, consumed by the existing ROS adapter.

No ROS import, graph attribution, control publisher or automatic process start.
The original receiver clock is accepted only in the same proc/boot/namespaces.
Receiving/validating metadata never accredits its physical source for movement.
"""
import hashlib
import json
import os
from pathlib import Path
import selectors
import subprocess
import time
from uuid import UUID

from tools.vehicle_execution_lock import process_identity
from tools.rover_control import RoverControlError, number

SCHEMA = 'tfg.rover-observation-stream/1'
TOPICS = {'/ap/v3/status': 'status', '/rover1/odometry': 'odometry'}
MAX_BYTES, MAX_LINE, MAX_RECORDS = 448*1024, 64*1024, 128
# Admission budget, not a measured bound on discovery or publication latency.
# Existing 1 s availability quantum + native RPC response (2 s) + scene Request
# (1 s) + seven bounded writes: header/ack/two samples/request/reply/catalog.
BOOTSTRAP_CONTRACT = {
    'schema':'tfg.stationary-bootstrap/1','initial_availability_s':1.,
    'rpc_response_s':2.,'scene_request_s':1.,'record_write_s':.25,
    'records':7,'total_s':5.75,'new_pair_timeout_s':1.,
    'credits':'B1_METADATA_I1_W2_S2_D2','bootstrap_pair_is_live_observation':False,
}


def process_context(pid):
    identity=process_identity(pid)
    if identity is None:raise RoverControlError('Receiver process absent')
    executable=Path(f'/proc/{pid}/exe');stat=executable.stat()
    return {**identity,'executable':os.readlink(executable),'exe_inode':stat.st_ino,'exe_device':stat.st_dev,
            **{k+'_namespace':os.readlink(f'/proc/{pid}/ns/{k}') for k in ('net','pid','time')}}


class PipeFrames:
    """Only its explicitly owned child. No shell, retries, reconnect or signals."""
    def __init__(self, child, sink=lambda raw:None):
        self.child=child;self.buffer=b'';self.bytes=0;self.sink=sink;self.stderr=b'';self.observed_return_code=None
        self.selector=selectors.DefaultSelector()
        os.set_blocking(child.stdout.fileno(),False)
        self.selector.register(child.stdout,selectors.EVENT_READ)

    def ready(self,timeout_s=0.):
        return b'\n' in self.buffer or bool(self.selector.select(timeout_s))

    def read(self,timeout_s):
        deadline=time.monotonic()+number(timeout_s,'pipe timeout',positive=True)
        while True:
            if b'\n' in self.buffer:
                line,self.buffer=self.buffer.split(b'\n',1)
                if len(line)>MAX_LINE:raise RoverControlError('Receiver record budget')
                self.sink(line+b'\n')
                return line
            if len(self.buffer)>MAX_LINE:raise RoverControlError('Receiver truncated/oversized record')
            remaining=deadline-time.monotonic()
            if remaining<=0 or not self.selector.select(remaining):raise TimeoutError('Receiver transfer deadline')
            chunk=os.read(self.child.stdout.fileno(),4096)
            if not chunk:
                if self.buffer:self.sink(self.buffer);self.buffer=b''
                raise RoverControlError('Receiver disconnected/truncated before footer')
            self.bytes+=len(chunk)
            if self.bytes>MAX_BYTES:raise RoverControlError('Receiver aggregate budget')
            self.buffer+=chunk

    def grant(self,phase,timeout_s):
        if phase not in 'BIPWSD' or len(phase)!=1:raise RoverControlError('Invalid local retention credit')
        fd=self.child.stdin.fileno();os.set_blocking(fd,False)
        with selectors.DefaultSelector() as poll:
            poll.register(fd,selectors.EVENT_WRITE)
            if not poll.select(timeout_s) or os.write(fd,phase.encode('ascii'))!=1:
                raise RoverControlError('Receiver credit request uncertain; no replay')

    def request_close(self,timeout_s):
        fd=self.child.stdin.fileno();os.set_blocking(fd,False)
        with selectors.DefaultSelector() as poll:
            poll.register(fd,selectors.EVENT_WRITE)
            if not poll.select(timeout_s) or os.write(fd,b'C')!=1:
                raise RoverControlError('Receiver close request uncertain')

    def ended(self):
        self.observed_return_code=self.child.poll()
        if self.observed_return_code is None:return False
        # EOF failures make ObservationStream permanently reject further rows.
        # Drain this already-reaped child's bounded stderr here: close() may
        # consequently never reach its successful-footer wait path.
        self.wait(0)
        return True

    def wait(self,timeout_s):
        rc=self.child.wait(timeout=timeout_s)
        self.observed_return_code=rc
        if self.child.stderr is not None:
            os.set_blocking(self.child.stderr.fileno(),False)
            self.stderr+=os.read(self.child.stderr.fileno(),4097-len(self.stderr))
            if len(self.stderr)>4096:raise RoverControlError('Receiver stderr budget')
        return rc

    def drain_failed(self,timeout_s):
        """Preserve raw terminal output only; never validate it as observations.

        A sticky source failure cannot call _next(), but the same owned child
        may still emit its footer after C. Drain both pipes within the caller's
        existing close deadline and byte bounds, without restarting that clock.
        """
        deadline=time.monotonic()+number(timeout_s,'failed pipe drain timeout',positive=True)
        if self.buffer:
            self.sink(self.buffer);self.buffer=b''
        with selectors.DefaultSelector() as poll:
            for pipe,kind in ((self.child.stdout,'stdout'),(self.child.stderr,'stderr')):
                if pipe is not None:
                    os.set_blocking(pipe.fileno(),False)
                    poll.register(pipe,selectors.EVENT_READ,kind)
            while poll.get_map():
                remaining=deadline-time.monotonic()
                if remaining<=0:raise TimeoutError('Receiver failed drain deadline')
                for key,_ in poll.select(remaining):
                    raw=os.read(key.fileobj.fileno(),4096)
                    if not raw:
                        poll.unregister(key.fileobj);continue
                    if key.data=='stdout':
                        self.bytes+=len(raw)
                        if self.bytes>MAX_BYTES:raise RoverControlError('Receiver aggregate budget')
                        self.sink(raw)
                    else:
                        self.stderr+=raw
                        if len(self.stderr)>4096:raise RoverControlError('Receiver stderr budget')
        self.observed_return_code=self.child.wait(timeout=max(0,deadline-time.monotonic()))
        return self.observed_return_code

    def release(self):
        self.selector.close();self.child.stdout.close();self.child.stdin.close()
        if getattr(self.child,'stderr',None) is not None:self.child.stderr.close()


class ObservationStream:
    def __init__(self,frames,*,session_id,identity,read_context=process_context,clock=time,
                 max_age_s, journal=lambda event:None, selection_mode="DIAGNOSTIC_SPACING_V1"):
        if str(UUID(session_id))!=session_id:raise RoverControlError('Canonical receiver session required')
        self.frames,self.session_id,self.identity=frames,session_id,dict(identity)
        self.read_context,self.clock,self.journal=read_context,clock,journal
        self.max_age=number(max_age_s,'original sample maximum age',positive=True)
        self.header=None;self.latest={};self.stamps={};self.gids={};self.counts={k:0 for k in TOPICS}
        self.sequence=0;self.failed=None;self.footer=None;self.closed=False;self.rpc=[]
        self.close_attempted=False;self.close_result=None;self.footer_sha256=None;self.catalog=None
        self.preparation=None
        self.metadata_prepared_monotonic_s=None
        self.reserved_pairs=0
        if selection_mode not in ('DIAGNOSTIC_SPACING_V1','CREDIT_PHASED_V1'):raise RoverControlError('Unknown receiver selection')
        self.selection_mode=selection_mode;self.phase='B';self.credits=[];self.paired={}


    def _live(self):
        actual=self.read_context(self.identity['pid'])
        own=self.read_context(os.getpid())
        if actual!=self.identity or any(actual[k]!=own[k] for k in ('boot_id','net_namespace','pid_namespace','time_namespace')):
            raise RoverControlError('Receiver incarnation/clock namespace changed or incomparable')

    def _next(self,timeout_s,*,closing=False):
        if self.failed:raise RoverControlError('Receiver permanently rejected: '+self.failed)
        try:
            if not closing:self._live()
            raw=self.frames.read(timeout_s)
            def pairs(items):
                result={}
                for key,value in items:
                    if key in result:raise ValueError('Duplicate receiver field')
                    result[key]=value
                return result
            row=json.loads(raw,object_pairs_hook=pairs,parse_constant=lambda v:(_ for _ in ()).throw(ValueError('Nonfinite receiver JSON')))
            if (row.get('schema')!=SCHEMA or row.get('session_id')!=self.session_id
                    or row.get('sequence')!=self.sequence+1 or row.get('movement_authorized') is not False
                    or row.get('identity_verified') is not False or row.get('client_process')!=self.identity or self.sequence>=MAX_RECORDS):
                raise RoverControlError('Receiver schema/session/sequence/authority changed')
            if self.header is None:
                if (row.get('event')!='header' or row.get('process')!=self.identity or row.get('max_samples')!=20 or row.get('duration_s')!=120
                        or row.get('clock_scope')!='SAME_PROC_BOOT_AND_MONOTONIC'):
                    raise RoverControlError('Receiver header identity/bounds differ')
                if self.selection_mode=='CREDIT_PHASED_V1' and (row.get('selection_mode')!=self.selection_mode or row.get('spacing_source_ns')!=0):
                    raise RoverControlError('Receiver phased selection differs')
                if self.selection_mode=='DIAGNOSTIC_SPACING_V1' and row.get('selection_mode','DIAGNOSTIC_SPACING_V1')!=self.selection_mode:
                    raise RoverControlError('Receiver diagnostic selection differs')
                self.header=row
            elif row.get('event')=='sample':
                topic=row['topic'];kind=TOPICS[topic];sample=row['sample'];receipt=sample['receipt']['steady_ns']/1e9
                transfer=self.clock.monotonic()
                if (sample.get('incomplete') is not False or sample.get('from_intra_process') is not False
                        or sample.get('topic')!=topic or sample.get('message_gid_state')!='OBSERVED_NOT_ACCREDITED'):
                    raise RoverControlError('Receiver reports incomplete sample metadata')
                gid=sample['message_publisher_gid']
                if (not isinstance(gid,str) or len(gid)!=48 or any(c not in '0123456789abcdef' for c in gid) or not int(gid,16)
                        or sample.get('rmw_implementation_identifier')!='rmw_fastrtps_cpp'):
                    raise RoverControlError('Per-message publisher GID/RMW absent')
                if self.gids.get(kind,gid)!=gid:raise RoverControlError('Sample publisher changed')
                if not 0<=transfer-receipt<=self.max_age:raise RoverControlError('Original receiver receipt stale/future; transfer is not freshness')
                stamp=sample['header']['stamp'];sec,nano=stamp['sec'],stamp['nanosec']
                if type(sec) is not int or type(nano) is not int or sec<0 or not 0<=nano<10**9:raise RoverControlError('Invalid original stamp')
                stamp=sec*10**9+nano
                if kind in self.stamps and (stamp<=self.stamps[kind] or receipt<=self.latest[kind]['receipt']):
                    raise RoverControlError('Repeated/rewound source or receiver time')
                if self.counts[topic]>=10:raise RoverControlError('Per-stream sample quota exceeded')
                if self.selection_mode=='CREDIT_PHASED_V1':
                    credit=row.get('selection_credit')
                    if type(credit) is not int or not 1<=credit<=len(self.credits):raise RoverControlError('Unrequested receiver sample credit')
                    issued=self.credits[credit-1]
                    if (not issued['ack'] or row.get('selection_phase')!=issued['phase'] or topic in issued['seen']
                            or receipt<issued['requested_monotonic_s']):raise RoverControlError('Receiver sample credit/phase contradicts request')
                    if issued['phase'] in 'BIPW' and self.counts[topic]>=4:raise RoverControlError('Receiver consumed reserved confirmation quota')
                    issued['seen'].add(topic)
                body=row['body']
                if body['header']!=sample['header']:raise RoverControlError('Adaptation changed original header')
                if kind=='status':
                    if (type(body.get('vehicle_type')) is not int or body['vehicle_type']!=1 or type(body.get('mode')) is not int
                            or not 0<=body['mode']<=255 or any(type(body.get(k)) is not bool for k in ('armed','flying','external_control'))
                            or not isinstance(body.get('failsafe'),list) or any(type(v) is not int or not 0<=v<=255 for v in body['failsafe'])):
                        raise RoverControlError('Incomplete Rover Status payload')
                else:
                    if body.get('child_frame_id')!=sample['child_frame_id'] or body['child_frame_id']!='base_link' or not body['header']['frame_id']:
                        raise RoverControlError('Odometry frame mismatch')
                    for branch in ('pose','twist'):
                        if len(body[branch]['covariance'])!=36:raise RoverControlError('Covariance missing')
                        for value in body[branch]['covariance']:number(value,'covariance')
                    vectors=(body['pose']['pose']['position'],body['pose']['pose']['orientation'],body['twist']['twist']['linear'],body['twist']['twist']['angular'])
                    for vector,keys in zip(vectors,('xyz','xyzw','xyz','xyz')):
                        if not isinstance(vector,dict) or set(vector)!=set(keys):raise RoverControlError('Incomplete odometry vector')
                        for value in vector.values():number(value,'received odometry')
                self.latest[kind]={'body':body,'gid':gid,'receipt':receipt,'transfer':transfer,
                    'source_stamp_ns':stamp,'source':'rclcpp MessageInfo callback via owned local pipe',
                    'sample_sha256':hashlib.sha256(raw).hexdigest(),'raw_sample':sample,'raw_record':raw.decode()}
                self.gids[kind]=gid;self.stamps[kind]=stamp;self.counts[topic]+=1
                if self.selection_mode=='CREDIT_PHASED_V1' and len(issued['seen'])==2:self.paired=dict(self.latest)
            elif row.get('event')=='selection_credit':
                credit=row.get('credit')
                if self.selection_mode!='CREDIT_PHASED_V1' or type(credit) is not int or not 1<=credit<=len(self.credits):
                    raise RoverControlError('Unrequested receiver credit acknowledgement')
                issued=self.credits[credit-1]
                if issued['ack'] or row.get('phase')!=issued['phase']:raise RoverControlError('Receiver credit association differs')
                issued['ack']=True
            elif row.get('event') in {'rpc_request' ,'rpc_reply','rpc_timeout'}:
                if self.metadata_prepared_monotonic_s is not None:
                    raise RoverControlError('Bootstrap RPC repeated after preparation')
                if len(self.rpc)>=3:raise RoverControlError('RPC metadata quota exceeded')
                self.rpc.append(row)
            elif row.get('event')=='scene_catalog':
                if self.metadata_prepared_monotonic_s is not None:
                    raise RoverControlError('Bootstrap catalog repeated after preparation')
                if self.catalog is not None:raise RoverControlError('Duplicate scene catalog')
                self.catalog=row
            elif row.get('event')=='footer':
                if row.get('reader_closed') is not True or row.get('counts')!=self.counts:
                    raise RoverControlError('Receiver footer/coverage contradictory')
                self.footer=row
                self.footer_sha256=hashlib.sha256(raw+b'\n').hexdigest()
            else:raise RoverControlError('Unexpected receiver event or restart')
            if self.footer is None and not closing:self._live()
            self.sequence+=1
            self.journal({'operation':'receiver_record','valid':True,'record':row,
                'transfer_received_monotonic_s':self.clock.monotonic(),'valid_for_live_observation':not closing,'source_identity_verified':False})
            return row
        except Exception as exc:
            self.failed=type(exc).__name__+':'+str(exc)
            diagnostic={}
            if self.preparation is not None:
                diagnostic['source_preparation']={**self.preparation,'failure_monotonic_s':self.clock.monotonic(),
                    'pending_events':(['header'] if self.header is None else [])+
                        [k for k in ('status','odometry') if k not in self.latest or
                            self.preparation.get('phase')=='POST_BOOTSTRAP_PAIR' and
                            self.latest[k]['receipt']<=self.metadata_prepared_monotonic_s]+
                        [k for k in ('rpc_request','rpc_reply') if not any(r['event']==k for r in self.rpc)]+
                        ([] if self.catalog else ['scene_catalog'])}
            self.journal({'operation':'receiver_record','valid':False,'reason':self.failed,**diagnostic})
            raise

    def set_phase(self,phase):
        if phase not in ('B','I','P','W','S','D'):raise RoverControlError('Unknown receiver phase')
        if 'BIPWSD'.index(phase)<'BIPWSD'.index(self.phase):raise RoverControlError('Receiver phase rewind')
        self.phase=phase

    def _grant(self,timeout_s):
        if self.selection_mode!='CREDIT_PHASED_V1':return None
        if self.failed or self.closed or self.footer:raise RoverControlError('Receiver credit no longer live')
        self._live()
        if self.credits and self.credits[-1]['phase']==self.phase and len(self.credits[-1]['seen'])<2:
            return len(self.credits)
        if self.phase in 'BIPW' and min(10-v for v in self.counts.values())<=6:
            raise RoverControlError('PULSE_QUOTA_RESERVED_FOR_STOP')
        cap=1 if self.phase=='B' else 2 if self.phase=='I' else 4 if self.phase in 'PW' else 3
        if sum(c['phase']==self.phase for c in self.credits)>=cap or max(self.counts.values())>=10:
            raise RoverControlError('Receiver phase quota exhausted')
        # Record before write: uncertainty never causes credit replay.
        self.credits.append({'phase':self.phase,'ack':False,'seen':set(),'requested_monotonic_s':self.clock.monotonic()})
        try:self.frames.grant(self.phase,timeout_s)
        except Exception as exc:
            self.failed='CREDIT_REQUEST_UNCERTAIN:'+type(exc).__name__;raise
        return len(self.credits)

    def observe(self,*,timeout_s):
        if self.closed:raise RoverControlError('Receiver closed; no resume')
        start=self.clock.monotonic();deadline=start+number(timeout_s,'observation timeout',positive=True)
        credit=self._grant(timeout_s)
        while self.clock.monotonic()<deadline:
            self._next(deadline-self.clock.monotonic())
            if self.footer:raise RoverControlError('Receiver ended before fresh observation pair')
            credited=(credit is None or len(self.credits[credit-1]['seen'])==2)
            if credited and all(k in self.latest and self.latest[k]['receipt']>=start for k in ('status','odometry')):
                value={'sample_provenance':dict(self.latest),'sample_gid_source':'RCLCPP_MESSAGE_INFO_PER_SAMPLE'}
                for key in ('status','odometry'):
                    sample=self.latest[key]
                    if self.clock.monotonic()-sample['receipt']>self.max_age:raise RoverControlError('Pair aged during transfer')
                    value.update({key:sample['body'],key+'_publisher_gid':sample['gid'],key+'_received_monotonic_s':sample['receipt']})
                return value
        raise TimeoutError('Receiver fresh pair timeout')

    def poll(self,*,timeout_s):
        """Bounded watch of existing pipe/cache; never renew original receipts."""
        if self.closed or self.footer or self.failed:raise RoverControlError('Receiver observation no longer live')
        self._live();deadline=self.clock.monotonic()+number(timeout_s,'watch timeout',positive=True)
        if self.selection_mode=='CREDIT_PHASED_V1' and min(10-v for v in self.counts.values())>6:self._grant(timeout_s)
        ready=getattr(self.frames,'ready',None)
        if ready is None:raise RoverControlError('Receiver pipe readiness unavailable')
        for _ in range(MAX_RECORDS):
            remaining=deadline-self.clock.monotonic()
            if remaining<=0 or not ready(0):break
            if self.selection_mode!='CREDIT_PHASED_V1' and self.reserved_pairs and min(10-v for v in self.counts.values())<=self.reserved_pairs:
                raise RoverControlError('PULSE_QUOTA_RESERVED_FOR_STOP')
            self._next(remaining)
            if self.footer:raise RoverControlError('Receiver ended during pulse watch')
        return self.current()

    def reserve_observations(self,pairs):
        if type(pairs) is not int or not 0<=pairs<=10:raise RoverControlError('Invalid stop observation reservation')
        if self.probe(timeout_s=self.max_age)['remaining_sample_pairs']<pairs:raise RoverControlError('Stop observation quota unavailable')
        self.reserved_pairs=pairs

    def probe(self,*,timeout_s):
        if not self.latest:self.observe(timeout_s=timeout_s)
        if self.metadata_prepared_monotonic_s is not None:self.current()
        self._live()
        if any(not 0<=self.clock.monotonic()-s['receipt']<=self.max_age for s in self.latest.values()):
            raise RoverControlError('Receiver probe samples stale')
        if self.selection_mode=='CREDIT_PHASED_V1' and self.phase=='B':self.set_phase('I')
        return {'selection_mode':self.selection_mode,'session_id':self.session_id,'status_sample_gid':self.gids['status'],
                'odometry_sample_gid':self.gids['odometry'],'metadata_source':'RCLCPP_MESSAGE_INFO_PER_SAMPLE',
                'source_identity_verified':False,'max_samples':20,'duration_s':120,
                'remaining_sample_pairs':min(10-v for v in self.counts.values()),
                'quota_basis':('CREDIT_BOUNDED_RETENTION_NOT_GUARANTEED_PUBLICATION' if self.selection_mode=='CREDIT_PHASED_V1' else 'UNCONSUMED_BY_ADAPTER_NOT_GUARANTEED_FUTURE_RECEPTIONS')}

    def current(self):
        """Validate the existing pair without consuming or refreshing it."""
        if self.failed or self.closed or self.footer:raise RoverControlError('Receiver is not a live source')
        self._live()
        samples=self.paired if self.selection_mode=='CREDIT_PHASED_V1' else self.latest
        if set(samples)!={'status','odometry'}:raise RoverControlError('Receiver pair absent')
        if self.metadata_prepared_monotonic_s is not None and any(
                s['receipt']<=self.metadata_prepared_monotonic_s for s in samples.values()):
            raise RoverControlError('New observation pair required after metadata preparation')
        value={'sample_provenance':dict(samples),'sample_gid_source':'RCLCPP_MESSAGE_INFO_PER_SAMPLE'}
        for kind,sample in samples.items():
            if not 0<=self.clock.monotonic()-sample['receipt']<=self.max_age:raise RoverControlError('Receiver current sample stale/future')
            value.update({kind:sample['body'],kind+'_publisher_gid':sample['gid'],kind+'_received_monotonic_s':sample['receipt']})
        return value

    def prepare_metadata(self,*,timeout_s):
        """B1 only: bounded metadata preparation, never a current observation.

        Each transferred B sample still passes the normal age/identity checks.
        Waiting for RPC/catalog may age that pair: it cannot be reused by
        current(), probe() or watch after the completion barrier below.
        """
        if (self.selection_mode!='CREDIT_PHASED_V1' or self.phase!='B'
                or self.metadata_prepared_monotonic_s is not None):
            raise RoverControlError('Metadata preparation requires initial phased source')
        started=self.clock.monotonic();deadline=started+number(timeout_s,'metadata preparation timeout',positive=True)
        self.preparation={'phase':'BOOTSTRAP_METADATA','started_monotonic_s':started,'deadline_monotonic_s':deadline}
        self._grant(number(deadline-self.clock.monotonic(),'metadata credit remaining',positive=True))
        while not (set(self.paired)=={'status','odometry'} and self.catalog and len(self.rpc)==2):
            self._next(number(deadline-self.clock.monotonic(),'metadata preparation remaining',positive=True))
            if self.footer or any(r['event']=='rpc_timeout' for r in self.rpc):
                raise RoverControlError('Receiver identity metadata incomplete')
        if (self.header.get('spacing_source_ns')!=0 or self.header.get('after_status') is not True
                or [r['event'] for r in self.rpc]!=['rpc_request','rpc_reply']
                or self.rpc[0].get('accepted') is not True or self.catalog.get('received') is not True):
            raise RoverControlError('Bootstrap metadata incomplete/contradictory')
        self._live()
        finished=self.clock.monotonic()
        if finished>=deadline:raise TimeoutError('Receiver metadata preparation deadline')
        self.metadata_prepared_monotonic_s=finished;self.preparation=None;self.set_phase('I')
        return {'phase':'BOOTSTRAP_METADATA','started_monotonic_s':started,'deadline_monotonic_s':deadline,
            'finished_monotonic_s':finished,'counts':dict(self.counts),'observations_qualified':False,
            'rpc_and_catalog_complete':True,'receiver_context_revalidated':True,
            'source_identity_verified':False,'movement_authorized':False}

    def acquire_after_preparation(self,*,timeout_s):
        """I1: new callbacks strictly after metadata and its context recheck."""
        if self.metadata_prepared_monotonic_s is None or self.phase!='I':
            raise RoverControlError('Metadata preparation barrier absent')
        started=self.clock.monotonic();deadline=started+number(timeout_s,'new observation timeout',positive=True)
        self.preparation={'phase':'POST_BOOTSTRAP_PAIR','started_monotonic_s':started,'deadline_monotonic_s':deadline}
        self._live()
        value=self.observe(timeout_s=number(deadline-self.clock.monotonic(),'new observation remaining',positive=True))
        # observe enforces new credit, stamp/receipt progression and current age;
        # current additionally fences both receipts against metadata completion.
        self.current()
        if abs(value['status_received_monotonic_s']-value['odometry_received_monotonic_s'])>self.max_age:
            raise RoverControlError('Post-preparation channel receipts incoherent')
        if self.clock.monotonic()>=deadline:raise TimeoutError('Receiver new observation deadline')
        self.preparation=None
        return value

    def prepare_identity(self,*,timeout_s):
        """Same bounded pipe, including RPC/catalog, before control admission."""
        started=self.clock.monotonic()
        deadline=started+number(timeout_s,'source preparation timeout',positive=True)
        self.preparation={'started_monotonic_s':started,'deadline_monotonic_s':deadline}
        if not self.latest:self._grant(timeout_s)
        while not (set(self.latest)=={'status','odometry'} and self.catalog and len(self.rpc)==2):
            self._next(number(deadline-self.clock.monotonic(),'source preparation remaining',positive=True))
            if self.footer or any(r['event']=='rpc_timeout' for r in self.rpc):
                raise RoverControlError('Receiver identity metadata incomplete')
        expected_spacing=0 if self.selection_mode=='CREDIT_PHASED_V1' else 500000000
        if self.header.get('spacing_source_ns')!=expected_spacing or self.header.get('after_status') is not True:
            raise RoverControlError('Reviewed receiver spacing/status contract differs')
        value=self.current()
        self.preparation=None
        if self.selection_mode=='CREDIT_PHASED_V1':self.set_phase('I')
        return value

    def close(self,*,timeout_s):
        if self.closed:return
        if self.close_attempted:raise RoverControlError('Receiver close already uncertain; inspect without replay')
        self.close_attempted=True
        deadline=self.clock.monotonic()+number(timeout_s,'receiver close timeout',positive=True)
        try:
            if not self.footer and not getattr(self.frames,'ended',lambda:False)():
                try:self.frames.request_close(max(1e-6,deadline-self.clock.monotonic()))
                except BrokenPipeError:
                    if not getattr(self.frames,'ended',lambda:False)():raise
            while self.footer is None:
                remaining=number(deadline-self.clock.monotonic(),'receiver close remaining',positive=True)
                self._next(remaining,closing=True)
            rc=self.frames.wait(number(deadline-self.clock.monotonic(),'receiver wait remaining',positive=True))
            self.close_result={'session_id':self.session_id,'receiver_process':self.identity,
                'return_code':rc,'footer_sha256':self.footer_sha256,'identity_verified':False,'movement_authorized':False}
            self.close_result['stderr']=getattr(self.frames,'stderr',b'').decode('utf-8',errors='replace')
            if rc!=0:raise RoverControlError('Receiver exit is not successful')
            self.journal({'operation':'receiver_close',**self.close_result,'footer':self.footer,'process':self.identity,
                          'source_identity_verified':False,'movement_authorized':False})
            self.frames.release();self.closed=True
        except Exception:
            # Keep the failure sticky. Never infer closure, restart or kill a
            # process from absence/EOF, or release a vehicle reservation here.
            self.failed=self.failed or 'RECEIVER_CLOSE_UNCERTAIN'
            if self.close_result is None:self.close_result={'session_id':self.session_id,'receiver_process':self.identity,
                'return_code':getattr(self.frames,'observed_return_code',None),'footer_sha256':self.footer_sha256,
                'identity_verified':False,'movement_authorized':False}
            # A sticky parse/data failure must not bypass the bounded child
            # wait/drain. Keep the original failure and never manufacture footer.
            try:
                drain=getattr(self.frames,'drain_failed',self.frames.wait)
                drain(number(deadline-self.clock.monotonic(),'failed receiver wait remaining',positive=True))
            except Exception as exc:
                self.close_result['drain_error']={'type':type(exc).__name__,'reason':str(exc)[:240]}
            self.close_result.update(return_code=getattr(self.frames,'observed_return_code',self.close_result['return_code']),
                stderr=getattr(self.frames,'stderr',b'').decode('utf-8',errors='replace'))
            self.journal({'operation':'receiver_close','status':'UNCERTAIN',**self.close_result,'reason':self.failed})
            raise


def qualify_stationary_source(source,limits):
    """Explicit passive test of the SAME pulse source; never constructs a reader.

    Caller must obtain passive admission/exclusion and current identity evidence.
    This function supplies neither authority nor a movement credential. S/D are
    retention phases here: no vehicle stop/disarm is requested or certified.
    """
    from tools.rover_control import RoverLimits
    if type(source) is not ObservationStream or not isinstance(limits,RoverLimits):raise RoverControlError('Exact supervised source and limits required')
    if source.selection_mode!='CREDIT_PHASED_V1' or source.max_age!=limits.observation_max_age_s:
        raise RoverControlError('Stationary source selection/freshness differs')
    result={'status':'UNCONFIRMED','bootstrap_contract':dict(BOOTSTRAP_CONTRACT),
            'observations':[],'controls_attempted':False,'movement_authorized':False,
            'vehicle_stop_or_disarm_certified':False}
    try:
        if limits.call_timeout_s!=BOOTSTRAP_CONTRACT['new_pair_timeout_s']:
            raise RoverControlError('Unreviewed stationary acquisition timeout')
        result['bootstrap']=source.prepare_metadata(timeout_s=BOOTSTRAP_CONTRACT['total_s'])
        result['credit_budget']={'metadata_pairs':1,'qualified_pairs':7,'maximum_pairs':10,
            'reserved_before_watch':6,'unused_final_pairs':2}
        previous={}
        def retain(value,phase):
            row={'phase':phase,'channels':{},'decision_monotonic_s':source.clock.monotonic()}
            for kind in ('status','odometry'):
                raw=value['sample_provenance'][kind];receipt=raw['receipt'];stamp=raw['source_stamp_ns']
                prior=previous.get(kind)
                if prior and (receipt<=prior[0] or stamp<=prior[1] or raw['gid']!=prior[2]):raise RoverControlError('Stationary source progression/identity failed')
                if phase=='W' and prior and receipt-prior[0]>limits.observation_max_age_s:
                    raise RoverControlError('Stationary watch inter-receipt limit exceeded')
                age=source.clock.monotonic()-receipt
                if not 0<=age<=limits.observation_max_age_s:raise RoverControlError('Stationary source age failed')
                row['channels'][kind]={'gid':raw['gid'],'source_stamp_ns':stamp,'original_receipt_monotonic_s':receipt,
                    'transfer_monotonic_s':raw['transfer'],'decision_age_s':age,'inter_receipt_s':None if prior is None else receipt-prior[0]}
                previous[kind]=(receipt,stamp,raw['gid'])
            status=value['status'];odom=value['odometry'];twist=odom['twist']['twist']
            row['observed_state']={k:status[k] for k in ('mode','armed','flying','external_control','failsafe')}
            if (status['armed'] or status['flying'] or status['failsafe'] or
                    sum(float(v)**2 for v in twist['linear'].values())**.5>limits.stopped_linear_mps or
                    sum(float(v)**2 for v in twist['angular'].values())**.5>limits.stopped_angular_rad_s):
                raise RoverControlError('Stationary/disarmed source precondition not observed')
            row['channel_receipt_skew_s']=abs(value['status_received_monotonic_s']-value['odometry_received_monotonic_s'])
            if row['channel_receipt_skew_s']>limits.observation_max_age_s:
                raise RoverControlError('Stationary channel receipt skew exceeded')
            result['observations'].append(row)
        retain(source.acquire_after_preparation(timeout_s=limits.call_timeout_s),'I')
        source.reserve_observations(6)
        for phase,count in [('W',2),('S',2),('D',2)]:
            source.set_phase(phase)
            for _ in range(count):
                if phase=='W':
                    deadline=source.clock.monotonic()+limits.call_timeout_s
                    while True:
                        value=source.poll(timeout_s=min(.05,number(deadline-source.clock.monotonic(),'stationary watch remaining',positive=True)))
                        if all(value['sample_provenance'][k]['source_stamp_ns']>previous[k][1] for k in previous):break
                        source.clock.sleep(min(.05,number(deadline-source.clock.monotonic(),'stationary watch remaining',positive=True)))
                else:value=source.observe(timeout_s=limits.call_timeout_s)
                retain(value,phase)
        result.update(status='STATIONARY_RETENTION_SEQUENCE_OBSERVED',remaining_pairs=min(10-v for v in source.counts.values()))
    except Exception as exc:
        result['error']={'operation':'qualify_stationary_source','type':type(exc).__name__,'reason':str(exc)[:240]}
        result['failed_phase']=(source.preparation or {}).get('phase',source.phase)
    finally:
        try:
            source.close(timeout_s=limits.call_timeout_s);result['receiver_close']=source.close_result
        except Exception as exc:
            result['status']='UNCONFIRMED';result['close_error']={'type':type(exc).__name__,'reason':str(exc)[:240]}
            result['receiver_close']=source.close_result
    return result


def start_receiver(binary,sha256,session_id,*,timeout_s,max_age_s,journal=lambda event:None,popen=subprocess.Popen,raw_sink=lambda raw:None,rpc_metadata=False,probe_on_start=True,credit_selection=False,status_availability=False):
    """Explicit future same-namespace receiver only. Never called by default."""
    path=Path(binary)
    if not path.is_absolute() or path.is_symlink() or hashlib.sha256(path.read_bytes()).hexdigest()!=sha256:
        raise RoverControlError('Receiver binary differs from reviewed hash')
    if str(UUID(session_id))!=session_id:raise RoverControlError('Receiver session id invalid')
    if type(rpc_metadata) is not bool or type(probe_on_start) is not bool:raise RoverControlError('Explicit receiver modes required')
    if type(credit_selection) is not bool or credit_selection and not rpc_metadata:raise RoverControlError('Phased receiver requires explicit RPC metadata')
    if type(status_availability) is not bool or status_availability and (rpc_metadata or credit_selection or probe_on_start):
        raise RoverControlError('Status diagnosis excludes RPC, credits and live probe')
    child=popen([str(path),'--session-id',session_id]+(['--rpc-metadata'] if rpc_metadata else [])+(['--credit-selection'] if credit_selection else [])+(['--status-availability'] if status_availability else []),stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
    try:identity=process_context(child.pid)
    except BaseException as exc:
        child.stdin.close()  # this child's EOF requests receiver closure; no signals or restart
        try:rc=child.wait(timeout=timeout_s)
        except subprocess.TimeoutExpired:rc=child.poll()
        stderr=b''
        for pipe,limit,is_output in ((child.stdout,MAX_BYTES,True),(child.stderr,4096,False)):
            os.set_blocking(pipe.fileno(),False);retained=0
            while retained<limit:
                try:raw=os.read(pipe.fileno(),min(4096,limit-retained))
                except BlockingIOError:break
                if not raw:break
                retained+=len(raw)
                if is_output:raw_sink(raw)
                else:stderr+=raw
            pipe.close()
        exc.receiver_start_diagnostic={'return_code':rc,'receiver_pid':child.pid,'receiver_process':None,'stderr':stderr}
        raise
    source=ObservationStream(PipeFrames(child,raw_sink),session_id=session_id,identity=identity,max_age_s=max_age_s,journal=journal,selection_mode="CREDIT_PHASED_V1" if credit_selection else "DIAGNOSTIC_SPACING_V1")
    try:
        if probe_on_start:source.probe(timeout_s=timeout_s)
    except BaseException as exc:
        try:source.close(timeout_s=timeout_s)
        except Exception:pass  # propagate original failure, retain child deadline; never force signals
        exc.receiver_source=source
        raise
    return source
