"""Single-attempt passive driver protocol. No CLI, control publisher or consent grant.

LocalPorts only uses the existing protected lifecycle and selected passive reader.
Callers require a separate operator authorization; a declaration is not identity
 authentication. Imports never start processes. Tests inject ports and storage.
"""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time
from uuid import UUID


RETENTION_CONTRACT={'mode':'CREDIT_PHASED_V1','reserved_stop_pairs':3,'reserved_final_pairs':3,'max_samples':20,'duration_s':120}
STATUS_WINDOW={'observation_s':120.,'capture_outer_s':140.,'drain_ceiling_s':20.,
               'lifecycle_outer_s':80.,'inventory_outer_s':45.,'observation_max_age_s':.5}


def observe_status_window(source,*,started_monotonic_s):
    """Same owned pipe, finite evidence window; never a pulse-source qualifier.

    Draining uses the remaining 140s capture envelope, not an assumed 1s.
    Host docker transport still has its independent existing 140s timeout.
    """
    from tools.rover_observation_stream import ObservationStream
    if type(source) is not ObservationStream or source.selection_mode!='DIAGNOSTIC_SPACING_V1' or source.max_age!=.5:
        raise ValueError('Exact diagnostic source/freshness required')
    clock=source.clock
    started=float(started_monotonic_s)
    if not 0<=clock.monotonic()-started<STATUS_WINDOW['observation_s']:
        raise ValueError('Invalid/already spent diagnostic observation window')
    end=started+STATUS_WINDOW['observation_s']
    outer=started+STATUS_WINDOW['capture_outer_s']
    result={'purpose':'STATUS_AVAILABILITY_ONLY','movement_authorized':False,
            'source_qualified_for_pulse':False,'status':'DIAGNOSTIC_EVIDENCE_ONLY',
            'started_monotonic_s':started,'observation_deadline_monotonic_s':end,
            'outer_deadline_monotonic_s':outer,'budget':dict(STATUS_WINDOW)}
    try:
        while not source.footer:
            remaining=end-clock.monotonic()
            if remaining<=0:break
            # readiness waits are not failed transfers and cannot make a quiet
            # topic permanently fail at every polling tick.
            if source.frames.ready(min(.05,remaining)):
                ended=source.frames.child.poll() is not None
                if not ended:source._live()
                before=sum(source.counts.values())
                source._next(end-clock.monotonic(),closing=True)
                if ended and sum(source.counts.values())!=before:
                    raise ValueError('Post-exit sample context not current; retained as raw diagnosis only')
        result['observation_finished_monotonic_s']=clock.monotonic()
    except BaseException as exc:
        result['status']='UNCONFIRMED'
        result['initial_error']={'type':type(exc).__name__,'reason':str(exc)[:240]}
        if not isinstance(exc,Exception):
            exc.status_window_diagnostic=result
            raise
    finally:
        remaining=min(STATUS_WINDOW['drain_ceiling_s'],outer-clock.monotonic())
        result['drain_budget_s']=max(0,remaining)
        try:
            if remaining<=0:raise TimeoutError('Status capture envelope spent; protected lifecycle close required')
            source.close(timeout_s=remaining)
        except Exception as exc:
            result['status']='UNCONFIRMED'
            result['close_error']={'type':type(exc).__name__,'reason':str(exc)[:240]}
        result['receiver_close']=source.close_result
        result['finished_monotonic_s']=clock.monotonic()
    return result


def write_once(path,value):
    fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
    with os.fdopen(fd,'w') as f:
        json.dump(value,f,allow_nan=False,indent=2);f.write('\n');f.flush();os.fsync(f.fileno())
    parent=os.open(path.parent,os.O_RDONLY|os.O_DIRECTORY)
    try:os.fsync(parent)
    finally:os.close(parent)


def execute_once(root,ports):
    """No automatic retries, including errors, missing responses and restarts."""
    root=Path(root);root.mkdir(parents=True,exist_ok=True,mode=0o700)
    if root.is_symlink() or root.stat().st_uid!=os.getuid() or root.stat().st_mode & 0o077:
        raise ValueError('Private owned driver directory required')
    write_once(root/'single-opening.intent',{'scope':'ONE_PASSIVE_SESSION','movement_authorized':False})
    result={'start':None,'admission':None,'reader':None,'stop':None,'post':None,'movement_authorized':False};owner=None
    try:
        result['start']=ports.start()
        owner=result['start'].get('operation',{}).get('owner_id')
        if owner and str(UUID(owner))!=owner:raise ValueError('Noncanonical start owner')
        write_once(root/'start-result.json',result['start'])
        if result['start'].get('status')!='SUCCESS':return result
        if not owner:raise ValueError('Start response lost; inspect, do not resume')
        result['admission']=ports.admit(owner);write_once(root/'capture-admission.json',result['admission'])
        if result['admission'].get('measurement_allowed') is not True:return result
        result['reader']=ports.reader(owner);write_once(root/'reader-result.json',result['reader'])
    except BaseException as exc:
        result['error']={'type':type(exc).__name__,'message':str(exc)}
        if not isinstance(exc,Exception):raise
    finally:
        if owner:
            try:result['stop']=ports.stop(owner)
            except Exception as exc:result['stop']={'status':'UNCERTAIN','error_type':type(exc).__name__}
            try:write_once(root/'stop-result.json',result['stop'])
            except OSError:result['persistence']='UNCERTAIN'
        try:result['post']=ports.post(owner)
        except Exception as exc:result['post']={'status':'UNKNOWN','error_type':type(exc).__name__}
        try:write_once(root/'driver-result.json',result)
        except OSError:result['persistence']='UNCERTAIN'
    return result


def admit_from_prefix(prefix):
    """Fresh core/resource admission; socket uniqueness is a RESULT, not consent."""
    from .selection import verify_overlay
    from tools.rover_passive_validation import session_window
    prefix=Path(prefix);value=json.loads((prefix/'selection.json').read_bytes())['descriptor'];verify_overlay(value)
    monitor=json.loads((prefix/'capture/monitor.json').read_bytes())
    if monitor['lifecycle_id']!=value['lifecycle_id']:raise ValueError('Mixed session context')
    if value['manifest']['schema'] in {'tfg.xrce-agent-selection/2','tfg.xrce-agent-selection/3','tfg.xrce-agent-selection/4'} and not monitor.get('identity_bridge',{}).get('verified_overlay_library'):
        raise ValueError('Essential bridge identity unavailable')
    if value['manifest']['schema'] in {'tfg.xrce-agent-selection/3','tfg.xrce-agent-selection/4'} and not monitor.get('model_source',{}).get('verified_overlay_library'):
        raise ValueError('Essential model source identity unavailable')
    boot=Path('/proc/sys/kernel/random/boot_id').read_text().strip()
    plan=session_window(monitor,now=time.monotonic(),boot_id=boot)
    return {'measurement_allowed':True,'budget':plan,'socket_inventory':monitor['socket_inventory'],
            'global_uniqueness':'NOT_ASSERTED','movement_authorized':False}


def capture_transport_from_prefix(prefix,binary,binary_sha256,directory,*,stationary_limits=None,status_availability=False):
    """Future single receiver; reuses fresh admission and source used by adapter.

    Does not start/stop lifecycle or grant motion. Caller needs separate passive
    session authorization. Exact wire bytes survive parse/transfer failures.
    """
    if type(status_availability) is not bool or status_availability and stationary_limits is not None:
        raise ValueError('Status evidence window is separate from stationary qualification')
    from tools.rover_observation_stream import start_receiver,MAX_BYTES
    prefix=Path(prefix);root=Path(directory)
    if root.is_symlink() or root.stat().st_uid!=os.getuid() or root.stat().st_mode & 0o077:
        raise ValueError('Private owned capture directory required')
    admission=admit_from_prefix(prefix);write_once(root/'capture-admission.json',admission)
    selected=json.loads((prefix/'selection.json').read_bytes())['descriptor']
    owner=selected['lifecycle_id']
    native_options={}
    if status_availability:
        from .selection import STATUS_SCHEMA,verify_overlay
        if selected['manifest']['schema']!=STATUS_SCHEMA:
            raise ValueError('Status diagnostic needs its explicit rover/agent selection')
        verify_overlay(selected)
        env={**os.environ,'TFG_STATUS_DIAGNOSTIC':owner,
             'TFG_STATUS_DIAGNOSTIC_CONTEXT':selected['selection_sha256']}
        env.pop('TFG_STATUS_DIAGNOSTIC_FIXTURE_FD',None)
        native_options['popen']=lambda argv,**kw:subprocess.Popen(argv,env=env,**kw)
    source=None;events=[];event_bytes=0;written=0;startup_stderr=b'';status_handled=False
    result={'status':'UNCERTAIN','session_id':owner,'return_code':None,'movement_authorized':False}
    interruption=None
    with (root/'journal.jsonl').open('xb') as output:
        os.chmod(root/'journal.jsonl',0o600)
        def sink(raw):
            nonlocal written
            if written+len(raw)>MAX_BYTES:raise ValueError('Raw journal budget')
            if output.write(raw)!=len(raw):raise OSError('Short journal write')
            output.flush();os.fsync(output.fileno());written+=len(raw)
        def event(value):
            nonlocal event_bytes
            summary={k:value[k] for k in ('operation','valid','reason','transfer_received_monotonic_s','return_code','footer_sha256','source_preparation') if k in value}
            summary['sequence']=value.get('record',{}).get('sequence')
            row=value.get('record',{})
            if row.get('event')=='sample':
                from tools.rover_observation_stream import process_context
                try:
                    actual=process_context(row['client_process']['pid']);own=process_context(os.getpid())
                    summary['receiver_context_at_transfer']=('MATCH' if actual==row['client_process'] and all(actual[k]==own[k] for k in ('boot_id','net_namespace','pid_namespace','time_namespace')) else 'MISMATCH')
                except (OSError,ValueError):summary['receiver_context_at_transfer']='UNKNOWN'
                summary['fresh_pair_at_transfer']=bool(source and all(k in source.latest and 0<=time.monotonic()-source.latest[k]['receipt']<=.5 for k in ('status','odometry')))
            event_bytes+=len(json.dumps(summary).encode())
            if event_bytes>32768:raise ValueError('Transfer event budget')
            events.append(summary)
        try:
            if stationary_limits is not None:
                from tools.rover_control import RoverLimits
                stationary_limits=RoverLimits(**stationary_limits)
                if stationary_limits.observation_max_age_s!=.5 or stationary_limits.call_timeout_s!=1.:raise ValueError('Unreviewed stationary timing')
            receiver_started=time.monotonic()
            source=start_receiver(binary,binary_sha256,owner,timeout_s=5.,max_age_s=.5,
                journal=event,raw_sink=sink,rpc_metadata=not status_availability,probe_on_start=False,
                credit_selection=stationary_limits is not None,status_availability=status_availability,**native_options)
            if status_availability:
                status_handled=True
                result['status_diagnostic']=observe_status_window(source,started_monotonic_s=receiver_started)
            elif stationary_limits is not None:
                from tools.rover_observation_stream import qualify_stationary_source
                result['stationary_qualification']=qualify_stationary_source(source,stationary_limits)
            else:
                while not source.footer:source._next(120.,closing=True)  # capture/drain is not a live-control observation
            if not status_availability and not source.close_attempted:source.close(timeout_s=1.)
            if source.close_result:
                result.update(source.close_result)
                result['status']='RECEIVER_CLOSED' if result.get('footer_sha256') else 'UNCERTAIN'
            if status_availability and result['status_diagnostic']['status']=='UNCONFIRMED':result['status']='STATUS_DIAGNOSTIC_UNCONFIRMED'
            if stationary_limits is not None and result['status']!='UNCERTAIN' and result['stationary_qualification']['status']!='STATIONARY_RETENTION_SEQUENCE_OBSERVED':result['status']='STATIONARY_QUALIFICATION_REJECTED'
        except BaseException as exc:
            if not isinstance(exc,Exception):interruption=exc
            if status_availability and hasattr(exc,'status_window_diagnostic'):
                result['status_diagnostic']=exc.status_window_diagnostic
            source=source or getattr(exc,'receiver_source',None)
            result['reason']=type(exc).__name__+':'+str(exc)
            diagnostic=getattr(exc,'receiver_start_diagnostic',None)
            if diagnostic:
                startup_stderr=diagnostic.get('stderr',b'');result.update({k:v for k,v in diagnostic.items() if k!='stderr'})
            if source is not None:
                if not source.close_attempted and not status_handled:
                    try:source.close(timeout_s=max(.001,min(20.,receiver_started+140.-source.clock.monotonic())) if status_availability else 1.)
                    except Exception as closing:result['close_error']={'type':type(closing).__name__,'message':str(closing)}
                if source.close_result:result.update(source.close_result)
        result['raw_bytes']=written
    stderr=getattr(source.frames,'stderr',b'') if source is not None else startup_stderr
    # Try every receipt even if one persistence channel fails. Never mask the
    # original receiver error with a later disk error or a successful close.
    result['persistence_errors']=[]
    try:
        fd=os.open(root/'receiver.stderr',os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
        with os.fdopen(fd,'wb') as file:file.write(stderr);file.flush();os.fsync(file.fileno())
    except OSError as exc:result['persistence_errors'].append({'file':'receiver.stderr','error':str(exc)})
    for name,value in [('transfer-events.json',events),('receiver-receipt.json',result)]:
        if result['persistence_errors']:result['persistence']='UNCERTAIN'
        try:write_once(root/name,value)
        except OSError as exc:result['persistence_errors'].append({'file':name,'error':str(exc)})
    if result['persistence_errors']:result['persistence']='UNCERTAIN'
    if interruption is not None:raise interruption
    return result


class LocalPorts:
    """Future authorized use only. Fixed command shapes, no eval or ROS CLI."""
    def __init__(self,repo,root,manifest,reader_manifest,*,socket_helper_review=None):
        from .selection import load_manifest
        self.repo=Path(repo);self.root=Path(root);self.manifest=Path(manifest)
        self.selected=load_manifest(manifest);self.reader_selection=json.loads(Path(reader_manifest).read_bytes())
        self.socket_helper_review=Path(socket_helper_review) if socket_helper_review is not None else None
        self.validate_reader()
    def validate_reader(self):
        if self.reader_selection.get('schema')=='tfg.rover-transport-reader/1':
            from .selection import MODEL_SCHEMA,STATUS_SCHEMA,STATUS_PAIR,RPC_IDENTITY_ARTIFACTS,RPC_PREPARED_ARTIFACTS,digest
            if self.reader_selection.get('prepared') is not True:
                raise ValueError('Receiver preparation unavailable; no opening')
            status_variant=self.selected['schema']==STATUS_SCHEMA
            pairs=(STATUS_PAIR+RPC_PREPARED_ARTIFACTS[2:],) if status_variant else (RPC_IDENTITY_ARTIFACTS,RPC_PREPARED_ARTIFACTS)
            if (self.selected['schema'] not in (MODEL_SCHEMA,STATUS_SCHEMA) or
                    tuple(self.selected[k+'_sha256'] for k in ('wrapper','library','bridge','bridge_library')) not in pairs or
                    self.reader_selection.get('agent_selection_sha256')!=digest(self.selected)):
                raise ValueError('Incompatible receiver/RPC selection')
            if not isinstance(self.reader_selection.get('source_hashes'),dict) or not isinstance(self.reader_selection.get('native_dependencies'),dict):
                raise ValueError('Missing receiver build review')
            if (self.reader_selection.get('max_samples')!=20 or self.reader_selection.get('duration_s')!=120
                    or self.reader_selection.get('max_wire_bytes')!=448*1024):raise ValueError('Unreviewed receiver bounds')
            if not {'tools/rover_identity_probe/observation_receiver.cpp','tools/rover_identity_probe/session_context.hpp',
                    'tools/rover_identity_probe/parameter_rpc.hpp','tools/rover_observation_stream.py',
                    'tools/rover_xrce_trace/passive_trial.py','tools/rover_xrce_trace/selection.py',
                    'tools/rover_identity_probe/CMakeLists.txt','tools/rover_passive_rclcpp/collector_core.hpp',
                    'tools/rover_passive_rclcpp/observer.hpp'}<=self.reader_selection.get('source_hashes',{}).keys():
                raise ValueError('Incomplete receiver/source review')
            if not 1<=len(self.reader_selection.get('native_dependencies',{}))<=256:raise ValueError('Missing native dependency pins')
            p=Path(self.reader_selection['binary']['path'])
            if not p.is_absolute() or '..' in p.parts or not p.is_relative_to('/tmp') or p.name!='rover_observation_receiver':
                raise ValueError('Explicit temporary receiver binary required')
            for name,expected in self.reader_selection['source_hashes'].items():
                p=(self.repo/name).resolve()
                if not p.is_relative_to(self.repo.resolve()) or hashlib.sha256(p.read_bytes()).hexdigest()!=expected:
                    raise ValueError('Receiver/helper source differs from reviewed preparation')
            retention=self.reader_selection.get('retention_selection')
            status_review=self.reader_selection.get('helper_review',{}).get('status_source_review')
            if status_variant or status_review is not None or 'status_window' in self.reader_selection:
                required={'tools/rover_identity_probe/status_diagnostic.hpp',
                          'tools/rover_identity_probe/status_producer.hpp',
                          'tools/rover_identity_probe/status_producer_impl.hpp',
                          'tools/rover_identity_probe/status_producer.cpp',
                          'tools/rover_xrce_trace/prepare_status.py'}
                from .selection import TIMING_STATUS_BUILD
                if tuple(self.selected[k+'_sha256'] for k in ('rover','model_library'))==TIMING_STATUS_BUILD:
                    required|={'tools/rover_identity_probe/timing_window.hpp',
                               'tools/rover_identity_probe/timing_fields.hpp',
                               'tools/rover_xrce_trace/prepare_timing.py',
                               'tools/rover_xrce_trace/model_probe/model_timing.hpp'}
                if (not status_variant or retention is not None or
                        self.reader_selection.get('status_window')!=STATUS_WINDOW or
                        not isinstance(status_review,dict) or
                        status_review.get('purpose')!='STATUS_AVAILABILITY_ONLY' or
                        status_review.get('movement_authorized') is not False or
                        status_review.get('receiver_sha256')!=self.reader_selection['binary']['sha256'] or
                        status_review.get('agent_selection_sha256')!=digest(self.selected) or
                        set(status_review.get('source_hashes',{}))!=required or
                        any(status_review['source_hashes'][name]!=self.reader_selection['source_hashes'].get(name) for name in required)):
                    raise ValueError('Explicit Status source/window/artifact review required')
            if retention is not None:
                from tools.rover_control import RoverLimits
                from tools.rover_observation_stream import BOOTSTRAP_CONTRACT
                if (set(retention)!={'mode','purpose','reserved_stop_pairs','reserved_final_pairs','limits','bootstrap'} or
                        retention['mode']!='CREDIT_PHASED_V1' or retention['purpose']!='STATIONARY_ONLY' or
                        retention['reserved_stop_pairs']!=3 or retention['reserved_final_pairs']!=3 or
                        retention['bootstrap']!=BOOTSTRAP_CONTRACT or
                        self.reader_selection.get('helper_review',{}).get('bootstrap_contract')!=BOOTSTRAP_CONTRACT):
                    raise ValueError('Unreviewed phased retention selection')
                limits=RoverLimits(**retention['limits'])
                if limits.observation_max_age_s!=.5 or limits.call_timeout_s!=1.:
                    raise ValueError('Unreviewed stationary timing')
                if not {'tools/rover_identity_probe/phase_selection.hpp','tools/rover_control.py','tools/rover_ros2_adapter.py'}<=self.reader_selection['source_hashes'].keys():
                    raise ValueError('Missing phased producer/consumer pins')
            receiver_build_sha=self.reader_selection.get('helper_review',{}).get('receiver_build_review_sha256')
            receiver_build_valid=False
            if receiver_build_sha is not None:
                provenance=Path(self.reader_selection['provenance'])
                if not provenance.is_absolute():provenance=self.repo/provenance
                if (provenance.is_symlink() or receiver_build_sha!=self.reader_selection.get('provenance_sha256')
                        or hashlib.sha256(provenance.read_bytes()).hexdigest()!=receiver_build_sha):
                    raise ValueError('Receiver build review binding differs')
                build=json.loads(provenance.read_bytes())
                if (build.get('schema')!='tfg.rover-transport-build-review/1' or build.get('preparation_valid') is not True
                        or build.get('snapshot_unchanged') is not True
                        or build.get('artifacts',{}).get('receiver')!=self.reader_selection['binary']
                        or build.get('native_dependencies')!=self.reader_selection['native_dependencies']
                        or build.get('contract',{}).get('pure_cpp_contract')!='PASSED'
                        or build['contract'].get('dds_participant_created') is not False
                        or build['contract'].get('ros_initialized') is not False):
                    raise ValueError('Receiver build review contradicts preparation')
                if retention is not None and (build.get('retention_contract')!=RETENTION_CONTRACT or
                        build.get('phase_contract',{}).get('phase_selection_contract')!='PASSED' or
                        build['phase_contract'].get('dds_participant_created') is not False or
                        build['phase_contract'].get('ros_initialized') is not False):
                    raise ValueError('Phased receiver native contract review missing/contradictory')
                receiver_build_valid=True
            if retention is not None and not receiver_build_valid:raise ValueError('Phased receiver requires bound native build review')
            if status_variant and not receiver_build_valid:raise ValueError('Status receiver requires bound native build review')
            host_helpers={'tools/simulation_lifecycle.py','tools/reconciliation_environment.py'}
            host_review=self.reader_selection.get('helper_review',{}).get('host_source_review')
            if host_review is not None or host_helpers & self.reader_selection['source_hashes'].keys():
                # Reuse the reader's existing embedded helper review. No new
                # authorization or file-discovery path; pins are checked above
                # and this association is rechecked by start().
                if (not isinstance(host_review,dict) or host_review.get('schema')!='tfg.passive-host-helper-review/1' or
                        set(host_review.get('source_changes',{}))!=host_helpers or
                        host_review.get('native_binary_unchanged') is not True or
                        host_review.get('native_dependencies_unchanged') is not True or
                        any(host_review['source_changes'][k].get('after')!=self.reader_selection['source_hashes'].get(k)
                            for k in host_helpers)):
                    raise ValueError('Host lifecycle helper review missing/contradictory')
            review_sha=self.reader_selection.get('socket_helper_review_sha256')
            if (review_sha is not None or self.socket_helper_review is not None or
                    {'tools/rover_xrce_trace/monitor.py','tools/rover_xrce_trace/socket_inventory.py'} &
                    self.reader_selection['source_hashes'].keys()):
                if self.socket_helper_review is None or not isinstance(review_sha,str):
                    raise ValueError('Explicit pinned socket-helper-review required')
                if self.socket_helper_review.is_symlink():raise ValueError('Unsafe socket-helper-review')
                raw=self.socket_helper_review.read_bytes()
                if hashlib.sha256(raw).hexdigest()!=review_sha:
                    raise ValueError('Socket-helper-review hash differs')
                review=json.loads(raw)
                from .budget import SOCKET
                bounds={'query_timeout_s':SOCKET.query_timeout_s,'cooperative_s':SOCKET.cooperative_s,
                        'interval_s':SOCKET.interval_s,'samples':SOCKET.observations,
                        'row_bytes':SOCKET.row_bytes,'journal_bytes':SOCKET.journal_bytes}
                helpers={'tools/rover_xrce_trace/monitor.py','tools/rover_xrce_trace/socket_inventory.py'}
                if (review.get('schema')!='tfg.socket-helper-review/1' or
                        set(review.get('source_changes',{}))!=helpers or
                        not (review.get('binary_manifests_byte_identical_to_parent') is True or
                            review.get('binary_manifests_byte_identical_to_parent') is False and receiver_build_valid and
                            review.get('receiver_build_review_sha256')==receiver_build_sha) or
                        any(review.get(k)!=v for k,v in bounds.items()) or
                        any(review['source_changes'][k].get('after')!=self.reader_selection['source_hashes'].get(k)
                            for k in helpers)):
                    raise ValueError('Socket-helper-review source/budget association differs')
        elif self.reader_selection.get('schema')!='tfg.passive-reader-selection/1':
            raise ValueError('Unsupported reader selection')
    def command(self,name,argv,timeout):
        start=time.monotonic();rc=None;error=None
        with (self.root/(name+'.stdout')).open('xb') as out,(self.root/(name+'.stderr')).open('xb') as err:
            try:rc=subprocess.run(argv,cwd=self.repo,stdout=out,stderr=err,timeout=timeout,check=False).returncode
            except subprocess.TimeoutExpired:error='OUTER_TIMEOUT_NO_REPLAY'
            except BaseException as exc:
                # Preserve interrupted preparation evidence; execute_once owns close.
                write_once(self.root/(name+'-command.json'),{'command':argv,'return_code':rc,'error':type(exc).__name__,'duration_s':time.monotonic()-start})
                raise
        write_once(self.root/(name+'-command.json'),{'command':argv,'return_code':rc,'error':error,'duration_s':time.monotonic()-start})
        if error:raise TimeoutError(error)
        return rc
    def start(self):
        self.validate_reader()
        if self.reader_selection.get('schema')=='tfg.rover-transport-reader/1':
            # Before any opening: no repair/build/substitution after mismatch.
            code="import sys,json,hashlib,pathlib;v=json.loads(sys.argv[1]);p=pathlib.Path(v['binary']['path']);assert not p.is_symlink();assert hashlib.sha256(p.read_bytes()).hexdigest()==v['binary']['sha256'];[(lambda p,h: (p.is_absolute() and (p.is_relative_to('/opt/ros/humble') or p.is_relative_to('/root/ardu_ws/install') or p.is_relative_to('/usr/lib/x86_64-linux-gnu')) and hashlib.sha256(p.read_bytes()).hexdigest()==h) or sys.exit(2))(pathlib.Path(p),h) for p,h in v['native_dependencies'].items()]"
            if self.command('receiver-precheck',['docker','exec',self.selected['container_id'],'python3','-B','-c',code,json.dumps(self.reader_selection)],15):
                return {'status':'BLOCKED','reason':'Receiver/dependency hash differs; no opening'}
        self.command('start',['.venv/bin/python','-m','tools.simulation_lifecycle','start','--headless','--profile','two_drones_rover','--diagnostic-agent-manifest',str(self.manifest)],200)
        return json.loads((self.root/'start.stdout').read_bytes())
    def admit(self,owner):
        code="import sys,json;sys.path.insert(0,'/workspace/tfg');from tools.rover_xrce_trace.passive_trial import admit_from_prefix;print(json.dumps(admit_from_prefix(sys.argv[1])))"
        rc=self.command('admission',['docker','exec',self.selected['container_id'],'python3','-B','-c',code,'/tmp/tfg_diagnostic_agents/'+owner],15)
        if rc:return {'measurement_allowed':False,'reason':'Fresh essential supervision/resource check failed'}
        return json.loads((self.root/'admission.stdout').read_bytes())
    def reader(self,owner):
        p=self.reader_selection['binary'];path=p['path']
        if not Path(path).is_absolute() or not Path(path).is_relative_to('/tmp') or '..' in Path(path).parts:raise ValueError('Temporary pinned reader required')
        # Literal shell recipe, all variable data passed as arguments; no controls.
        script='source /opt/ros/humble/setup.bash; source /root/ardu_ws/install/setup.bash; exec "$1" --session-id "$2" --output "$3"'
        cid=self.selected['container_id'];directory='/tmp/tfg-rover-passive-validation-'+owner
        code="import sys,hashlib,pathlib;p=pathlib.Path(sys.argv[1]);assert not p.is_symlink();assert hashlib.sha256(p.read_bytes()).hexdigest()==sys.argv[2];pathlib.Path(sys.argv[3]).mkdir(mode=0o700)"
        if self.command('reader-prepare',['docker','exec',cid,'python3','-B','-c',code,path,p['sha256'],directory],10):
            return {'status':'BLOCKED','executed':False,'return_code':None}
        if self.reader_selection.get('schema')=='tfg.rover-transport-reader/1':
            stationary=self.reader_selection.get('retention_selection',{}).get('limits')
            status_window='status_window' in self.reader_selection
            code="import sys,json;sys.path.insert(0,'/workspace/tfg');from tools.rover_xrce_trace.passive_trial import capture_transport_from_prefix;print(json.dumps(capture_transport_from_prefix(*sys.argv[1:],stationary_limits="+repr(stationary)+",status_availability="+repr(status_window)+")))"
            script='source /opt/ros/humble/setup.bash; source /root/ardu_ws/install/setup.bash; exec python3 -B -c "$1" "$2" "$3" "$4" "$5"'
            rc=self.command('reader',['docker','exec','-e','TFG_SIM_PROJECT=Agentic_Drone_Mission_Control',cid,'bash','-c',script,'--',code,'/tmp/tfg_diagnostic_agents/'+owner,path,p['sha256'],directory],140)
            return {'executed':True,'return_code':rc,'status':'RECEIVER_DRIVER_RETURN_OBSERVED',
                    'coverage':'VERIFY_ORIGINAL_JOURNAL_RECEIVER_RECEIPT_AND_MONITOR_SEPARATELY'}
        rc=self.command('reader',['docker','exec','-e','TFG_SIM_PROJECT=Agentic_Drone_Mission_Control',cid,'bash','-c',script,'--',path,owner,directory+'/journal.jsonl'],140)
        return {'executed':True,'return_code':rc,'status':'READER_RETURN_OBSERVED','coverage':'VERIFY_JOURNAL_AND_RECEIPT_SEPARATELY'}
    def stop(self,owner):
        target=json.loads((self.repo/'missions/generated/diagnostic_agent_session.json').read_bytes())
        if target['descriptor']['lifecycle_id']!=owner or target['state']=='CLOSED':raise ValueError('Close target changed/already closed; inspect only')
        argv=['.venv/bin/python','-m','tools.simulation_lifecycle','stop','--headless','--profile','two_drones_rover']
        if target['state']=='UNCONFIRMED':
            # Only the failed start returned by THIS single attempt. Lifecycle
            # revalidates its original owner/environment under both mutexes.
            started=json.loads((self.root/'start.stdout').read_bytes())
            operation=started.get('operation',{})
            if (started.get('status')!='UNCONFIRMED' or operation.get('owner_id')!=owner
                    or operation.get('action')!='start' or operation.get('diagnostic_agent')!=target['descriptor']):
                raise ValueError('No same-attempt failed-start close receipt; inspect only')
            argv.extend(['--close-owner',owner])
        self.command('stop',argv,80)
        return json.loads((self.root/'stop.stdout').read_bytes())
    def post(self,owner):
        self.command('post-precheck',['.venv/bin/python','-m','tools.rover_xrce_trace.historical_disposition','diagnostic-precheck'],45)
        return json.loads((self.root/'post-precheck.stdout').read_bytes())


def selection_dry_run(repo,manifest,reader_manifest,*,socket_helper_review=None):
    """Host files only: never opens lifecycle, Docker, ROS or a receiver."""
    try:
        LocalPorts(repo,repo,manifest,reader_manifest,socket_helper_review=socket_helper_review)
        return {'selection_files_valid':True,'status':'BLOCKED',
                'reason':'Runtime artifacts/dependencies and fresh authorization not checked',
                'movement_authorized':False,'executed':False}
    except (ValueError,OSError,KeyError,TypeError) as exc:
        return {'selection_files_valid':False,'status':'BLOCKED','reason':str(exc),
                'movement_authorized':False,'executed':False}


if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser(description='Offline selection dry-run only; no session execution')
    parser.add_argument('--dry-run',action='store_true',required=True)
    parser.add_argument('--agent-manifest',required=True)
    parser.add_argument('--reader-manifest',required=True)
    parser.add_argument('--socket-helper-review')
    args=parser.parse_args()
    print(json.dumps(selection_dry_run(Path(__file__).resolve().parents[2],
        args.agent_manifest,args.reader_manifest,socket_helper_review=args.socket_helper_review),indent=2))
