"""Native receiver main -> real OS pipes -> real Python consumer; SYNTHETIC.

No SDK, ROS/DDS participants or operational binary execution. The exact source
is linked with explicit callback/session/RPC doubles in a frozen test build.
"""
from pathlib import Path
import hashlib,json,os,select,subprocess,threading,time
import pytest
from tools import rover_observation_stream as stream
from tests.fixtures.rover_receiver_protocol_native import build

SESSION='11111111-1111-4111-8111-111111111111'
ROOT=Path(__file__).resolve().parents[1]

@pytest.fixture(scope='module')
def native(tmp_path_factory):
    root=Path(os.environ['TFG_PROTOCOL_EVIDENCE'])/'native' if os.environ.get('TFG_PROTOCOL_EVIDENCE') else tmp_path_factory.mktemp('receiver-protocol')
    return build(root,source_root=ROOT)

class Protocol:
    def __init__(self,binary,*,rpc_delay=0):
        self.rows=[];self.events=[];self.feeder=None
        rd,self.input=os.pipe();self.feedback,wr=os.pipe()
        env={**os.environ,'TFG_SYNTHETIC_INPUT_FD':str(rd),'TFG_SYNTHETIC_FEEDBACK_FD':str(wr),'TFG_SYNTHETIC_RPC_DELAY_MS':str(rpc_delay)}
        def popen(argv,**kwargs):
            self.child=subprocess.Popen(argv,env=env,pass_fds=(rd,wr),**kwargs);return self.child
        try:
            self.source=stream.start_receiver(str(binary.resolve()),hashlib.sha256(binary.read_bytes()).hexdigest(),SESSION,
                timeout_s=1,max_age_s=.5,popen=popen,raw_sink=self.rows.append,journal=self.events.append,
                rpc_metadata=True,probe_on_start=False,credit_selection=True)
        finally:os.close(rd);os.close(wr)
    def feed(self,char):
        os.write(self.input,char.encode());assert select.select([self.feedback],[],[],2)[0],'Synthetic callback did not complete'
        assert os.read(self.feedback,1)==char.encode()
    def schedule(self,events):
        errors=[]
        def work():
            try:
                for delay,char in events:time.sleep(delay);self.feed(char)
            except (OSError,AssertionError) as exc:errors.append(str(exc))
        self.feeder=threading.Thread(target=work);self.feeder.start();self.feed_errors=errors
    def records(self):return [json.loads(raw) for raw in b''.join(self.rows).splitlines()]
    def finish(self):
        try:
            if not self.source.close_attempted:
                try:self.source.close(timeout_s=1)
                except Exception:pass
            if self.feeder:self.feeder.join(2)
            self.child.wait(timeout=2)
            self.unconsumed=self.source.frames.buffer
            if not self.child.stdout.closed:
                os.set_blocking(self.child.stdout.fileno(),False)
                while True:
                    raw=os.read(self.child.stdout.fileno(),4096)
                    if not raw:break
                    self.unconsumed+=raw
        finally:
            if self.child.poll() is None:self.child.kill();self.child.wait(timeout=2)
            if not self.source.closed:self.source.frames.release()
            os.close(self.input);os.close(self.feedback)
    def save(self,name):
        if os.environ.get('TFG_PROTOCOL_EVIDENCE'):
            p=Path(os.environ['TFG_PROTOCOL_EVIDENCE'])/name;p.mkdir()
            (p/'journal.jsonl').write_bytes(b''.join(self.rows));(p/'stderr').write_bytes(self.source.frames.stderr)
            (p/'test-only-unconsumed-stdout').write_bytes(getattr(self,'unconsumed',b''))
            (p/'result.json').write_text(json.dumps({'kind':'SYNTHETIC_NATIVE_MAIN_AND_REAL_CONSUMER','events':self.events,
                'counts':self.source.counts,'footer_validated':bool(self.source.footer),'closed':self.source.closed,
                'failed':self.source.failed,'close_result':self.source.close_result,'returncode':self.child.returncode},indent=2)+'\n')

@pytest.mark.parametrize('order',['SO','OSO'])
def test_first_pair_and_metadata_with_native_real_pipes(native,order):
    p=Protocol(native)
    try:
        p.schedule([(.03,c) for c in order]);value=p.source.prepare_identity(timeout_s=1)
        assert set(value['sample_provenance'])=={'status','odometry'}
        assert p.source.counts=={'/ap/v3/status':1,'/rover1/odometry':1}
        assert len(p.source.rpc)==2 and p.source.catalog['received']
        assert all(0<=time.monotonic()-v['receipt']<=.5 for v in p.source.latest.values())
        p.source.close(timeout_s=1)
        assert p.source.closed and p.source.close_result['return_code']==0
        assert p.source.footer['termination']=='LOCAL_CLOSE'
        assert p.source.footer['omitted_before_status']==(1 if order=='OSO' else 0)
    finally:p.finish();p.save('first-pair-'+order)


def test_callbacks_before_and_after_credit_are_not_reused(native):
    p=Protocol(native)
    try:
        p.source._next(1);p.feed('S');p.feed('O')
        assert p.source.counts=={'/ap/v3/status':0,'/rover1/odometry':0}
        p.schedule([(.03,'s'),(.03,'S'),(.03,'O')]);p.source.prepare_identity(timeout_s=1)
        # Repeated pre-credit Status stamp is discarded, then a new callback wins.
        assert p.source.latest['status']['source_stamp_ns']==20000000
        assert p.source.latest['odometry']['source_stamp_ns']==20000000
        assert all(s['receipt']>=p.source.credits[0]['requested_monotonic_s'] for s in p.source.latest.values())
        p.source.close(timeout_s=1)
        assert p.source.footer['callback_coverage']['/ap/v3/status']['callbacks']==3
        assert p.source.footer['callback_coverage']['/ap/v3/status']['not_credited_or_nonprogressing']==2
    finally:p.finish();p.save('pre-post-credit')


def test_timeout_keeps_failure_but_preserves_native_close_footer(native):
    p=Protocol(native)
    try:
        start=time.monotonic()
        with pytest.raises(TimeoutError,match='Receiver transfer deadline'):p.source.prepare_identity(timeout_s=1)
        assert .9<=time.monotonic()-start<1.5
        assert [r['event'] for r in p.records()]==['header','selection_credit']
        with pytest.raises(Exception,match='permanently rejected'):p.source.close(timeout_s=1)
        assert p.source.close_result['return_code']==0 and p.source.footer is None and not p.source.closed
        assert p.source.failed=='TimeoutError:Receiver transfer deadline'
        # Evidence only: raw stdout must survive without renewing/revalidating it.
        footer=[r for r in p.records() if r['event']=='footer']
        assert len(footer)==1 and footer[0]['termination']=='LOCAL_CLOSE'
        assert footer[0]['counts']=={'/ap/v3/status':0,'/rover1/odometry':0}
    finally:p.finish();p.save('timeout-close')


def test_first_pair_after_timeout_is_diagnostic_only(native):
    p=Protocol(native)
    try:
        p.schedule([(1.08,'S'),(.01,'O')])
        with pytest.raises(TimeoutError):p.source.prepare_identity(timeout_s=1)
        with pytest.raises(Exception):p.source.close(timeout_s=1)
        assert not p.source.closed and p.source.footer is None and not p.source.latest
        assert p.source.close_result['return_code']==0
        assert any(r['event']=='footer' for r in p.records())
        assert all(not e.get('valid') for e in p.events if e.get('record',{}).get('event')=='sample')
    finally:p.finish();p.save('late-data-close')


def test_rpc_work_is_inside_original_preparation_deadline(native):
    p=Protocol(native,rpc_delay=1100)
    try:
        p.schedule([(.03,'S'),(.03,'O')])
        with pytest.raises(TimeoutError,match='Receiver transfer deadline'):p.source.prepare_identity(timeout_s=1)
        assert p.source.counts=={'/ap/v3/status':1,'/rover1/odometry':0}
        assert [r['event'] for r in p.records()]==['header','selection_credit','sample','rpc_request']
        with pytest.raises(Exception):p.source.close(timeout_s=1)
        assert p.source.failed=='TimeoutError:Receiver transfer deadline'
        assert p.source.close_result['return_code']==0 and p.source.footer is None
    finally:p.finish();p.save('rpc-delayed')


def test_child_eof_rc0_does_not_manufacture_footer_or_success(native):
    p=Protocol(native)
    try:
        p.source._grant(1);p.source._next(1);p.source._next(1)
        os.write(p.input,b'X')
        # Closing reads deliberately do not require a still-live process: test
        # the actual pipe EOF after the same native header and credit ack.
        with pytest.raises(Exception,match='disconnected/truncated'):p.source._next(1,closing=True)
        with pytest.raises(Exception):p.source.close(timeout_s=1)
        assert p.source.close_result['return_code']==0 and not p.source.footer and not p.source.closed
        assert b'SYNTHETIC_EXIT_WITHOUT_FOOTER' in p.source.frames.stderr
    finally:p.finish();p.save('child-eof')

@pytest.mark.parametrize('deliver',[True,False,'slow','loss'])
def test_existing_capture_driver_preserves_full_credit_protocol_and_timeout(native,tmp_path,monkeypatch,deliver):
    from dataclasses import asdict
    from tools.rover_control import RoverLimits
    from tools.rover_xrce_trace import passive_trial as passive
    p=Protocol(native,rpc_delay=700 if deliver=='slow' else 0);tmp_path.chmod(0o700);prefix=tmp_path/'prefix';prefix.mkdir()
    (prefix/'selection.json').write_text(json.dumps({'descriptor':{'lifecycle_id':SESSION}}))
    monkeypatch.setattr(passive,'admit_from_prefix',lambda p:{'measurement_allowed':True,'fixture':'SYNTHETIC_NO_ADMISSION'})
    def existing_child(*args,**kw):
        assert kw['credit_selection'] and kw['rpc_metadata'] and not kw['probe_on_start']
        p.source.journal=lambda row:(p.events.append(row),kw['journal'](row))
        p.source.frames.sink=lambda raw:(p.rows.append(raw),kw['raw_sink'](raw))
        return p.source
    monkeypatch.setattr(stream,'start_receiver',existing_child)
    if deliver:
        def feed_all():
            for n in range(1,9):
                deadline=time.monotonic()+2
                # Issuing a byte is not applying it: a callback already in
                # spin_once can run before the native loop acknowledges B1.
                while (len(p.source.credits)<n or not p.source.credits[n-1]['ack']) and time.monotonic()<deadline:time.sleep(.001)
                if len(p.source.credits)<n or not p.source.credits[n-1]['ack']:return
                p.feed('S')
                if deliver=='loss' and n==3:return
                p.feed('O')
        p.feeder=threading.Thread(target=feed_all);p.feeder.start()
    try:
        limits=RoverLimits(.05,.1,3.,1.,5.,.5,.01,.01)
        result=passive.capture_transport_from_prefix(prefix,str(native),hashlib.sha256(native.read_bytes()).hexdigest(),tmp_path,stationary_limits=asdict(limits))
        receipt=json.loads((tmp_path/'receiver-receipt.json').read_bytes());assert receipt==result
        rows=[json.loads(line) for line in (tmp_path/'journal.jsonl').read_bytes().splitlines()]
        assert rows[-1]['event']=='footer' and rows[-1]['termination']=='LOCAL_CLOSE'
        assert result['return_code']==0 and (tmp_path/'receiver.stderr').read_bytes()==b''
        if deliver=='loss':
            q=result['stationary_qualification']
            assert result['status']=='STATIONARY_QUALIFICATION_REJECTED' and q['status']=='UNCONFIRMED',result
            assert q['failed_phase']=='W' and not q['controls_attempted']
            assert q['receiver_close']['return_code']==0 and q['receiver_close']['footer_sha256']
            assert min(10-v for v in p.source.counts.values())==7
        elif deliver:
            assert result['status']=='RECEIVER_CLOSED',result
            q=result['stationary_qualification'];assert q['status']=='STATIONARY_RETENTION_SEQUENCE_OBSERVED',q
            assert [r['phase'] for r in q['observations']]==list('IWWSSDD')
            assert sum(r['event']=='sample' for r in rows)==16
            assert q['remaining_pairs']==2 and result['footer_sha256']
            assert not q['controls_attempted'] and not q['vehicle_stop_or_disarm_certified']
            boundary=q['bootstrap']['finished_monotonic_s']
            assert all(c['original_receipt_monotonic_s']>boundary for row in q['observations'] for c in row['channels'].values())
            if deliver=='slow':assert q['bootstrap']['finished_monotonic_s']-q['bootstrap']['started_monotonic_s']>.5
        else:
            assert result['status']=='UNCERTAIN' and result['footer_sha256'] is None
            events=json.loads((tmp_path/'transfer-events.json').read_bytes())
            diag=next(row['source_preparation'] for row in events if row.get('valid') is False)
            assert diag['deadline_monotonic_s']-diag['started_monotonic_s']==pytest.approx(stream.BOOTSTRAP_CONTRACT['total_s'])
            assert diag['failure_monotonic_s']>=diag['deadline_monotonic_s']
            assert set(diag['pending_events'])=={'status','odometry','rpc_request','rpc_reply','scene_catalog'}
    finally:p.finish();p.save('capture-driver-'+str(deliver))

@pytest.mark.parametrize('fault',['stdout_budget','stderr_budget','persist','deadline'])
def test_failed_drain_keeps_original_bounds_and_errors(tmp_path,fault):
    import sys
    source={'stdout_budget':f"import os;os.write(1,b'x'*{stream.MAX_BYTES+1})",
            'stderr_budget':"import os;os.write(2,b'x'*4097)",
            'persist':"import os;os.write(1,b'raw diagnostic')",
            'deadline':"import time;time.sleep(.3)"}[fault]
    child=subprocess.Popen([sys.executable,'-c',source],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
    def sink(raw):
        if fault=='persist':raise OSError('SYNTHETIC_PERSISTENCE_FAILURE')
    frames=stream.PipeFrames(child,sink)
    try:
        pattern={'stdout_budget':'aggregate budget','stderr_budget':'stderr budget','persist':'SYNTHETIC_PERSISTENCE_FAILURE','deadline':'failed drain deadline'}[fault]
        with pytest.raises(Exception,match=pattern):frames.drain_failed(.05 if fault=='deadline' else 1.)
    finally:
        if child.poll() is None:child.kill()
        child.wait(timeout=1);frames.release()


def test_slow_bounded_metadata_requires_strictly_new_pair_before_watch(native):
    p=Protocol(native,rpc_delay=700)
    try:
        p.schedule([(.03,'S'),(.03,'O')]);bootstrap=p.source.prepare_metadata(timeout_s=stream.BOOTSTRAP_CONTRACT['total_s'])
        assert bootstrap['finished_monotonic_s']-bootstrap['started_monotonic_s']>.5
        before={k:dict(v) for k,v in p.source.latest.items()}
        assert time.monotonic()-before['status']['receipt']>.5
        assert not bootstrap['observations_qualified']
        with pytest.raises(Exception,match='New observation pair'):p.source.current()
        with pytest.raises(Exception,match='New observation pair'):p.source.probe(timeout_s=1)
        p.feeder.join(2);p.schedule([(.03,'S'),(.03,'O')])
        value=p.source.acquire_after_preparation(timeout_s=1)
        for kind in ('status','odometry'):
            row=value['sample_provenance'][kind]
            assert row['receipt']>bootstrap['finished_monotonic_s']
            assert row['source_stamp_ns']>before[kind]['source_stamp_ns']
            assert row['gid']==before[kind]['gid']
            assert 0<=time.monotonic()-row['receipt']<=.5
            # Do not change the recorded bootstrap's original callback times.
            original=next(r for r in p.records() if r.get('event')=='sample' and r['topic']==('/ap/v3/status' if kind=='status' else '/rover1/odometry'))
            assert original['sample']['receipt']['steady_ns']/1e9==before[kind]['receipt']
        assert abs(value['status_received_monotonic_s']-value['odometry_received_monotonic_s'])<=.5
        p.source.reserve_observations(6);p.source.set_phase('W')
        # Metadata work cannot run again: no dependency makes a new request.
        p.feeder.join(2);p.schedule([(.03,'S'),(.03,'O')]);p.source.observe(timeout_s=1)
        assert len([r for r in p.records() if r['event']=='rpc_request'])==1
        assert len([r for r in p.records() if r['event']=='rpc_reply'])==1
        assert len([r for r in p.records() if r['event']=='scene_catalog'])==1
        p.source.close(timeout_s=1)
        assert p.source.closed
    finally:p.finish();p.save('staged-slow-metadata-new-pair')


def test_preparation_timeout_remains_failure_and_drains_late_metadata(native):
    p=Protocol(native,rpc_delay=400)
    try:
        p.schedule([(.03,'S'),(.03,'O')])
        with pytest.raises(TimeoutError):p.source.prepare_metadata(timeout_s=.15)
        assert p.source.metadata_prepared_monotonic_s is None
        with pytest.raises(Exception):p.source.close(timeout_s=1)
        assert not p.source.closed and not p.source.footer and p.source.close_result['return_code']==0
        assert p.source.failed=='TimeoutError:Receiver transfer deadline'
        error=next(e for e in p.events if e.get('valid') is False)
        assert error['source_preparation']['phase']=='BOOTSTRAP_METADATA'
        assert any(r['event']=='footer' for r in p.records())
    finally:p.finish();p.save('staged-preparation-timeout')


def test_context_change_after_metadata_blocks_new_credit(native):
    p=Protocol(native)
    try:
        p.schedule([(.03,'S'),(.03,'O')]);p.source.prepare_metadata(timeout_s=1)
        credits=len(p.source.credits);real=p.source.read_context
        p.source.read_context=lambda pid:{**real(pid),'start_ticks':real(pid)['start_ticks']+1} if pid==p.child.pid else real(pid)
        with pytest.raises(Exception,match='incarnation'):p.source.acquire_after_preparation(timeout_s=1)
        assert len(p.source.credits)==credits
        p.source.read_context=real;p.source.close(timeout_s=1)
    finally:p.finish();p.save('staged-context-changed')


def test_watch_data_loss_preserves_reserves_and_failure(native):
    p=Protocol(native)
    try:
        p.schedule([(.03,'S'),(.03,'O')]);p.source.prepare_metadata(timeout_s=1)
        p.feeder.join(2);p.schedule([(.03,'S'),(.03,'O')]);p.source.acquire_after_preparation(timeout_s=1)
        p.source.reserve_observations(6);p.source.set_phase('W')
        p.feeder.join(2);p.schedule([(.03,'S')])
        with pytest.raises(TimeoutError):p.source.observe(timeout_s=1)
        assert p.source.counts=={'/ap/v3/status':3,'/rover1/odometry':2}
        assert min(10-v for v in p.source.counts.values())==7
        with pytest.raises(Exception):p.source.current()
        with pytest.raises(Exception):p.source.close(timeout_s=1)
        assert not p.source.closed and not p.source.footer and p.source.close_result['return_code']==0
    finally:p.finish();p.save('staged-watch-loss')
