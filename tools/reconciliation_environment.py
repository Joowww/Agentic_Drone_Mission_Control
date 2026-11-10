"""Bounded Docker *metadata* reads. No exec, starts, controls or configuration reads.

Only selected non-secret fields are collected. A missing name or a transport error
is not termination evidence. Callers must bind a STOPPED observation to prior
identity evidence and revalidate it under the project execution/registry mutexes.
"""
from datetime import datetime
import json
import re
import subprocess

from tools.ros2_flight_control import CONTAINER
from tools.vehicle_execution_lock import utc_now

COMMAND_TIMEOUT_SECONDS = 3
HEX_ID = re.compile(r"[0-9a-f]{64}\Z")
INSPECT_FORMAT = ('{"container_id":{{json .Id}},"name":{{json .Name}},'
                  '"created_at":{{json .Created}},"image_id":{{json .Image}},'
                  '"state":{{json .State}}}')


class ActiveExecutionReadError(ValueError):
    """Fixed diagnostic labels only; never copies stdout, stderr or values."""
    def __init__(self, source, field, reason):
        self.diagnostic={'operation':'inspect_active_execution','source':source,
                         'field':field,'reason':reason}
        super().__init__(source+'.'+field+': '+reason)


def _timestamp(value):
    if not isinstance(value, str):
        raise ValueError("Missing/invalid Docker wall timestamp")
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.tzinfo is None or result.year < 1970:
        raise ValueError("Missing/invalid Docker wall timestamp")
    return result


def environment_identity(value):
    """Incarnation, including state/termination times, for exact application binding."""
    return {key: value.get(key) for key in (
        "engine_id", "container_id", "name", "created_at", "image_id", "state")}


def stopped_reasons(value):
    try:
        if value.get("status") != "STOPPED":
            return [f"Environment is {value.get('status', 'UNKNOWN')}, not verified STOPPED"]
        state = value["state"]
        if (not value["engine_id"] or not HEX_ID.fullmatch(value["container_id"])
                or value["name"] != "/" + CONTAINER or not value["image_id"]
                or state["Status"] != "exited" or state["Running"] is not False
                or type(state["Pid"]) is not int or state["Pid"] != 0
                or any(state[k] is not False for k in ("Paused", "Restarting", "Dead"))):
            raise ValueError("Contradictory stopped-container identity/state")
        if not _timestamp(value["created_at"]) <= _timestamp(state["StartedAt"]) < _timestamp(state["FinishedAt"]):
            raise ValueError("Missing/contradictory Docker creation/start/finish wall times")
    except (KeyError, TypeError, ValueError, AttributeError) as exc:
        return [str(exc)]
    return []


def inspect_environment():
    """At most five read-only CLI calls, each <=3 s; preserve partial observations."""
    result = {"status": "UNKNOWN", "expected_container_name": CONTAINER,
              "started_at_utc": utc_now(), "command_timeout_seconds": COMMAND_TIMEOUT_SECONDS,
              "reasons": [], "operations": [], "unknown_fields": [],
              "clock": "Docker daemon wall timestamps; not ROS/simulation time"}

    def read(operation, arguments):
        try:
            value = subprocess.run(["docker", *arguments], capture_output=True, text=True,
                                   timeout=COMMAND_TIMEOUT_SECONDS, check=False)
            result["operations"].append({"operation": operation, "return_code": value.returncode,
                                         "error": value.stderr[-1024:] if value.returncode else None})
            if value.returncode:
                raise RuntimeError(f"{operation} returned {value.returncode}: {value.stderr[-1024:]}")
            return value.stdout.strip()
        except (OSError, subprocess.TimeoutExpired) as exc:
            result["operations"].append({"operation": operation, "return_code": None,
                                         "error": f"{type(exc).__name__}: {exc}"})
            raise

    try:
        try:
            engine = json.loads(read("engine_identity", ["info", "--format", "{{json .ID}}"]))
            if not isinstance(engine, str) or not engine.strip():
                raise ValueError("Docker engine identity unavailable")
            result["engine_id"] = engine
        except (OSError, subprocess.TimeoutExpired, RuntimeError, ValueError):
            result["status"] = "DOCKER_UNAVAILABLE"
            raise
        list_arguments = ["ps", "--all", "--no-trunc", "--filter", f"name=^/{CONTAINER}$", "--format", "{{.ID}}"]
        identifier = read("resolve_exact_name", list_arguments)
        if not identifier:
            result["status"] = "CONTAINER_ABSENT"
            result["reasons"].append("Accessible Docker daemon resolved no exact named container; absence does not prove termination")
        else:
            if not HEX_ID.fullmatch(identifier):
                raise ValueError("Container name did not resolve to exactly one full identity")
            value = json.loads(read("container_metadata", ["inspect", "--type", "container", "--format", INSPECT_FORMAT, identifier]))
            result.update(value)
            if value["container_id"] != identifier or value["name"] != "/" + CONTAINER:
                raise ValueError("Container replaced/renamed during collection")
            if (not isinstance(value["image_id"], str) or not value["image_id"]
                    or _timestamp(value["created_at"]) > _timestamp(value["state"]["StartedAt"])):
                raise ValueError("Missing/contradictory container image, creation or start identity")
            if (read("recheck_name", list_arguments) != identifier
                    or json.loads(read("recheck_engine", ["info", "--format", "{{json .ID}}"])) != engine):
                raise ValueError("Docker engine/container changed during collection")
            state = value["state"]
            if (state["Status"] == "running" and state["Running"] is True
                    and type(state["Pid"]) is int and state["Pid"] > 0
                    and all(state[k] is False for k in ("Paused", "Restarting", "Dead"))):
                result["status"] = "ACTIVE"
            else:
                result["status"] = "STOPPED"
                reasons = stopped_reasons(result)
                if reasons:
                    result["status"] = "UNKNOWN"
                    result["reasons"].extend(reasons)
    except (OSError, subprocess.TimeoutExpired, RuntimeError, ValueError, TypeError, KeyError) as exc:
        if result["status"] not in {"DOCKER_UNAVAILABLE", "CONTAINER_ABSENT"}:
            result["status"] = "UNKNOWN"
        result["reasons"].append(f"{type(exc).__name__}: {exc}")
    result["finished_at_utc"] = utc_now()
    result["unknown_fields"] = [k for k in ("engine_id", "container_id", "name", "created_at", "image_id", "state") if k not in result]
    if isinstance(result.get("state"), dict):
        result["unknown_fields"].extend('state.'+k for k in (
            "Status", "Running", "Pid", "Paused", "Restarting", "Dead", "StartedAt", "FinishedAt") if k not in result["state"])
    return result


def persistent_identity(value):
    """Identity which survives stop/start; deliberately excludes execution clocks."""
    fields=('engine_id','container_id','image_id','name','created_at')
    if not isinstance(value,dict):raise ActiveExecutionReadError('container_metadata','persistent_identity','NOT_OBJECT')
    result={}
    for field in fields:
        if not isinstance(value.get(field),str) or not value[field]:
            raise ActiveExecutionReadError('container_metadata',field,'MISSING_OR_INVALID_STRING')
        result[field]=value[field]
    for field,valid in (('container_id',HEX_ID.fullmatch(result['container_id'])),
                        ('image_id',re.fullmatch(r'sha256:[0-9a-f]{64}',result['image_id']))):
        if not valid:raise ActiveExecutionReadError('container_metadata',field,'INVALID_ID_FORMAT')
    try:_timestamp(result['created_at'])
    except ValueError:raise ActiveExecutionReadError('container_metadata','created_at','INVALID_WALL_TIMESTAMP') from None
    return result


def active_execution_identity(value, container_boot_id):
    """Current container execution, separate from host worker/Docker engine identity."""
    identity=persistent_identity(value);state=value.get('state')
    if not isinstance(state,dict):raise ActiveExecutionReadError('container_metadata','state','MISSING_OR_INVALID_OBJECT')
    checks=[('status',value.get('status')=='ACTIVE'),('state.Status',state.get('Status')=='running'),
            ('state.Running',state.get('Running') is True),
            ('state.Pid',type(state.get('Pid')) is int and state['Pid']>0),
            *[('state.'+k,state.get(k) is False) for k in ('Paused','Restarting','Dead')],
            ('container_boot_id',isinstance(container_boot_id,str) and bool(container_boot_id))]
    for field,valid in checks:
        if not valid:raise ActiveExecutionReadError('container_metadata',field,'UNKNOWN_OR_CONTRADICTORY_EXECUTION')
    try:started=_timestamp(state.get('StartedAt'))
    except ValueError:raise ActiveExecutionReadError('container_metadata','state.StartedAt','INVALID_WALL_TIMESTAMP') from None
    if started<_timestamp(identity['created_at']):
        raise ActiveExecutionReadError('container_metadata','state.StartedAt','BEFORE_CONTAINER_CREATION')
    return {'persistent_identity':identity,'container_started_at':state['StartedAt'],
            'container_boot_id':container_boot_id}


def read_container_boot_id(environment):
    """Bounded read in the exact already-resolved container; no shell/ROS."""
    if environment.get('status')!='ACTIVE':raise ValueError('Container not known ACTIVE')
    persistent_identity(environment)
    result=subprocess.run(['docker','exec',environment['container_id'],'python3','-B','-c',
        "from pathlib import Path;print(Path('/proc/sys/kernel/random/boot_id').read_text().strip())"],
        capture_output=True,text=True,timeout=COMMAND_TIMEOUT_SECONDS,check=False)
    if result.returncode:raise ActiveExecutionReadError('container_boot_query','returncode','QUERY_FAILED')
    if not result.stdout.strip():raise ActiveExecutionReadError('container_boot_query','stdout','EMPTY_BOOT_ID')
    if len(result.stdout)>128:raise ActiveExecutionReadError('container_boot_query','stdout','BOOT_ID_OUTPUT_LIMIT')
    return result.stdout.strip()


def inspect_active_execution():
    """Metadata -> exact-container proc boot -> metadata, without state changes."""
    def identity(value,boot,source):
        try:return active_execution_identity(value,boot)
        except ActiveExecutionReadError as exc:
            raise ActiveExecutionReadError(source,exc.diagnostic['field'],exc.diagnostic['reason']) from exc
    before=inspect_environment()
    # Do not enter an unknown/stopped container, even to read its boot.
    if before.get('status')!='ACTIVE':
        raise ActiveExecutionReadError('metadata.before','status','METADATA_NOT_ACTIVE')
    first=identity(before,read_container_boot_id(before),'metadata.before')
    after=inspect_environment()
    second=identity(after,first['container_boot_id'],'metadata.after')
    if second!=first:
        field=next(k for k in first if first[k]!=second[k])
        if field=='persistent_identity':field+='.'+next(k for k in first[field] if first[field][k]!=second[field][k])
        raise ActiveExecutionReadError('metadata.after',field,'EXECUTION_CHANGED_DURING_OBSERVATION')
    return first


def inspect_review_environment(*, final=False):
    """Two-call metadata snapshot for a caller-bracketed acquisition.

    inspect by exact name returns ID/name/image/incarnation together. The caller
    MUST compare engine, name and execution with a second snapshot after reads;
    this is not a standalone replacement for inspect_environment's rechecks.
    """
    import time
    result={'status':'UNKNOWN','operations':[],'reasons':[],
            'started_at_utc':utc_now(),'command_timeout_seconds':COMMAND_TIMEOUT_SECONDS,
            'stability_check':'CALLER_BRACKETS_COMPLETE_ACQUISITION'}
    def read(name,args):
        started=time.monotonic()
        try:
            value=subprocess.run(['docker',*args],capture_output=True,text=True,
                                 timeout=COMMAND_TIMEOUT_SECONDS,check=False)
            result['operations'].append({'operation':name,'return_code':value.returncode,
                'duration_s':time.monotonic()-started,'error':value.stderr[-1024:] if value.returncode else None})
            if value.returncode:raise ValueError(name+' failed: '+value.stderr[-1024:])
            return value.stdout
        except (OSError,subprocess.TimeoutExpired) as exc:
            result['operations'].append({'operation':name,'return_code':None,
                'duration_s':time.monotonic()-started,'error':str(exc)})
            raise
    try:
        arguments=['inspect','--type','container','--format',INSPECT_FORMAT,CONTAINER]
        metadata=read('named_container_metadata',arguments) if final else None
        engine=json.loads(read('engine_identity',['info','--format','{{json .ID}}']))
        if not isinstance(engine,str) or not engine:raise ValueError('Docker engine identity unavailable')
        result['engine_id']=engine
        value=json.loads(metadata if final else read('named_container_metadata',arguments))
        result.update(value);persistent_identity(result)
        if value['name']!='/'+CONTAINER:raise ValueError('Exact container name mismatch')
        state=value['state']
        if _timestamp(value['created_at'])>_timestamp(state['StartedAt']):raise ValueError('Container incarnation chronology invalid')
        if (state['Status']=='running' and state['Running'] is True and type(state['Pid']) is int and state['Pid']>0
                and all(state[k] is False for k in ('Paused','Restarting','Dead'))):
            result['status']='ACTIVE'
        else:
            result['status']='STOPPED';reasons=stopped_reasons(result)
            if reasons:result['status']='UNKNOWN';result['reasons'].extend(reasons)
    except (OSError,subprocess.TimeoutExpired,ValueError,TypeError,KeyError) as exc:
        result['status']='UNKNOWN';result['reasons'].append(str(exc))
    result['finished_at_utc']=utc_now()
    return result
