"""Pure identity assessment. No ROS/Docker, flight authority or automatic recovery.

Also deployed beside the container's passive worker; stdlib only. Consistency of
process/ROS records is deliberately not accreditation of an XRCE source session.
"""
import hashlib
import json
import math
import time
import os
from pathlib import Path
from uuid import UUID


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, allow_nan=False).encode()).hexdigest()


def assess_identity(expected, current, *, max_age_s=3.):
    reasons = []
    result = {'status': 'BLOCKED', 'identity_consistent': False,
              'source_association_verified': False, 'movement_authorized': False,
              'reasons': reasons}
    try:
        if not isinstance(current, dict) or not isinstance(current.get('record'), dict):
            raise ValueError('Identity worker record absent; evidence not collected')
        if str(UUID(expected['lifecycle_id'])) != expected['lifecycle_id']:
            raise ValueError('Invalid lifecycle start identity')
        environment = expected['environment']
        if (not all(isinstance(environment[k], str) and environment[k] for k in
                    ('engine_id', 'container_id', 'name', 'created_at', 'image_id'))
                or environment['name'] != '/tfg-ardupilot-gazebo'
                or not environment['created_at'] or not environment['image_id']
                or len(environment['container_id']) != 64
                or any(c not in '0123456789abcdef' for c in environment['container_id'])):
            raise ValueError('Incomplete protected environment identity')
        if expected['profile'] != 'two_drones_rover' or expected['vehicle_id'] != 'rover_01' or expected['interface'] != 'v3' or expected['namespace'] != '/rover1':
            raise ValueError('Unexpected rover/profile/namespace')
        launch_hash = expected['launch_sha256']
        if (not isinstance(launch_hash, str) or len(launch_hash) != 64
                or any(c not in '0123456789abcdef' for c in launch_hash)
                or current['installed_launch_sha256'] != launch_hash):
            raise ValueError('Installed launch bytes missing or changed')
        if current['context_sha256'] != digest(expected):
            raise ValueError('Launch context changed or belongs to another start')
        if current['environment'] != expected['environment']:
            raise ValueError('Engine/container incarnation differs from protected start')
        record = current['record']
        if record['context_sha256'] != digest(expected):
            raise ValueError('Worker belongs to another launch context')
        for age in ('receipt_age_s', 'worker_age_s'):
            value = current[age]
            if type(value) not in (int, float) or not math.isfinite(value) or not 0 <= value <= max_age_s:
                raise ValueError(f'Missing/stale {age}')
        if record.get('state') != 'OBSERVING':
            raise ValueError('Identity worker stopped/failed; no restart or acceptance on query')
        # PIDs here belong to ONE container proc/boot domain, never host worker PIDs.
        if current['process_clock_scope'] != 'CONTAINER_PROC_BOOT_AND_MONOTONIC':
            raise ValueError('Unknown process/clock namespace')
        for role, identity in (('launch', expected['launch_process']), ('worker', record['worker'])):
            if (set(identity) != {'pid', 'start_ticks', 'boot_id'}
                    or type(identity['pid']) is not int or type(identity['start_ticks']) is not int
                    or not identity['boot_id']):
                raise ValueError(f'Invalid {role} process identity')
            if current['processes'].get(str(identity['pid'])) != identity:
                raise ValueError(f'{role} missing, dead or PID recycled')
        observed = record['ros']
        for key, topic in (('status', '/ap/v3/status'), ('odometry', '/rover1/odometry')):
            stream = observed[key]
            if stream['topic'] != topic or not stream.get('publisher_gid'):
                raise ValueError(f'{key} source/interface absent or wrong')
            if type(stream.get('publisher_count')) is not int or stream['publisher_count'] != 1:
                raise ValueError(f'{key} publisher absent or ambiguous')
            if key == 'status' and (type(stream['message'].get('vehicle_type')) is not int or stream['message']['vehicle_type'] != 1):
                raise ValueError('Status is not Rover')
            if key == 'odometry' and stream['message'].get('child_frame_id') != 'base_link':
                raise ValueError('Odometry frame is not rover body contract')
            # Age computed by the passive worker in its OWN monotonic domain.
            age = stream['age_s']
            if (type(age) not in (int, float) or not math.isfinite(age) or age < 0
                    or age + current['worker_age_s'] + current['receipt_age_s'] > max_age_s):
                raise ValueError(f'{key} observation stale')
            if stream.get('source_progressing') is not True:
                raise ValueError(f'{key} source frozen/rewound or insufficient samples')
        if observed['odometry'].get('publisher_namespace') != '/rover1':
            raise ValueError('Odometry publisher is outside expected bridge namespace')
        result['identity_consistent'] = True
        reasons.append('Runtime XRCE client/SYSID/DDS_USE_NS correlation and active bridge config association not yet accredited')
    except (KeyError, TypeError, ValueError) as exc:
        reasons.append(str(exc))
    return result


class RoverEnvironmentGuard:
    """Reader must collect CURRENT evidence; no constructor accepting verified=True.

    The context reader supplies current environment/proc/native journals. The
    factory attaches one supervised same-session pipe for samples/RPC/catalog.
    No automatic SDK access or historical-sample fallback is supplied here.
    """
    def __init__(self, expected, read_current, *, clock=time, clock_context=None):
        from copy import deepcopy
        self.expected, self.read_current = deepcopy(expected), read_current
        self.clock=clock
        self.clock_context=clock_context or (lambda:{'boot_id':Path('/proc/sys/kernel/random/boot_id').read_text().strip(),
            'time_namespace':os.readlink('/proc/self/ns/time')})
        self._target=None
        self.observation_source=None

    def attach_source(self,source):
        from tools.rover_observation_stream import ObservationStream
        if self.observation_source is not None or type(source) is not ObservationStream or source.session_id!=self.expected['lifecycle_id']:
            raise RuntimeError('Single same-session supervised source required')
        self.observation_source=source

    def _current(self,*,samples=True):
        from copy import deepcopy
        current=self.read_current()
        source=self.observation_source
        if source is not None:
            current=deepcopy(current);e=current['source_evidence']
            e['rpc']=deepcopy(source.rpc);e['catalog']=deepcopy(source.catalog)
            if samples:
                e['observations']=source.current()
                odom=e['observations']['odometry']
                e['frame_samples']=[{'kind':'sample','topic':'/rover1/odometry','frame_id':odom['header']['frame_id'],'child_frame_id':odom['child_frame_id']}]
            # The model/bridge route is stable proof metadata even after data
            # loss; use its last frame, never pretend it is a new observation.
            elif 'odometry' in source.latest:
                odom=source.latest['odometry']['body']
                e['frame_samples']=[{'kind':'sample','topic':'/rover1/odometry','frame_id':odom['header']['frame_id'],'child_frame_id':odom['child_frame_id']}]
        return current

    def require_passive_context(self):
        if 'source_contract' not in self.expected:return self.require_motion_source()
        return self._verify(self.read_current(),observations=None,passive=True)

    def query(self):
        try:
            if 'source_contract' in self.expected:
                current=self._current()
                value=self._verify(current,observations=current['source_evidence']['observations'])
                return {'status':'CURRENT_SOURCE_BOUND','identity_consistent':True,
                    'source_association_verified':False,'movement_authorized':False,
                    'current_binding':value,'reasons':[]}
            return assess_identity(self.expected, self.read_current())
        except Exception as exc:
            return {'status': 'BLOCKED', 'identity_consistent': False,
                    'source_association_verified': False, 'movement_authorized': False,
                    'reasons': [f'Identity collector unavailable: {type(exc).__name__}: {exc}']}

    def require_motion_source(self):
        if 'source_contract' not in self.expected:
            result = self.query()
            raise RuntimeError('Rover source identity BLOCKED: ' + '; '.join(result['reasons']))
        current=self._current()
        result=self._verify(current,observations=current['source_evidence']['observations'])
        if self._target is not None and self._target!=result['target_sha256']:
            raise RuntimeError('Control target identity changed; no retargeting')
        self._target=result['target_sha256']
        return result

    def require_stop_target(self):
        """Data loss does not erase a still-current target; never retarget a stop."""
        if self._target is None:raise RuntimeError('No previously verified control target')
        result=self._verify(self._current(samples=False),observations=None)
        if result['target_sha256']!=self._target:raise RuntimeError('Stop target identity changed')
        return result

    def require_observation(self,raw):
        current=self._current();result=self._verify(current,observations=raw)
        if self._target is None or result['target_sha256']!=self._target:
            raise RuntimeError('Observation/control target identity changed')
        return result

    def _verify(self,current,*,observations,passive=False):
        """Recompute joins from bounded CURRENT originals, never accept verified flags.

        read_current supplies the existing collector's current environment/worker
        envelope plus native trace, monitor and socket journal. No SDK is queried
        here. A production collector must supply these records, not a report from
        a closed session. Default/legacy contexts stay blocked.
        """
        from tools.rover_passive_validation import (identity_records,model_records,transport_routes,
            correlate_rpc_v2,correlate_bridge,assess_model_source,correlate_odometry_model,TRACE_BYTES)
        from tools.rover_xrce_trace.analyze import analyze
        from tools.rover_xrce_trace.socket_inventory import analyze_series
        from tools.rover_observation_stream import MAX_BYTES,SCHEMA
        expected=self.expected;c=expected['source_contract'];e=current['source_evidence']
        def require(value,reason):
            if not value:raise RuntimeError('Current source rejected: '+reason)
        def age(at,limit):
            return type(at) in (int,float) and math.isfinite(at) and 0<=self.clock.monotonic()-at<=limit
        require(str(UUID(expected['lifecycle_id']))==expected['lifecycle_id'] and
                (expected['profile'],expected['vehicle_id'],expected['interface'],expected['namespace'])==
                ('two_drones_rover','rover_01','v3','/rover1'),'owner/profile/interface')
        for k in ('max_target_age_s','max_sample_age_s'):
            require(type(c[k]) in (int,float) and math.isfinite(c[k]) and c[k]>0,'missing finite '+k)
        environment=expected['environment']
        require(all(isinstance(environment[k],str) and environment[k] for k in
                    ('engine_id','container_id','name','created_at','image_id')) and
                environment['name']=='/tfg-ardupilot-gazebo' and len(environment['container_id'])==64 and
                all(ch in '0123456789abcdef' for ch in environment['container_id']),'protected environment identity')
        require(type(c['mav_sysid']) is int and 1<=c['mav_sysid']<=255 and
                type(c['ros_domain_id']) is int and 0<=c['ros_domain_id']<=232,'SYSID/domain contract')
        require(e['schema']=='tfg.rover-current-source/1' and e['context_sha256']==digest(expected),'context/schema')
        require(e['clock_context']==self.clock_context()==c['clock_context'],'clock domain')
        require(age(e['observed_monotonic'],c['max_target_age_s']),'stale target collection')
        require(current['context_sha256']==digest(expected) and current['environment']==expected['environment'] and
                current['installed_launch_sha256']==expected['launch_sha256'],'environment/launch')
        require(e['environment_execution']==expected['execution'],'environment execution')
        require(current['process_clock_scope']=='CONTAINER_PROC_BOOT_AND_MONOTONIC','process scope')
        record=current['record']
        require(record['context_sha256']==digest(expected) and record['state']=='OBSERVING','worker/context')
        for identity in (expected['launch_process'],record['worker']):
            require(identity['boot_id']==c['clock_context']['boot_id'] and current['processes'].get(str(identity['pid']))==identity,'worker/launch process changed')
        require(age(e['collection_started_monotonic'],c['max_target_age_s']) and
                e['collection_started_monotonic']<=e['observed_monotonic'],'collection window')
        monitor=e['monitor'];owner=expected['lifecycle_id']
        require(monitor['lifecycle_id']==owner and monitor['phase']=='OBSERVING' and
                monitor.get('errors')==[] and not monitor.get('closure_requested') and
                not monitor.get('cleanup_request') and 'finished_monotonic' not in monitor,'not a live monitor')
        require(monitor['monitor']['boot_id']==c['clock_context']['boot_id'],'monitor boot')
        for process in (monitor['monitor'],monitor['agent'],monitor['identity_bridge'],monitor['model_source']):
            identity={k:process[k] for k in ('pid','start_ticks','boot_id')}
            require(identity['boot_id']==c['clock_context']['boot_id'] and current['processes'].get(str(process['pid']))==identity,'target process changed')
        require(monitor['identity_bridge'].get('verified_overlay_library') is True and
                monitor['model_source'].get('verified_overlay_library') is True,'overlay provenance')
        require({k:monitor[k]['library_sha256'] for k in ('agent','identity_bridge','model_source')}==c['artifact_hashes'],'artifact selection changed')
        if passive:return {'status':'PASSIVE_CONTEXT_ONLY','movement_authorized':False}
        payload={k:v for k,v in e.items() if k not in ('trace','sockets','observations','observed_monotonic','collection_started_monotonic')}
        sockets_raw=e['sockets'].encode() if isinstance(e['sockets'],str) else e['sockets']
        require(isinstance(sockets_raw,bytes),'in-memory socket originals required')
        from tools.rover_xrce_trace.budget import SOCKET
        require(len(sockets_raw)<=SOCKET.journal_bytes and len(e['trace'].encode())<=TRACE_BYTES,'source byte budgets')
        key=digest(payload)+hashlib.sha256(sockets_raw).hexdigest()+hashlib.sha256(e['trace'].encode()).hexdigest()
        cache=getattr(self,'_verified_target_cache',None)
        if cache and cache[0]==key:
            result,begin,end,events,snapshots,sitl=cache[1]
        else:
            trace=e['trace'];require(isinstance(trace,str) and len(trace.encode())<=TRACE_BYTES,'trace bounds')
            native=analyze(trace.splitlines());events=identity_records(trace.splitlines());models=model_records(trace.splitlines())
            require(native['trace_valid'],'native trace')
            require(all(monitor['started_monotonic']<=v['steady_ns']/1e9<=e['observed_monotonic'] for v in events+models),'metadata clock/window')
            writers=[w for w in native['correlations'] if w['topic']=='rt/ap/v3/status' and w['rmw_gid']==c['status_gid']]
            require(len(writers)==1,'ambiguous/missing Status writer');writer=writers[0]
            require(all(str(writer[a])==str(monitor['agent'][b]) for a,b in
                [('pid','pid'),('process_start_ticks','start_ticks'),('boot_id','boot_id')]),'writer process')
            routes=transport_routes(events,writer)
            require(all(routes[k]['state']=='XRCE_ENTITY_CONTEXT_OBSERVED' for k in
                    ('/ap/v3/cmd_vel','/ap/v3/mode_switch','/ap/v3/arm_motors')),'control/finalization destinations')
            destinations={}
            for endpoint,field,topic in (('/ap/v3/cmd_vel','topic','rt/ap/v3/cmd_vel'),
                    ('/ap/v3/mode_switch','request_topic','rq/ap/v3/mode_switchRequest'),
                    ('/ap/v3/arm_motors','request_topic','rq/ap/v3/arm_motorsRequest')):
                candidates=[v for v in events if v.get(field)==topic and all(str(v.get(k))==str(writer[k]) for k in
                    ('pid','process_start_ticks','boot_id','client_instance','client_key','session_id'))]
                require(len(candidates)==1,'destination generation');endpoint_record=candidates[0]
                guid=endpoint_record.get('reader_guid','')
                require(isinstance(guid,str) and len(guid)==32 and all(v in '0123456789abcdef' for v in guid) and
                        guid[:24]==writer['native_guid'][:24],'destination DDS participant')
                if field=='request_topic':require(endpoint_record['domain']==writer['domain'],'service domain')
                destinations[endpoint]={'reader_guid':guid,'domain':writer['domain'],
                    'domain_basis':'NATIVE_SAME_PARTICIPANT_GUID_PREFIX_AND_XRCE_GENERATION'}
            require(e['ros_domain_id']==writer['domain']==c['ros_domain_id'],'ROS domain')
            rpc=e['rpc'];require(len(rpc)==2,'RPC cardinality')
            require(correlate_rpc_v2(rpc[0],rpc[1],events,writer)['state']=='PER_RESPONSE_METADATA_TO_XRCE_OBSERVED','RPC attribution')
            require(rpc[1]['values']=={'MAV_SYSID':c['mav_sysid'],'DDS_USE_NS':1},'effective parameters')
            require(all(r['session_id']==owner and monitor['started_monotonic']<=r['receipt_steady_ns']/1e9<=e['observed_monotonic'] for r in rpc),'RPC execution window')
            source=assess_model_source(models,monitor['model_source'])
            require(source['state']=='MODEL_SOURCE_CONTEXT_OBSERVED_ONLY','model source')
            body=e['body_review'];require(digest(body)==c['body_review_sha256'],'body review hash')
            require(body['schema']=='tfg.rover-body-review/1' and body['pose_frame']==c['pose_frame'] and
                    body['body_frame']=='base_link' and body['linear_unit']=='m/s' and body['angular_unit']=='rad/s' and
                    body['positive_x']=='FORWARD' and body['positive_yaw']=='ROS_CCW' and
                    body['source_hashes']==e['current_source_hashes'] and bool(body['source_hashes']),'body/source contract')
            catalog=e['catalog']
            require(catalog['session_id']==owner and catalog['event']=='scene_catalog' and catalog['received'] is True,'catalog context')
            labels={v['id']:v['name'] for v in catalog['body']}
            require(len(labels)==len(catalog['body']),'ambiguous catalog')
            entities=[{'model_entity':m['model_entity'],'catalog_label':labels[m['model_entity']]} for m in source['models']]
            require(entities==c['model_entities'],'model entities')
            bridge=correlate_bridge({'message_gid':c['odometry_gid'],'rmw':'rmw_fastrtps_cpp','from_intra_process':False},events,[monitor['identity_bridge']])
            require(bridge['state']=='SAMPLE_TO_BRIDGE_PROCESS_OBSERVED','bridge process')
            route={'model_source':source,'model_entities':{'state':'EXACT_RUNTIME_CATALOG_PLUGIN_CONTEXT_OBSERVED','entities':entities},
                'odometry':{'state':'SAMPLE_TO_BRIDGE_PROCESS_OBSERVED'},'odometry_samples':[bridge]}
            odometry_model=correlate_odometry_model(route,e['frame_samples'],monitor['model_source'],e['launch_log'])
            require(odometry_model['state']=='ODOMETRY_BRIDGE_TO_INSTANTIATED_MODEL_ROUTE_OBSERVED' and
                    odometry_model['model_entity']==c['model_entity'],'model/bridge route')
            sends=[m for m in models if m['event']=='fdm_send' and m['model_entity']==c['model_entity']]
            require(sends,'no FDM send')
            wire=e['sockets'].encode() if isinstance(e['sockets'],str) else e['sockets']
            require(isinstance(wire,bytes),'in-memory socket originals required')
            series=analyze_series(wire,monitor['socket_inventory'],writer,owner,
                fdm_sends=sends,model=monitor['model_source'])
            require(series['series_state']=='REPEATED_ENDPOINT_PROCESS_CANDIDATE_ONLY' and not series['errors'],'socket coverage/owners')
            require(series['usable_windows'],'missing EOF windows')
            # Uses SDK monotonic provenance, not the wall-time span as a freshness proxy.
            from tools.rover_xrce_trace.budget import journal_rows
            from tools.rover_xrce_trace.socket_inventory import unpack_inventory
            snapshots=[unpack_inventory(json.loads(line)) for line in journal_rows(wire)]
            require(all(s['context_before']['boot_id']==c['clock_context']['boot_id'] for s in snapshots),'socket boot')
            require(all(s['context_declared_by_protected_monitor']['environment']=={k:expected['environment'][k] for k in ('engine_id','container_id','image_id')} for s in snapshots),'socket environment')
            begin=min(x['started_monotonic'] for x in snapshots[0]['reads']);end=max(x['finished_monotonic'] for x in snapshots[-1]['reads'])
            require(age(end,c['max_target_age_s']) and end<=e['observed_monotonic'],'stale socket target')
            sitl=series['rows'][0]['candidates'][0]['owners'][0]['process']
            identity={k:sitl[k] for k in ('pid','start_ticks','boot_id')}
            require(current['processes'].get(str(sitl['pid']))==identity,'SITL replaced/dead')
            fdm=[s for row in series['fdm_rows'] for s in row['sends'] if s['state']=='FDM_DESTINATION_TO_VISIBLE_SITL_SOCKET_OBSERVED']
            require(fdm and all(s['receiver']==sitl for s in fdm),'FDM/SITL join')
            target={'context_sha256':digest(expected),'sitl':sitl,'writer':writer,'routes':routes,'destinations':destinations,
                'bridge':monitor['identity_bridge'],'model':monitor['model_source'],'model_entity':c['model_entity']}
            result={'target_sha256':digest(target),'target':target,'movement_authorized':False,
                'binding_sha256':c['binding_sha256'],'body_review_sha256':c['body_review_sha256'],
                'envelope_sha256':digest(body['envelope']),
                'coverage':'CURRENT_SAMPLED_SOURCE_BINDING','global_monitor_complete':monitor.get('capture_complete'),
                'infrastructure_closed':False}
            self._verified_target_cache=(key,(result,begin,end,events,snapshots,sitl))
        require(age(end,c['max_target_age_s']) and end<=e['observed_monotonic'],'stale socket target')
        require(current['processes'].get(str(sitl['pid']))=={k:sitl[k] for k in ('pid','start_ticks','boot_id')},'SITL replaced/dead')
        if observations is not None:
            provenance=observations['sample_provenance']
            require(observations['sample_gid_source']=='RCLCPP_MESSAGE_INFO_PER_SAMPLE','per-message attribution')
            require(len(json.dumps(observations).encode())<=MAX_BYTES,'observation bounds')
            for kind,topic,gid in (('status','/ap/v3/status',c['status_gid']),('odometry','/rover1/odometry',c['odometry_gid'])):
                sample=provenance[kind];row=json.loads(sample['raw_record']);meta=row['sample']
                require(row['schema']==SCHEMA and row['session_id']==owner and row['event']=='sample' and
                        row['topic']==topic and row['body']==observations[kind] and
                        meta['header']==row['body']['header'] and meta['incomplete'] is False and
                        meta['from_intra_process'] is False and meta==sample['raw_sample'] and
                        meta['message_publisher_gid']==gid==observations[kind+'_publisher_gid'],'sample association')
                require(hashlib.sha256(sample['raw_record'].encode()).hexdigest()==sample['sample_sha256'],'sample hash')
                require(meta['rmw_implementation_identifier']=='rmw_fastrtps_cpp' and meta['header']==observations[kind]['header'] and
                        meta['message_gid_state']=='OBSERVED_NOT_ACCREDITED','sample metadata')
                receipt=meta['receipt']['steady_ns']/1e9
                require(receipt==observations[kind+'_received_monotonic_s']==sample['receipt'] and
                        age(receipt,c['max_sample_age_s']) and monitor['started_monotonic']<=receipt<=e['observed_monotonic'],'sample age/coverage')
                process=row['client_process'];identity={k:process[k] for k in ('pid','start_ticks','boot_id')}
                require(current['processes'].get(str(process['pid']))==identity and
                        process['boot_id']==c['clock_context']['boot_id'] and process['time_namespace']==c['clock_context']['time_namespace'] and
                        process['net_namespace']==snapshots[-1]['context_before']['net_namespace'] and
                        process['pid_namespace']==snapshots[-1]['context_before']['pid_namespace'],'receiver process/clock')
            bridge=correlate_bridge({'message_gid':c['odometry_gid'],'rmw':provenance['odometry']['raw_sample']['rmw_implementation_identifier'],
                'from_intra_process':False},events,[monitor['identity_bridge']])
            require(bridge['state']=='SAMPLE_TO_BRIDGE_PROCESS_OBSERVED','sample/bridge')
        from copy import deepcopy
        proof=deepcopy(result)
        proof.update(target_observed_monotonic=end,target_age_s=self.clock.monotonic()-end,
            observation_receipts=({kind:observations[kind+'_received_monotonic_s'] for kind in ('status','odometry')} if observations is not None else None),
            observation_scope='FRESH_PER_MESSAGE_WITH_BOUNDED_AGE_TARGET_REVALIDATION_NOT_ATOMIC_PACKET_ATTRIBUTION')
        return proof
