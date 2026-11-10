"""Offline evidence joins and preparation for ONE explicitly authorized passive session.

No node, service, process or lifecycle is started by importing or evaluating this
module. Numerical support never creates frame_transform VERIFIED or movement consent.
"""
import argparse
import json
import math
from pathlib import Path

from tools.rover_xrce_trace.budget import SOCKET
from tools.rover_xrce_trace.monitor import capture_window

READER_BYTES=512*1024
TRACE_BYTES=2*1024*1024


def session_window(monitor,*,now,boot_id):
    window=capture_window(monitor,now=now,observed_boot_id=boot_id,outer_capture_s=140,stop_s=60,passive_measurement=True)
    s=monitor['socket_inventory']
    future_rows=math.ceil(200/SOCKET.interval_s)+1
    projected=s['journal_bytes_written']+future_rows*SOCKET.row_bytes+READER_BYTES+TRACE_BYTES
    if s['snapshots']+future_rows>SOCKET.observations or projected>SOCKET.journal_bytes:
        raise ValueError('Combined reader/trace/socket worst-case does not fit existing 16 MiB budget')
    return {**window,'projected_total_bytes':projected,'aggregate_limit_bytes':SOCKET.journal_bytes,
        'future_socket_rows':future_rows,'reader_limit_bytes':READER_BYTES,'trace_limit_bytes':TRACE_BYTES,
        'duration_s':120,'max_retained_samples':20,'opening_authorized':False,'movement_authorized':False}


def _finite(value):
    if type(value) not in (float,int) or not math.isfinite(value):raise ValueError('Nonfinite/missing numeric evidence')
    return float(value)


def geodetic_enu(latitude,longitude,origin_latitude,origin_longitude):
    """WGS84 ECEF then tangent ENU at zero ellipsoid height; horizontal only.

    No claim that the producer actually uses this datum or shares an origin.
    Altitude is deliberately excluded (AP_DDS source has an altitude-frame TODO).
    """
    vals=list(map(_finite,(latitude,longitude,origin_latitude,origin_longitude)))
    if any(abs(v)>limit for v,limit in zip(vals,(90,180,90,180))):raise ValueError('Invalid geodetic coordinate')
    def ecef(lat,lon):
        lat,lon=map(math.radians,(lat,lon));a=6378137.;e2=6.6943799901413165e-3
        n=a/math.sqrt(1-e2*math.sin(lat)**2)
        return (n*math.cos(lat)*math.cos(lon),n*math.cos(lat)*math.sin(lon),n*(1-e2)*math.sin(lat))
    x=ecef(*vals[:2]);o=ecef(*vals[2:]);dx,dy,dz=(a-b for a,b in zip(x,o));p,l=map(math.radians,vals[2:])
    return (-math.sin(l)*dx+math.cos(l)*dy,
            -math.sin(p)*math.cos(l)*dx-math.sin(p)*math.sin(l)*dy+math.cos(p)*dz)


def quantization_radius(latitude,lat_resolution_deg,lon_resolution_deg):
    """Worst half-cell diagonal, not sensor accuracy. Resolution must be sourced."""
    lat=_finite(latitude);a=_finite(lat_resolution_deg);b=_finite(lon_resolution_deg)
    if abs(lat)>90 or min(a,b)<=0:raise ValueError('Unknown/invalid geodetic resolution')
    return math.hypot(111700.*a/2,111700.*math.cos(math.radians(max(0,abs(lat)-a/2)))*b/2)


def evaluate_transform(dataset):
    r={'state':'UNKNOWN','movement_authorized':False,'frame_transform_verified':False,'reasons':[]}
    try:
        session=dataset['session_id'];train=dataset['fit'];check=dataset['holdout']
        if not session or len(train)!=2 or not check:raise ValueError('Need exactly 2 fit anchors and independent holdout')
        if set(v['observation_id'] for v in train)&set(v['observation_id'] for v in check):
            raise ValueError('Fit observations reused for validation')
        ids=[v['observation_id'] for v in train+check]
        if len(ids)!=len(set(ids)):raise ValueError('Duplicate observation IDs')
        bound=_finite(dataset['required_error_bound_m']);skew=_finite(dataset['max_pair_skew_s'])
        if min(bound,skew)<=0:raise ValueError('Explicit positive error/skew criteria required')
        for v in train+check:
            if v['session_id']!=session or v['source_frame']!=dataset['source_frame'] or v['target_frame']!=dataset['target_frame']:
                raise ValueError('Mixed session or coordinate frames')
            if not v['source_ref'] or not v['target_ref'] or not v['uncertainty_ref'] or not v['resolution_ref']:
                raise ValueError('Missing source/uncertainty/resolution provenance')
            if not v['clock_contract_ref'] or v['source_clock']!=v['target_clock'] or not v['source_clock']:
                raise ValueError('No comparable source clock contract')
            if abs(_finite(v['source_stamp_s'])-_finite(v['target_stamp_s']))>skew:
                raise ValueError('Source timestamps are not contemporaneous')
            if abs(_finite(v['source_receipt_s'])-_finite(v['target_receipt_s']))>skew:
                raise ValueError('Correspondence is not contemporaneous')
            for p in ('source_xy_m','target_xy_m'):
                if len(v[p])!=2:raise ValueError('Two dimensional points required')
                for x in v[p]:_finite(x)
            u=_finite(v['uncertainty_radius_m']);q=_finite(v['quantization_radius_m'])
            if min(u,q)<0:raise ValueError('Negative uncertainty')
            if u+q>=bound:
                r['state']='REJECTED';raise ValueError('Requested bound cannot resolve the source uncertainty/quantization')
        def baseline(a,b,p):return math.dist(a[p],b[p])
        distinguishable=any(min(baseline(a,b,'source_xy_m'),baseline(a,b,'target_xy_m'))>
            a['uncertainty_radius_m']+a['quantization_radius_m']+b['uncertainty_radius_m']+b['quantization_radius_m']
            for i,a in enumerate(train) for b in train[i+1:])
        if not distinguishable:raise ValueError('Stationary/coincident references do not observe yaw/scale')
        combined=sum(v['uncertainty_radius_m']+v['quantization_radius_m'] for v in train)
        source_baseline=baseline(*train,'source_xy_m');target_baseline=baseline(*train,'target_xy_m')
        if combined>=min(source_baseline,target_baseline):raise ValueError('Uncertainty hides calibration direction')
        yaw_bound=math.asin(combined/source_baseline)+math.asin(combined/target_baseline)
        anchor_bound=combined/2
        n=len(train);sx=sum(v['source_xy_m'][0] for v in train)/n;sy=sum(v['source_xy_m'][1] for v in train)/n
        tx=sum(v['target_xy_m'][0] for v in train)/n;ty=sum(v['target_xy_m'][1] for v in train)/n
        dot=cross=spread=0.
        for v in train:
            x,y=v['source_xy_m'];a,b=v['target_xy_m'];x-=sx;y-=sy;a-=tx;b-=ty
            dot+=x*a+y*b;cross+=x*b-y*a;spread+=x*x+y*y
        if spread==0 or math.hypot(dot,cross)<=1e-15:raise ValueError('Degenerate planar transform')
        angle=math.atan2(cross,dot);c,s=math.cos(angle),math.sin(angle);translation=(tx-c*sx+s*sy,ty-s*sx-c*sy)
        residuals=[]
        for v in check:
            x,y=v['source_xy_m'];pred=(translation[0]+c*x-s*y,translation[1]+s*x+c*y)
            residuals.append({'observation_id':v['observation_id'],'residual_m':math.dist(pred,v['target_xy_m']),
                'measurement_bound_m':v['uncertainty_radius_m']+v['quantization_radius_m'],
                'calibration_bound_m':anchor_bound+2*math.hypot(x-sx,y-sy)*math.sin(yaw_bound/2)})
        r.update(state='NUMERICALLY_SUPPORTED_ONLY',rotation_rad=angle,translation_xy_m=translation,holdout=residuals,
                 yaw_uncertainty_bound_rad=yaw_bound,calibration_points=len(train),validation_points=len(check),unobserved_dofs=['vertical datum','full 3D extrinsics'],
                 acceptance='SOURCE_IDENTITY_AND_FRAME_CONVENTIONS_REQUIRE_SEPARATE_EVIDENCE')
        if any(v['residual_m']+v['measurement_bound_m']+v['calibration_bound_m']>bound for v in residuals):
            r['state']='REJECTED';r['reasons'].append('Independent holdout exceeds error budget')
    except (KeyError,TypeError,ValueError,IndexError) as exc:r['reasons'].append(str(exc))
    return r


def identity_records(lines):
    rows=[];sequences={}
    for line in lines:
        if 'TFG_IDENTITY_TRACE ' not in line:continue
        v=json.loads(line.split('TFG_IDENTITY_TRACE ',1)[1]);p=(v['pid'],v['process_start_ticks'],v['boot_id'])
        if type(v['pid']) is not int or v['pid']<=0 or not str(v['process_start_ticks']).isdigit() or not v['boot_id']:
            raise ValueError('Unknown identity process context')
        if any(type(v[k]) is not int or v[k]<=0 for k in ('wall_unix_ns','steady_ns')):raise ValueError('Unknown identity observation times')
        if v['schema']!='tfg.identity-trace/1' or v.get('incomplete'):raise ValueError('Incomplete identity trace')
        if type(v['sequence']) is not int or not 0<v['sequence']<128:raise ValueError('Invalid/capped identity sequence')
        seen=sequences.setdefault(p,set())
        if v['sequence'] in seen:raise ValueError('Repeated identity sequence')
        seen.add(v['sequence']);rows.append(v)
    for seen in sequences.values():
        if seen!=set(range(1,max(seen)+1)):raise ValueError('Truncated/mixed identity trace')
    return rows


def correlate_parameter(reply,events,status_writer):
    """Legacy public service metadata cannot attribute a received response.

    Humble's rmw_request_id_t does not carry the response SampleInfo identities
    here; the old agent field was read after a mutable DataWriter::write. Even
    nonzero equal GUIDs cannot repair that missing per-response provenance.
    """
    r={'state':'UNKNOWN','movement_authorized':False,'source_association_verified':False,
        'received_values':reply.get('values'),'value_attribution':'UNVERIFIED',
        'native_exchange':inspect_rpc_exchange(events,status_writer)}
    try:
        import re
        guid=reply['request_writer_guid']
        if not isinstance(guid,str) or not re.fullmatch('[0-9a-f]{32}',guid) or set(guid)=={'0'}:
            raise ValueError('Requester GUID unavailable; sequence/endpoint alone cannot attribute a parameter response')
        raise ValueError('Legacy metadata lacks received SampleInfo identities; a GUID/sequence coincidence cannot attribute parameter values')
    except (KeyError,TypeError,ValueError) as exc:r['reason']=str(exc)
    return r


def inspect_rpc_exchange(events,status_writer):
    """What native metadata proves even when the public service GUID is unset."""
    r={'state':'UNKNOWN','parameter_value_attributed':False}
    try:
        ctx=('pid','process_start_ticks','boot_id','client_instance','client_key','session_id')
        created=[e for e in events if e.get('event')=='replier_created' and
            e.get('request_topic')=='rq/ap/v3/get_parametersRequest' and all(str(e.get(k))==str(status_writer.get(k)) for k in ctx)]
        if len(created)!=1:raise ValueError('No unique committed parameter replier in the Status context')
        c=created[0];scope=ctx+('attempt','object_id','entity_kind')
        if (c.get('reply_topic')!='rr/ap/v3/get_parametersReply' or c.get('domain')!=status_writer['domain']
                or c.get('request_type')!='rcl_interfaces::srv::dds_::GetParameters_Request_'
                or c.get('reply_type')!='rcl_interfaces::srv::dds_::GetParameters_Response_'):
            raise ValueError('Native replier type/domain differs from parameter contract')
        rows=[e for e in events if all(e.get(k)==c[k] for k in scope)]
        committed=[e for e in rows if e['event']=='entity_commit' and e.get('committed') is True]
        req=[e for e in rows if e['event']=='rpc_request' and e.get('accepted') is True]
        rep=[e for e in rows if e['event']=='rpc_reply' and e.get('accepted') is True]
        if len(committed)!=1 or len(req)!=1 or len(rep)!=1:raise ValueError('Request/response context incomplete or ambiguous')
        if not c['sequence']<committed[0]['sequence']<req[0]['sequence']<rep[0]['sequence']:raise ValueError('RPC order contradiction')
        r.update(state='NATIVE_REPLIER_AND_EXCHANGE_CONTEXT_OBSERVED',context={k:c[k] for k in scope},
            server_request_reader_guid=c.get('reader_guid'),server_reply_writer_guid=c.get('writer_guid'),
            request_metadata=req[0],reply_metadata=rep[0],
            limitation='Legacy reply field was read AFTER write; do not equate it with the request writer or a response received by this client')
    except (KeyError,ValueError,TypeError) as e:r['reason']=str(e)
    return r


def correlate_rpc_v2(request,reply,native_events,status_writer):
    """Exact per-response Fast DDS metadata contract; unavailable in legacy take().

    request/response inputs require instrumented native client metadata, not graph
    candidates or the zero public rmw_request_id_t GUID. No such capture exists yet.
    """
    r={'state':'UNKNOWN','movement_authorized':False,'source_association_verified':False}
    try:
        def key(v):
            import re
            guid=v['writer_guid'];high=v['sequence_high'];low=v['sequence_low']
            if (not re.fullmatch('[0-9a-f]{32}',guid) or set(guid)=={'0'} or type(high) is not int or not 0<=high<2**31
                    or type(low) is not int or not 0<=low<2**32 or not (high or low)):
                raise ValueError('Invalid sample identity')
            return guid,high,low
        identity=key(request['request_identity'])
        if request['client_instance']!=reply['client_instance'] or request['session_id']!=reply['session_id']:
            raise ValueError('Different native client/session')
        if not request.get('client_process') or request['client_process']!=reply.get('client_process'):
            raise ValueError('Native client process differs or is unknown')
        process=request['client_process']
        if (type(process.get('pid')) is not int or process['pid']<=0 or type(process.get('start_ticks')) is not int
                or process['start_ticks']<0 or not isinstance(process.get('boot_id'),str) or not process['boot_id']):
            raise ValueError('Native client incarnation missing')
        if process['boot_id']!=status_writer['boot_id']:raise ValueError('Client/agent process clock boot differs')
        if any(type(request.get(k)) is not int or request[k]<=0 for k in ('sent_steady_ns',)) or type(reply.get('received_steady_ns')) is not int:
            raise ValueError('Native reception clock missing')
        if reply.get('metadata_source')!='FASTDDS_SAMPLE_INFO' or key(reply['related_identity'])!=identity:
            raise ValueError('Response not related to this exact request')
        if not request['sent_steady_ns']<=reply['received_steady_ns']:raise ValueError('Response predates request')
        ctx=('pid','process_start_ticks','boot_id','client_instance','client_key','session_id')
        rows=[e for e in native_events if e.get('rpc_contract')=='FASTDDS_RPC_IDENTITIES_V2' and all(str(e.get(k))==str(status_writer[k]) for k in ctx)]
        req=[e for e in rows if e['event']=='rpc_request' and e.get('accepted') and key(e['request_identity'])==identity]
        rep=[e for e in rows if e['event']=='rpc_reply' and e.get('accepted') and key(e['request_identity'])==identity and key(e['written_identity'])==key(reply['sample_identity'])]
        if len(req)!=1 or len(rep)!=1:raise ValueError('Missing/ambiguous exact native RPC association')
        if any(req[0][k]!=rep[0][k] for k in ('attempt','object_id','entity_kind','replier_reader_guid','replier_writer_guid')):raise ValueError('Replier generation differs')
        scope=ctx+('attempt','object_id','entity_kind')
        created=[e for e in native_events if e.get('event')=='replier_created' and all(e.get(k)==rep[0][k] for k in scope)]
        committed=[e for e in native_events if e.get('event')=='entity_commit' and e.get('committed') is True and all(e.get(k)==rep[0][k] for k in scope)]
        if len(created)!=1 or len(committed)!=1:raise ValueError('Replier not uniquely committed')
        c=created[0]
        if (c.get('request_topic')!='rq/ap/v3/get_parametersRequest' or c.get('reply_topic')!='rr/ap/v3/get_parametersReply'
                or c.get('domain')!=status_writer['domain'] or c.get('writer_guid')!=rep[0]['replier_writer_guid']
                or c.get('reader_guid')!=rep[0]['replier_reader_guid']
                or rep[0]['written_identity']['writer_guid']!=c.get('writer_guid')
                or c.get('request_type')!='rcl_interfaces::srv::dds_::GetParameters_Request_'
                or c.get('reply_type')!='rcl_interfaces::srv::dds_::GetParameters_Response_'
                or not c['sequence']<committed[0]['sequence']<req[0]['sequence']<rep[0]['sequence']):
            raise ValueError('Service route/order/related identity mismatch')
        r.update(state='PER_RESPONSE_METADATA_TO_XRCE_OBSERVED',context={k:rep[0][k] for k in ctx})
    except (KeyError,TypeError,ValueError) as e:r['reason']=str(e)
    return r


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('action',choices=['evaluate-transform','capture-window','analyze-reader','analyze-transport-stream'])
    p.add_argument('input',type=Path);p.add_argument('--now',type=float);p.add_argument('--boot-id');p.add_argument('--receipt',type=Path);p.add_argument('--trace',type=Path);p.add_argument('--monitor',type=Path)
    p.add_argument('--closure-evidence',type=Path,help='Offline independent cleanup and active-observation evidence; never completes an INCOMPLETE monitor')
    p.add_argument('--launch-log',type=Path,help='Same-session retained launch log for instantiated odometry route verification')
    p.add_argument('--sockets',type=Path,help='Same-session bounded socket journal; no current collection')
    a=p.parse_args()
    try:
        if a.action=='analyze-transport-stream':result=analyze_transport_stream(a.input,a.receipt,a.trace,a.monitor,sockets=a.sockets,launch_log=a.launch_log)
        elif a.action=='analyze-reader':result=analyze_reader(a.input,a.receipt,a.trace,a.monitor,
            closure_evidence=json.loads(a.closure_evidence.read_bytes()) if a.closure_evidence else None,launch_log=a.launch_log,sockets=a.sockets)
        else:
            v=json.loads(a.input.read_bytes())
            result=evaluate_transform(v) if a.action=='evaluate-transform' else session_window(v,now=a.now,boot_id=a.boot_id)
    except (ValueError,KeyError,TypeError,OSError) as exc:result={'state':'BLOCKED','reason':str(exc)}
    print(json.dumps(result,allow_nan=False,indent=2))





def read_journal(path,receipt_path):
    """New validation reader format only; never substitutes the historical /3 reader."""
    data=Path(path).read_bytes()
    if len(data)>READER_BYTES or not data.endswith(b'\n'):raise ValueError('Oversized/truncated reader journal')
    rows=[json.loads(line) for line in data.splitlines()]
    if len(rows)<2 or rows[0].get('kind')!='header' or rows[-1].get('kind')!='footer':
        raise ValueError('Missing explicit reader header/footer')
    header,footer=rows[0],rows[-1];session=header['session_id']
    receipt=json.loads(Path(receipt_path).read_bytes())
    if receipt.get('schema')!='tfg.rover-passive-validation-receipt/1' or receipt.get('session_id')!=session or receipt.get('reader_closed') is not True:
        raise ValueError('Missing/contradictory durable receipt')
    if footer.get('session_id')!=session or footer.get('reader_closed') is not True or header.get('probe_session_id')!=session:
        raise ValueError('Reader session/closure mismatch')
    counts={};last=None
    for row in rows:
        if row.get('schema')!='tfg.rover-passive-validation/1' or row.get('status')!='BLOCKED' or row.get('movement_authorized') is not False:
            raise ValueError('Unexpected authority/schema')
        if type(row.get('receipt_wall_ns')) is not int:raise ValueError('Missing wall reception time')
        now=row['receipt_steady_ns']
        if type(now) is not int or last is not None and now<last:raise ValueError('Receipt clock reversal')
        last=now
        if row['kind']=='sample':counts[row['topic']]=counts.get(row['topic'],0)+1
    if counts!=footer['counts'] or sum(counts.values())>20:raise ValueError('Contradictory retained counts')
    return {'state':'BLOCKED','session_id':session,'reader_closed':True,'counts':counts,'records':rows,
            'movement_authorized':False,'source_association_verified':False}


def correlate_bridge(sample,events,session_processes):
    """Sample GID -> publisher object in the bridge PID; not Gazebo entity proof."""
    r={'state':'UNKNOWN','movement_authorized':False,'model_identity_verified':False}
    try:
        if sample.get('from_intra_process') is not False:raise ValueError('Intra-process/unknown sample')
        gid=sample['message_gid']
        if len(gid)!=48 or not any(c!='0' for c in gid):raise ValueError('Invalid sample GID')
        matches=[e for e in events if e['event']=='bridge_subscription' and e['gid']==gid and e['rmw']==sample['rmw']]
        if len(matches)!=1:raise ValueError('Missing/ambiguous actual bridge publisher')
        v=matches[0]
        if (v['ros_topic'],v['gz_topic'],v['ros_type'],v['gz_type'])!=('/rover1/odometry','/model/rover1/odometry','nav_msgs/msg/Odometry','gz.msgs.Odometry'):
            raise ValueError('Bridge route/type differs')
        publishers=[e for e in events if e['event']=='bridge_publisher' and all(e.get(k)==v[k] for k in
            ('pid','process_start_ticks','boot_id','gid','rmw','ros_topic','gz_topic','ros_type','gz_type','config_file'))]
        if len(publishers)!=1 or publishers[0]['sequence']>=v['sequence']:raise ValueError('Bridge publisher/subscription creation inconsistent')
        owners=[p for p in session_processes if str(p['pid'])==str(v['pid']) and str(p['start_ticks'])==str(v['process_start_ticks']) and p['boot_id']==v['boot_id']]
        if len(owners)!=1 or not owners[0].get('verified_overlay_library'):raise ValueError('Bridge process/maps not accredited in this session')
        if not v['config_file']:raise ValueError('Unknown effective bridge config selector')
        r.update(state='SAMPLE_TO_BRIDGE_PROCESS_OBSERVED',process=owners[0],configuration_selector=v['config_file'],gz_topic=v['gz_topic'])
    except (ValueError,KeyError,TypeError) as exc:r['reason']=str(exc)
    return r


def _terminal_model_gap(current,session,evidence):
    """Offline prefix assessment only; never upgrades the monitor or a precheck.

    The sole error was appended by the pinned monitor's FINAL exit check after
    the reader. Require independent protected cleanup and an active observation
    of the same library/process context. All other failures remain rejected.
    """
    try:
        start,stop,target,active,cleanup=(evidence[k] for k in
            ('start_operation','stop_operation','target','active_observation','cleanup'))
        if (current.get('capture_semantics')!='SEPARATE_CHANNELS_V2'
                or current.get('phase')!='INCOMPLETE' or current.get('core_capture_complete') is not False
                or current.get('capture_complete') is not False or current.get('closure_requested') is not True
                or current.get('errors')!=['Model server exit not observed by monitor']):return False
        if (start.get('state')!='FINISHED' or start.get('action')!='start' or start.get('owner_id')!=session
                or stop.get('state')!='FINISHED' or stop.get('action')!='stop'
                or target.get('state')!='CLOSED' or target.get('closed_by')!=stop.get('owner_id')
                or target.get('descriptor')!=start.get('diagnostic_agent')
                or stop.get('diagnostic_close_target')!=target.get('descriptor')):return False
        if (cleanup.get('success') is not True or any(cleanup.get(k)!=[] for k in
                ('remaining','errors','unattributed_auxiliaries'))):return False
        observed=active['monitor']
        if (active.get('lifecycle_id')!=session or observed.get('lifecycle_id')!=session
                or observed.get('phase')!='OBSERVING' or observed.get('errors')!=[]
                or not current['started_monotonic']<=observed['observation_monotonic']<current['finished_monotonic']):return False
        for role in ('agent','identity_bridge','model_source'):
            a,b=observed[role],current[role]
            if any(a[k]!=b[k] for k in ('pid','start_ticks','boot_id','library_sha256')):return False
        model=current['model_source']
        if not any(v.get('pid')==model['pid'] and v.get('start_ticks')==model['start_ticks'] for v in cleanup.get('signals',[])):return False
        return (observed['model_source']['verified_overlay_library'] is True
                and observed['model_source']['boot_id']==current['monitor']['boot_id'])
    except (KeyError,TypeError,ValueError):return False


def analyze_reader(journal,receipt,trace,monitor,*,closure_evidence=None,launch_log=None,sockets=None):
    from tools.rover_xrce_trace.analyze import analyze
    report=read_journal(journal,receipt);rows=report.pop('records')
    import hashlib
    report['journal_sha256']=hashlib.sha256(Path(journal).read_bytes()).hexdigest()
    report['parameters']={'state':'UNKNOWN','reason':'No uniquely correlated Status and parameter response'}
    report['odometry']={'state':'UNKNOWN','reason':'No attributed bridge sample'}
    data=Path(trace).read_bytes()
    if len(data)>TRACE_BYTES:raise ValueError('Trace budget exhausted')
    lines=data.decode().splitlines();events=identity_records(lines);writers=analyze(lines)
    current=json.loads(Path(monitor).read_bytes())
    complete=(not current.get('errors') and current.get('phase')=='CLOSED' and
        (current.get('capture_complete') is True or current.get('capture_semantics')=='SEPARATE_CHANNELS_V2' and current.get('core_capture_complete') is True))
    prefix=(closure_evidence is not None and _terminal_model_gap(current,report['session_id'],closure_evidence))
    if current.get('lifecycle_id')!=report['session_id'] or not (complete or prefix):
        raise ValueError('No coherent same-session monitor closure')
    report['analysis_scope']='SUPERVISED_PREFIX_WITH_UNOBSERVED_TERMINAL_MODEL_EXIT' if prefix else 'CLOSED_CORE_TRACE'
    report['capture_complete']=current.get('capture_complete') is True
    if any(not current['started_monotonic']<=e['steady_ns']/1e9<=current['finished_monotonic'] for e in events):raise ValueError('Identity trace outside same monitor window')
    samples=[r for r in rows if r['kind']=='sample']
    report['monitor_channels']={k:current.get(k,'UNKNOWN') for k in ('capture_complete','core_capture_complete','socket_capture_complete')}
    clock_boot=rows[0]['boot_id']
    if current['monitor']['boot_id']!=clock_boot:raise ValueError('Mixed execution clocks')
    lower,upper=current['started_monotonic'],current['finished_monotonic']
    if any(not lower<=r['receipt_steady_ns']/1e9<=upper for r in rows):raise ValueError('Reader outside observed monitor window')
    report['dds_samples']=[]
    for sample in samples:
        if sample['topic'].startswith('/world/'):continue
        matches=[w for w in writers['correlations'] if w['rmw_gid']==sample['message_gid'] and
            w['rmw_identifier']==sample['rmw'] and w['topic']=='rt'+sample['topic']] if writers['trace_valid'] else []
        report['dds_samples'].append({'topic':sample['topic'],'state':'EXACT_NATIVE_WRITER_CONTEXT' if len(matches)==1 else 'UNKNOWN',
            'context':matches[0] if len(matches)==1 else None,'full_identity_verified':False})
    status=[r for r in samples if r['topic']=='/ap/v3/status' and r.get('from_intra_process') is False]
    status_writer=None
    if writers['trace_valid'] and len(status)==1:
        candidates=[w for w in writers['correlations'] if w['rmw_gid']==status[0]['message_gid'] and
            w['rmw_identifier']==status[0]['rmw'] and w['topic']=='rt/ap/v3/status']
        replies=[r for r in rows if r['kind']=='parameter_reply' and r['endpoint']=='/ap/v3/get_parameters']
        if len(candidates)==1:
            status_writer=candidates[0]
            report['intended_transport_routes']=transport_routes(events,candidates[0])
            if len(replies)==1:report['parameters']=correlate_parameter(replies[0],events,candidates[0])
    bridge=current.get('identity_bridge');odom=[r for r in samples if r['topic']=='/rover1/odometry']
    if bridge and odom:
        report['odometry_samples']=[correlate_bridge(r,events,[bridge]) for r in odom]
        report['odometry']={'state':'SAMPLE_TO_BRIDGE_PROCESS_OBSERVED' if all(r['state']=='SAMPLE_TO_BRIDGE_PROCESS_OBSERVED' for r in report['odometry_samples']) else 'UNKNOWN',
            'model_identity_verified':False}
    report['model_source']={'state':'UNKNOWN','reason':'No attributed model source trace',
        'identity_verified':False,'movement_authorized':False}
    try:
        models=model_records(lines)
        source=current.get('model_source')
        if models:
            if (not source or source.get('verified_overlay_library') is not True
                    or source.get('boot_id')!=current.get('monitor',{}).get('boot_id')):
                raise ValueError('Model library observation unavailable')
            if any(r.get('lifecycle_id')!=report['session_id'] or not lower<=r['steady_ns']/1e9<=upper for r in models):
                raise ValueError('Model source belongs to another session/window')
            report['model_source']=assess_model_source(models,source)
            report['model_entities']=correlate_model_entities(report['model_source'],rows)
            if launch_log is not None:
                report['odometry_model']=correlate_odometry_model(report,rows,current['model_source'],Path(launch_log).read_text())
    except (KeyError,ValueError,TypeError) as exc:
        report['model_source']['reason']=str(exc)
    if sockets is not None:
        from tools.rover_xrce_trace.socket_inventory import analyze_series
        if status_writer is None:report['socket_series']={'state':'UNKNOWN','reason':'No unique same-session Status writer'}
        else:
            entity=report.get('odometry_model',{}).get('model_entity')
            sends=[e for e in models if e['event']=='fdm_send' and entity is not None and e['model_entity']==entity] if report['model_source']['state']=='MODEL_SOURCE_CONTEXT_OBSERVED_ONLY' else []
            report['socket_series']=analyze_series(sockets,current['socket_inventory'],status_writer,report['session_id'],
                receipt_wall_ns=[r['receipt_wall_ns'] for r in status],fdm_sends=sends,model=current.get('model_source'))
    report['frame_transform']={'state':'UNKNOWN','reason':'Needs sourced contemporary correspondences, uncertainty, fit and independent holdout'}
    return report


def analyze_transport_stream(journal,receipt,trace,monitor,*,sockets=None,launch_log=None):
    """Same-session offline consumer for the live adapter's bounded C++ source.

    Historical metadata is not passed through a fake live clock/identity guard.
    Receiver closure, monitor closure and per-response attribution stay separate.
    """
    import hashlib
    from tools.rover_observation_stream import SCHEMA,MAX_BYTES,MAX_LINE,MAX_RECORDS
    from tools.rover_xrce_trace.analyze import analyze
    result={'state':'BLOCKED','identity_verified':False,'movement_authorized':False,
            'parameters_link':{'state':'UNKNOWN'},'receiver_closed':False,'monitor_complete':False}
    try:
        data=Path(journal).read_bytes()
        if len(data)>MAX_BYTES or not data.endswith(b'\n'):raise ValueError('Truncated/oversized receiver stream')
        lines=data.splitlines(keepends=True)
        if not 2<=len(lines)<=MAX_RECORDS or any(len(line)>MAX_LINE for line in lines):raise ValueError('Stream record bounds')
        rows=[json.loads(line,parse_constant=lambda value:(_ for _ in ()).throw(ValueError('Nonfinite JSON'))) for line in lines];head,last=rows[0],rows[-1];owner=head['session_id'];process=head['process']
        if head['event']!='header' or last['event']!='footer' or last.get('reader_closed') is not True:raise ValueError('Missing receiver header/footer')
        if any(r.get('schema')!=SCHEMA or r.get('session_id')!=owner or r.get('client_process')!=process
               or r.get('sequence')!=i or r.get('identity_verified') is not False or r.get('movement_authorized') is not False for i,r in enumerate(rows,1)):
            raise ValueError('Receiver context/generation/sequence contradiction')
        close=json.loads(Path(receipt).read_bytes());current=json.loads(Path(monitor).read_bytes())
        if (close.get('status')!='RECEIVER_CLOSED' or close.get('session_id')!=owner or close.get('receiver_process')!=process or close.get('return_code')!=0
                or close.get('footer_sha256')!=hashlib.sha256(lines[-1]).hexdigest()):raise ValueError('No actual coherent receiver wait/closure receipt')
        if current['lifecycle_id']!=owner or current['monitor']['boot_id']!=process['boot_id']:raise ValueError('Monitor/receiver execution differs')
        if any(not current['started_monotonic']<=r['receipt_steady_ns']/1e9<=current['finished_monotonic'] for r in rows):raise ValueError('Receiver outside monitor observation interval')
        samples=[r for r in rows if r['event']=='sample'];counts={k:sum(r['topic']==k for r in samples) for k in ('/ap/v3/status','/rover1/odometry')}
        if last['counts']!=counts or sum(counts.values())>20 or any(v>10 for v in counts.values()):raise ValueError('Receiver sample count contradiction')
        result.update(session_id=owner,receiver_closed=True,counts=counts,monitor_complete=current.get('capture_complete') is True,
            monitor_channels={k:current.get(k) for k in ('phase','errors','core_capture_complete','socket_capture_complete')})
        if current.get('phase')!='CLOSED' or current.get('errors') or current.get('core_capture_complete') is not True:
            raise ValueError('Native/core supervision did not close coherently; receiver closure is separate')
        raw=Path(trace).read_bytes()
        if len(raw)>TRACE_BYTES:raise ValueError('Native trace byte budget')
        text=raw.decode().splitlines();writers=analyze(text);events=identity_records(text)
        if any(not current['started_monotonic']<=e['steady_ns']/1e9<=current['finished_monotonic'] for e in events):raise ValueError('Native metadata outside same monitor window')
        status=[r for r in samples if r['topic']=='/ap/v3/status'];matches=[]
        for sample in status:
            m=sample['sample']
            if m.get('incomplete') or m.get('from_intra_process'):raise ValueError('Invalid Status sample metadata')
            matches.extend(w for w in writers['correlations'] if w['topic']=='rt/ap/v3/status' and w['rmw_gid']==m['message_publisher_gid'] and w['rmw_identifier']==m['rmw_implementation_identifier'])
        writer=matches[0] if matches and all(w==matches[0] for w in matches) and writers['trace_valid'] else None
        if writer and any(str(writer[a])!=str(current['agent'][b]) for a,b in
                [('pid','pid'),('process_start_ticks','start_ticks'),('boot_id','boot_id')]):
            raise ValueError('Native writer agent differs from pinned monitor process')
        requests=[r for r in rows if r['event']=='rpc_request' and r.get('accepted') is True]
        replies=[r for r in rows if r['event']=='rpc_reply']
        if len(requests)==len(replies)==1 and writer:
            result['parameters_received']=replies[0].get('values')
            result['parameters_link']=correlate_rpc_v2(requests[0],replies[0],events,writer)
            values=result['parameters_received'] or {}
            result['parameters_value_validity']=('TYPED_PROFILE_VALUES' if type(values.get('MAV_SYSID')) is int and 1<=values['MAV_SYSID']<=255 and type(values.get('DDS_USE_NS')) is int and values['DDS_USE_NS']==1 else 'UNSET_OR_UNEXPECTED_PROFILE_VALUES')
        bridged=[]
        for row in samples:
            if row['topic']!='/rover1/odometry':continue
            sample=row['sample'];metadata={'message_gid':sample['message_publisher_gid'],'rmw':sample['rmw_implementation_identifier'],'from_intra_process':sample['from_intra_process']}
            bridged.append(correlate_bridge(metadata,events,[current['identity_bridge']]))
        result['odometry_samples']=bridged
        models=model_records(text);source=current.get('model_source')
        if source and source.get('verified_overlay_library') is True:
            if any(e['lifecycle_id']!=owner or not current['started_monotonic']<=e['steady_ns']/1e9<=current['finished_monotonic'] for e in models):raise ValueError('Mixed model trace execution/window')
            result['model_source']=assess_model_source(models,source)
            catalogs=[r for r in rows if r['event']=='scene_catalog' and r.get('received') is True]
            if len(catalogs)==1 and result['model_source']['state']=='MODEL_SOURCE_CONTEXT_OBSERVED_ONLY':
                catalog={v['id']:v['name'] for v in catalogs[0]['body']}
                if len(catalog)!=len(catalogs[0]['body']):raise ValueError('Ambiguous scene catalog')
                result['model_entities']={'state':'EXACT_RUNTIME_CATALOG_PLUGIN_CONTEXT_OBSERVED','entities':[
                    {'model_entity':m['model_entity'],'catalog_label':catalog[m['model_entity']]} for m in result['model_source']['models']]}
                if launch_log is not None and bridged:
                    result['odometry']={'state':'SAMPLE_TO_BRIDGE_PROCESS_OBSERVED' if all(v['state']=='SAMPLE_TO_BRIDGE_PROCESS_OBSERVED' for v in bridged) else 'UNKNOWN'}
                    odom_rows=[{'kind':'sample','topic':r['topic'],'frame_id':r['sample']['header']['frame_id'],'child_frame_id':r['body']['child_frame_id']} for r in samples if r['topic']=='/rover1/odometry']
                    result['odometry_model']=correlate_odometry_model(result,odom_rows,source,Path(launch_log).read_text())
            if sockets is not None and writer:
                from tools.rover_xrce_trace.socket_inventory import analyze_series
                entity=result.get('odometry_model',{}).get('model_entity')
                sends=[e for e in models if e['event']=='fdm_send' and entity is not None and e['model_entity']==entity]
                result['socket_series']=analyze_series(sockets,current['socket_inventory'],writer,owner,fdm_sends=sends,model=source,
                    receipt_wall_ns=[r['sample']['receipt']['system_unix_ns'] for r in status])
        result.update(session_id=owner,receiver_closed=True,counts=counts,
            monitor_complete=current.get('capture_complete') is True,
            monitor_channels={k:current.get(k) for k in ('phase','errors','core_capture_complete','socket_capture_complete')},
            observation_metadata='PER_MESSAGE_CALLBACK_NOT_GRAPH_ATTRIBUTION',
            source_is_current_motion_credential=False)
    except (ValueError,KeyError,TypeError,OSError) as exc:result['reason']=str(exc)
    return result


def correlate_model_entities(source,rows):
    """Exact runtime entity IDs in one supervised journal; names remain labels.

    Does not credit the odometry default route, SYSID, extrinsics or movement.
    Caller checks journal/process/session/window integrity before invoking.
    """
    r={'state':'UNKNOWN','entities':[],'identity_verified':False,'movement_authorized':False}
    try:
        if source.get('state')!='MODEL_SOURCE_CONTEXT_OBSERVED_ONLY':raise ValueError('Unverified model source context')
        catalogs=[v for v in rows if v.get('kind')=='scene_catalog' and v.get('received') is True]
        if len(catalogs)!=1:raise ValueError('Missing/ambiguous same-session scene catalog')
        by_id={}
        for v in catalogs[0]['body']:
            if type(v['id']) is not int or v['id']<=0 or v['id'] in by_id:raise ValueError('Unknown/duplicate scene entity')
            by_id[v['id']]=v['name']
        poses=[v for v in rows if v.get('kind')=='sample' and v.get('topic')=='/world/runway/pose/info']
        for model in source['models']:
            entity=model['model_entity'];name=by_id[entity];matched=[]
            for record in poses:
                values=[v for v in record['body']['pose'] if v['id']==entity]
                if len(values)!=1 or values[0]['name']!=name:raise ValueError('Contradictory/missing entity in pose observations')
                matched.append(record['receipt_steady_ns'])
            if not matched:raise ValueError('No pose observation for configured model entity')
            r['entities'].append({'model_entity':entity,'catalog_label':name,'plugin_instance':model['plugin_instance'],
                'pose_observations':len(matched),'pose_receipt_steady_ns':matched})
        r['state']='EXACT_RUNTIME_ENTITY_CONTEXT_OBSERVED'
    except (KeyError,ValueError,TypeError) as exc:r['reason']=str(exc);r['entities']=[]
    return r


def correlate_odometry_model(report,rows,process,launch_log):
    """Resolved runtime route + instantiated entity, not a match of spawn values.

    Closed controlled Gazebo process namespace is the existing trust model.
    No Gazebo per-sample publisher GUID or dynamic physical validation is claimed.
    """
    result={'state':'UNKNOWN','movement_authorized':False,'identity_complete':False,
            'dynamic_twist_convention_validated':False}
    try:
        import re
        if report['model_entities']['state'] not in {'EXACT_RUNTIME_ENTITY_CONTEXT_OBSERVED','EXACT_RUNTIME_CATALOG_PLUGIN_CONTEXT_OBSERVED'}:raise ValueError('Model entity context unavailable')
        if report['odometry']['state']!='SAMPLE_TO_BRIDGE_PROCESS_OBSERVED':raise ValueError('Odometry sample/bridge attribution incomplete')
        lines=re.sub(r'\x1b\[[0-9;]*m','',launch_log).splitlines()
        roles=[name for line in lines if (m:=re.fullmatch(r'\[INFO\] \[(.+)\]: process started with pid \[(\d+)\]',line))
            and int(m[2]) in {process['pid'],process['ppid']} for name in [m[1]]]
        if len(roles)!=1:raise ValueError('Gazebo log actor not bound to the observed process/parent')
        actor='['+roles[0]+'] ';owned=[line[len(actor):] for line in lines if line.startswith(actor)]
        bridge_routes={v['gz_topic'] for v in report['odometry_samples']}
        if len(bridge_routes)!=1:raise ValueError('Changing bridge route')
        route=bridge_routes.pop();matches=[]
        for entity in report['model_entities']['entities']:
            models=[v for v in report['model_source']['models'] if v['model_entity']==entity['model_entity']]
            if len(models)!=1:raise ValueError('Missing/duplicate instantiated model')
            cfg=models[0]['odometry_effective_sdf'];expected=cfg.get('odom_topic') or '/model/'+entity['catalog_label']+'/odometry'
            loaded=sum(bool(re.search(r'Loaded system \[gz::sim::systems::OdometryPublisher\] for entity \['+str(entity['model_entity'])+r'\]',line)) for line in owned)
            published=sum('OdometryPublisher publishing odometry on ['+expected+']' in line for line in owned)
            if loaded!=1 or published!=1:raise ValueError('Instantiated publisher/resolved route absent or ambiguous')
            if expected==route:matches.append((entity,cfg))
        if len(matches)!=1:raise ValueError('No unique instantiated model for bridge route')
        entity,cfg=matches[0];odom=[v for v in rows if v.get('kind')=='sample' and v.get('topic')=='/rover1/odometry']
        if not odom or cfg.get('dimensions')!='3' or any(v['frame_id']!=cfg.get('odom_frame') or v['child_frame_id']!=cfg.get('robot_base_frame') for v in odom):
            raise ValueError('Pose/twist frame or dimensions contradict instantiated configuration')
        result.update(state='ODOMETRY_BRIDGE_TO_INSTANTIATED_MODEL_ROUTE_OBSERVED',model_entity=entity['model_entity'],
            process={k:process[k] for k in ('pid','start_ticks','boot_id')},route=route,
            route_setting='EXPLICIT' if cfg.get('odom_topic') else 'OMITTED_DEFAULT_RESOLVED_IN_ORIGINAL_LOG',
            pose_frame=cfg['odom_frame'],twist_frame=cfg['robot_base_frame'],declared_units='ROS metres, seconds, radians; not a physical calibration',
            orientation='Quaternion xyzw, body orientation in pose frame',frequency_setting=cfg.get('odom_publish_frequency'),
            frequency_observed='NOT_DERIVABLE_FROM_RETAINED_QUOTA',trust_model='CONTROLLED_SINGLE_GAZEBO_NAMESPACE')
    except (KeyError,TypeError,ValueError) as e:result['reason']=str(e)
    return result


def transport_routes(events,status_writer):
    """Intended native XRCE endpoints, without constructing any control client."""
    common=('pid','process_start_ticks','boot_id','client_instance','client_key','session_id')
    routes={
        '/ap/v3/cmd_vel':('input_created','topic','rt/ap/v3/cmd_vel','type','geometry_msgs::msg::dds_::TwistStamped_'),
        '/ap/v3/arm_motors':('replier_created','request_topic','rq/ap/v3/arm_motorsRequest','request_type','ardupilot_msgs::srv::dds_::ArmMotors_Request_'),
        '/ap/v3/mode_switch':('replier_created','request_topic','rq/ap/v3/mode_switchRequest','request_type','ardupilot_msgs::srv::dds_::ModeSwitch_Request_')}
    result={}
    for endpoint,(event,field,name,type_field,type_name) in routes.items():
        candidates=[e for e in events if e['event']==event and e.get(field)==name and e.get(type_field)==type_name and
            all(str(e.get(k))==str(status_writer.get(k)) for k in common)]
        accepted=[]
        for candidate in candidates:
            scope=common+('attempt','object_id','entity_kind')
            commits=[e for e in events if e['event']=='entity_commit' and e.get('committed') is True and
                     all(e.get(k)==candidate.get(k) for k in scope) and e['sequence']>candidate['sequence']]
            if len(commits)==1:accepted.append(candidate)
        result[endpoint]={'state':'XRCE_ENTITY_CONTEXT_OBSERVED' if len(accepted)==1 and len(candidates)==1 else 'UNKNOWN',
            'control_command_sent':False,'effect_observed':False,'movement_authorized':False,
            'domain':accepted[0].get('domain','UNKNOWN') if len(accepted)==1 else 'UNKNOWN'}
    return result


def model_records(lines):
    """Copied-plugin diagnostics, independently bounded; never a movement gate."""
    result=[];sequences={}
    for line in lines:
        if 'TFG_MODEL_TRACE ' not in line:continue
        value=json.loads(line.split('TFG_MODEL_TRACE ',1)[1])
        if value.get('schema')!='tfg.model-source/1' or value.get('incomplete') or value.get('movement_authorized') is not False:
            raise ValueError('Model diagnostic schema/incompleteness')
        identity=(value['pid'],value['process_start_ticks'],value['boot_id'])
        if type(identity[0]) is not int or identity[0]<=0 or not str(identity[1]).isdigit() or not identity[2]:raise ValueError('Unknown model process')
        if any(type(value.get(k)) is not int or value[k]<=0 for k in ('steady_ns','wall_unix_ns')):raise ValueError('Unknown model observation clock')
        seen=sequences.setdefault(identity,set());sequence=value['sequence']
        if type(sequence) is not int or not 0<sequence<32 or sequence in seen:raise ValueError('Model diagnostic cap/duplicate')
        seen.add(sequence);result.append(value)
    for seen in sequences.values():
        if seen!=set(range(1,max(seen)+1)):raise ValueError('Truncated model diagnostics')
    return result


def assess_model_source(records,expected_process):
    """Alternative operational proof: live instantiated plugin + actual pose/FDM.

    Closed, controlled SITL namespace is the stated trust model. This does NOT
    authenticate malicious publishers, assign ROS samples, attest SYSID or gates.
    Process/maps provenance and the independent socket/SITL branch stay explicit.
    """
    report={'state':'UNKNOWN','movement_authorized':False,'identity_verified':False,
            'trust_model':'CONTROLLED_SITL_PROCESS_NAMESPACE_NOT_HOSTILE_PUBLISHER_AUTHENTICATION',
            'models':[],'pending':['ROS sample to bridge','bridge route to instantiated odometry plugin',
                'FDM destination socket to correlated SITL process','effective SYSID','frame/uncertainty validation']}
    try:
        if not records:raise ValueError('No live source-point observations')
        for r in records:
            if any(str(r[a])!=str(expected_process[b]) for a,b in [('pid','pid'),('process_start_ticks','start_ticks'),('boot_id','boot_id')]):
                raise ValueError('Model records mix process executions')
        configurations=[r for r in records if r['event']=='configured']
        keys=[r['plugin_instance'] for r in configurations]
        if not keys or len(keys)!=len(set(keys)):raise ValueError('Missing/duplicate instance generation')
        for cfg in configurations:
            instance=cfg['plugin_instance'];entity=cfg['model_entity']
            if type(instance) is not int or instance<=0 or type(entity) is not int or entity<=0:raise ValueError('Unknown live entity/instance')
            scope=[r for r in records if r.get('plugin_instance')==instance]
            if any(r['model_entity']!=entity for r in scope):raise ValueError('Instance/model changed')
            plugins=[r for r in scope if r['event']=='attached_plugin']
            odom=[r for r in plugins if r['name']=='gz::sim::systems::OdometryPublisher']
            fdm=[r for r in plugins if r['name']=='ArduPilotPlugin']
            if len(odom)!=1 or len(fdm)!=1:raise ValueError('Missing or multiple attached plugin instances')
            import re
            if any(not re.fullmatch('[0-9a-f]{64}',r['xml_sha256']) for r in plugins):raise ValueError('Missing configuration digest')
            source_poses=[r for r in scope if r['event']=='pose_input'];sends=[r for r in scope if r['event']=='fdm_send']
            if not source_poses or not sends:raise ValueError('No pose/actual FDM send')
            times=[_finite(r['sim_time_s']) for r in sorted(source_poses,key=lambda r:r['state_generation'])]
            if any(t<0 for t in times) or any(a>b for a,b in zip(times,times[1:])):raise ValueError('Model simulation clock changed epoch')
            accepted=[]
            for send in sends:
                poses=[r for r in source_poses if r['state_generation']==send['state_generation']]
                if len(poses)!=1:raise ValueError('Unbound/ambiguous FDM state generation')
                pose=poses[0];chain=pose['link_parent_chain']
                if not chain or chain[0]!=pose['input_link_entity'] or chain[-1]!=entity or len(chain)!=len(set(chain)) or pose['link_reaches_model'] is not True:
                    raise ValueError('Pose link is not a checked descendant of the model')
                for key in ('world_link_pose_m_xyzw','world_model_pose_m_xyzw','fdm_pose_m_xyzw'):
                    if len(pose[key])!=7:raise ValueError('Missing pose input')
                    for x in pose[key]:_finite(x)
                socket=send['socket_observation']
                if not socket or socket!=cfg['socket_observation'] or type(socket['fd']) is not int or socket['fd']<0 or socket['inode']<=0:
                    raise ValueError('Missing/changing actual JSON socket')
                import ipaddress
                ipaddress.ip_address(send['destination_address'])
                if type(send['destination_port']) is not int or not 0<send['destination_port']<=65535:raise ValueError('Unknown JSON destination')
                if send['bytes_expected']<=0 or send['bytes_sent']!=send['bytes_expected']:raise ValueError('FDM send not confirmed')
                if not cfg['sequence']<pose['sequence']<send['sequence']:raise ValueError('Contradictory source point order')
                accepted.append({'state_generation':send['state_generation'],'model_entity':entity,
                    'socket':socket,'fdm_destination':[send['destination_address'],send['destination_port']]})
            report['models'].append({'plugin_instance':instance,'model_entity':entity,
                'state':'INSTANTIATED_PLUGINS_POSE_AND_FDM_CONTEXT_OBSERVED','states':accepted,
                'odometry_effective_sdf':odom[0]['effective_sdf'],
                'route_default_unknown':not bool(odom[0]['effective_sdf'].get('odom_topic'))})
        report['state']='MODEL_SOURCE_CONTEXT_OBSERVED_ONLY'
    except (ValueError,KeyError,TypeError) as exc:report['reason']=str(exc)
    return report


if __name__=='__main__':main()
