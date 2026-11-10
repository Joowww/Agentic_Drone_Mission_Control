"""Present-resource basis for the existing disposition audit, not historical repair."""
import hashlib
import json
import math
import os
import time
from pathlib import Path

from . import present_resources as resources
from .budget import SOCKET
from .session_precheck import recorded_cleanup_archive, POINTER, _recorded
from tools.reconciliation_environment import active_execution_identity

HOST_WINDOW='HOST_ACQUISITION_MONOTONIC_V1'
BASIS='CURRENT_RESOURCE_REVIEW_V1'
SCHEMA='tfg.diagnostic-disposition/3'


def reader_hashes():
    root=Path(__file__).resolve().parents[2]
    names=['tools/rover_xrce_trace/'+n for n in ('present_resources.py','present_recovery.py','socket_inventory.py','budget.py','historical_disposition.py','session_precheck.py')]
    names+=['tools/simulation_profiles.py','tools/reconciliation_environment.py','simulation/ros2_gazebo/scripts/sim_processes.py','simulation/ros2_gazebo/scripts/start_sim_backend.sh']
    return {n:hashlib.sha256((root/n).read_bytes()).hexdigest() for n in names}


def host_clock_context():
    from tools.vehicle_execution_lock import process_identity
    identity=process_identity()
    if identity is None:raise ValueError('Host acquisition process identity unavailable')
    return {'clock':'CLOCK_MONOTONIC','process':identity,
            'time_namespace':os.readlink('/proc/self/ns/time')}


def review(records,current,*,now=None,clock=None):
    """Same locks/authorization/persistence as V2; independent present evidence."""
    conditions={};scope=None
    try:
        state=current.get('environment_observation',records.get('environment',{})).get('status')
        if state!='ACTIVE':raise ValueError('Current environment is '+str(state)+'; no complete recovery inventory')
        original=recorded_cleanup_archive(records['historical_evidence'])
        for key,value in original['historical'].items():
            if records.get(key)!=value:raise ValueError('Present review original/descriptor mismatch: '+key)
        pointer=records['target']['descriptor'];env=records['environment'];inventory=records['inventory']
        execution=active_execution_identity(env,inventory['boot_id'])
        if any(env[k]!=original['historical']['environment_reference']['environment'][k] for k in ('engine_id','container_id','image_id','name','created_at')):
            raise ValueError('Present review persistent identity mismatch')
        if set(inventory['state_files'])!={POINTER} or _recorded(json.loads(inventory['state_files'][POINTER]))!=pointer:
            raise ValueError('Present review other/contradictory session state')
        for key,name in [('selection','selection.json'),('launch','launch.json'),('monitor','capture/monitor.json')]:
            if json.loads(inventory['files'][pointer['prefix']+'/'+name])!=records[key]:raise ValueError('Present review retained file mismatch: '+name)
        value=resources.unpack(current['resources'])
        if value.get('status')=='INCOMPLETE':
            return {'status':'BLOCKED','reason':'Current resource inventory incomplete: '+', '.join(value.get('reasons',[])),
                    'conditions':conditions,'current_review':{'resources':value},
                    'opening_authorized':False,'movement_authorized':False,'source_association_verified':False}
        ctx=value['context']
        window=current['host_acquisition']
        timestamps=[window['started_monotonic'],window['received_monotonic'],value['started_monotonic'],value['finished_monotonic']]
        hashes=reader_hashes()
        if any(type(x) not in (int,float) or not math.isfinite(x) for x in timestamps):raise ValueError('Present review clock invalid')
        conditions.update(
            fresh_observation=False,host_window_complete=False,
            reader_complete=current.get('complete') is True,
            no_restrictions=current.get('restriction','UNKNOWN') is None,
            no_guards=current.get('guards')=={},no_other_sessions=current.get('other_sessions')==[],
            no_host_processes=current.get('host_processes')==[],host_identity_known=bool(current.get('host_boot_id')),
            audit_available=current.get('disposition_state')=='NOT_ATTEMPTED' or
                (current.get('disposition_state')=='DISPOSED_DIAGNOSTICALLY_INCOMPLETE' and current.get('disposition_schema')==SCHEMA),
            no_container_processes=all(inventory.get(k)==[] for k in ('owned','ambiguous','agents')),
            resource_context=ctx['boot_id']==inventory['boot_id'] and
                inventory.get('query_context_before')==inventory.get('query_context_after')=={k:ctx[k] for k in ('boot_id','net_namespace','pid_namespace','time_namespace')},
            resource_duration=0<=value['finished_monotonic']-value['started_monotonic']<=SOCKET.cooperative_s,
            resource_complete=value.get('schema')==resources.SCHEMA and value['status'] in {'FREE','OCCUPIED'} and
                len(value['reads'])<=SOCKET.reads and value['counts']['read_calls']<=SOCKET.reads and
                all(row.get('state')=='OBSERVED' for row in value['reads']) and value['budget']==SOCKET.record() and
                value['max_pids']==resources.s.MAX_PIDS and value['max_fds']==resources.s.MAX_FDS and
                len(value.get('table_reads',[]))==8 and all(value['reads'][i].get('operation')=='bytes_to_eof' and value['reads'][i].get('state')=='OBSERVED' for i in value.get('table_reads',[])),
            resources_free=value['status']=='FREE' and value.get('occupied')==[] and not value.get('reasons'),
            reader_version=value.get('reader_hashes')==hashes,
            resource_scope=value['scope_sha256']==resources.digest(value['scope']) and value['scope']==resources.expected_scope(),
        )
        scope={'protocol':BASIS,'historical':original['historical'],'proof':records['historical_evidence'],
               'historical_limitations':original['limitations'],'environment_execution':execution,
               'host_boot_id':current['host_boot_id'],'host_time_namespace':window['clock_context']['time_namespace'],
               'freshness_basis':HOST_WINDOW,
               'resource_context':{k:ctx[k] for k in ('boot_id','net_namespace','pid_namespace','time_namespace')},
               'resource_scope':value['scope'],'reader_hashes':hashes,
               'reviewed_outcome':{'resources':'FREE','required_conditions':sorted(conditions)},
               'effects':['RECOGNIZE_RETAINED_POINTER_AS_INACTIVE_HISTORY_UNDER_CURRENT_REVIEW'],
               'preserved':['original_descriptor','historical_monitor','historical_fresh_observation','all_originals'],
               'opening_authorized':False,'movement_authorized':False,'source_association_verified':False}
        scope_sha256=resources.digest(scope)
        # All result/config/original validation is complete before closing the
        # host window. SDK epochs never participate in this subtraction.
        end_context=host_clock_context()
        end=(clock or time.monotonic)() if now is None else now
        if type(end) not in (int,float) or not math.isfinite(end):raise ValueError('Host evaluation clock invalid')
        conditions['host_window_complete']=(window.get('basis')==HOST_WINDOW and
            window['clock_context']==end_context and current['host_boot_id']==end_context['process']['boot_id'] and
            window['clock_context']==window.get('received_clock_context') and
            current['observed_monotonic']==window['started_monotonic']<=window['received_monotonic']<=end)
        conditions['fresh_observation']=(conditions['host_window_complete'] and 0<=end-window['started_monotonic']<=3)
        failed=[name for name,valid in conditions.items() if not valid]
        reason=('Present resources: '+','.join(value.get('reasons',[]))) if not conditions['resources_free'] else 'Present review failed: '+', '.join(failed)
        return {'status':'BLOCKED' if failed else 'DRY_RUN_ELIGIBLE','conditions':conditions,
                'reason':reason if failed else None,
                'scope':scope,'scope_sha256':scope_sha256,
                'current_execution_fingerprint':scope_sha256,
                'current_review':{'resources':value,'current_conditions':conditions,
                    'observed_monotonic':window['started_monotonic'],'received_monotonic':window['received_monotonic'],
                    'assessed_monotonic':end,'host_acquisition':window,
                    'host_window_s':end-window['started_monotonic'],
                    'host_state':{k:current.get(k) for k in ('restriction','guards','other_sessions','host_processes','host_boot_id','host_time_namespace','sources')},
                    'inventory':{k:inventory[k] for k in ('boot_id','owned','ambiguous','agents','state_files')}},
                'classification':{'status':'BLOCKED','pointer_classification':'HISTORY_INCOMPLETE_PRESENT_REVIEW',
                    'historical_freshness_reconstructed':False,'diagnostic_capture':'INCOMPLETE'},
                'opening_authorized':False,'movement_authorized':False,'source_association_verified':False}
    except (KeyError,ValueError,TypeError,OSError,IndexError) as exc:
        return {'status':'BLOCKED','reason':str(exc),'conditions':conditions,
                'opening_authorized':False,'movement_authorized':False,'source_association_verified':False}
