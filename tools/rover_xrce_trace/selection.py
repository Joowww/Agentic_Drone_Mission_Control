"""Explicit diagnostic artifact selection. No agent launcher or control API."""
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
from uuid import UUID

SCHEMA = 'tfg.xrce-agent-selection/1'
PAIR = ('b1330420c764240c971263d5ec7abea3da82a46555bf677a2f21a1d78694325c',
        '5bae08d754e8113b99c1d418154f907754168b1217b5be18c0969738def55703')
# Reviewed real peer-metadata build; the historical pair remains distinct.
PEER_PAIR = ('2c81395a0aaf5aaac094e302c69edbe357975f200947578e9b4ca7eaf17a63a8',
             'cf2537265cb64b9ea0f52737306be6166e0a4456a4a2c94b21319b2298a097fa')
KEYS = {'schema','container_id','image_id','engine_id','wrapper_path','wrapper_sha256','library_path','library_sha256'}
IDENTITY_SCHEMA='tfg.xrce-agent-selection/2'
IDENTITY_KEYS=KEYS|{'bridge_path','bridge_sha256','bridge_library_path','bridge_library_sha256'}
IDENTITY_ARTIFACTS=('eedd3756864cbc26fd30f14a0fcf7c46e21a9f5b3712b17a9826ced7d373c099',
    '2b18ce9acc46305c48b2708de52218efc688cfa3a927e37ac9c8e7a752b40828',
    '44b065a6bef150a42f6b8d0316007a9c775ba19d9cfc0b6a6c72f2e11128f386',
    '5842aa4764e9861acaff01f8715d1fa0fd6820dab1a6f59bb365b68ff14625e4')
RPC_IDENTITY_ARTIFACTS=('0743391476c0d89a2d3195ec6f7330692275790cc781f4443528c5b716b5c3f3',
    '26b113bf6742187768e0b4b93cdb68859634c1104ae576a34dc326732514e240',
    '44b065a6bef150a42f6b8d0316007a9c775ba19d9cfc0b6a6c72f2e11128f386',
    '5842aa4764e9861acaff01f8715d1fa0fd6820dab1a6f59bb365b68ff14625e4')

# Reviewed isolated build; provenance: evaluation/operations/
# rover_transport_build_2026_10_27/54dd8ddc-f919-42f2-ac25-2206aecb8ab4.
# Historical pairs remain accepted separately; this does not select a session.
RPC_PREPARED_ARTIFACTS=('b480fc7fe52fe8b18d2a4540f0d8869642bb125c4e7e302e2067af77a0cdb17e',
    '066993392db4be9fb7e6f09fc586e9e6091df6fedbf251e9dd09be3873594bbc',
    '44b065a6bef150a42f6b8d0316007a9c775ba19d9cfc0b6a6c72f2e11128f386',
    '5842aa4764e9861acaff01f8715d1fa0fd6820dab1a6f59bb365b68ff14625e4')


MODEL_SCHEMA='tfg.xrce-agent-selection/3'
MODEL_KEYS=IDENTITY_KEYS|{'model_library_path','model_library_sha256'}
STATUS_SCHEMA='tfg.xrce-agent-selection/4'
STATUS_KEYS=MODEL_KEYS|{'rover_path','rover_sha256','sitl_launch_sha256','wildthumper_launch_sha256'}
STATUS_PAIR=('d1078c0db5edef6ae90f73d1cd19ca1433f04066622660360ae9c82145c491c3',
             '8607e46a95760451bd123f6eb1bf628413e4024a4ed5961cafec28d4cc1acaf1')
# Set only after the isolated rover build's final ELF inspection.
STATUS_ROVER_SHA256='8749eeef15347a9d9dd7edc25278e7d72b1b085f3e59e363c217adb02882161e'
# Isolated clock/JSON-path build 54b7adc8; exact paired rover/plugin only.
# Older Status selection remains distinct; no operational policy is enabled.
TIMING_STATUS_BUILD=('48196b558a596e25ac081d67195a5ed3578d78b4d3c161538ee86d0f4b04d235',
                     '4a26126d9d83fde175d274bb31a38ba8e8547015e5239eccda4da990f2d53b2e')
SITL_LAUNCH=Path('/root/ardu_ws/install/ardupilot_sitl/local/lib/python3.10/dist-packages/ardupilot_sitl/launch.py')
WILDTHUMPER_LAUNCH=Path('/root/ardu_ws/install/ardupilot_gz_bringup/share/ardupilot_gz_bringup/launch/robots/wildthumper.launch.py')
MODEL_LIBRARY_SHA256='bc94c8367974854e1f48dea15f376284aae57cf57edbeee7624015f7afe82562'


def manifest_shape(value):
    return ((value.get('schema')==SCHEMA and set(value)==KEYS) or
            (value.get('schema')==IDENTITY_SCHEMA and set(value)==IDENTITY_KEYS) or
            (value.get('schema')==MODEL_SCHEMA and set(value)==MODEL_KEYS) or
            (value.get('schema')==STATUS_SCHEMA and set(value)==STATUS_KEYS))


def artifact_names(value):
    return ('wrapper','library','bridge','bridge_library','model_library','rover') if value['schema']==STATUS_SCHEMA else ('wrapper','library','bridge','bridge_library','model_library') if value['schema']==MODEL_SCHEMA else ('wrapper','library','bridge','bridge_library') if value['schema']==IDENTITY_SCHEMA else ('wrapper','library')

ENV = 'TFG_DIAGNOSTIC_AGENT'
ROOT = Path('/tmp/tfg_diagnostic_agents')
# Logical overlay names and deployed bootstrap paths have one definition.
HELPERS = {'selection.py': Path('/tmp/tfg_diagnostic_agent.py'),
           'monitor.py': Path('/tmp/monitor.py'),
           'socket_inventory.py': Path('/tmp/socket_inventory.py'),
           'analyze.py': Path('/tmp/analyze.py'),
           'budget.py': Path('/tmp/budget.py')}


def helper_sources():
    # Deployment renames this entry. Never assume a sibling selection.py exists.
    return {name: Path(__file__) if name == 'selection.py' else Path(__file__).with_name(name)
            for name in HELPERS}


def deployment():
    sources = helper_sources()
    for source in sources.values():
        if source.is_symlink() or not source.is_file():
            raise ValueError('Diagnostic helper missing/nonregular before deployment')
    return [(str(sources[name]), str(destination)) for name, destination in HELPERS.items()]



def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':')).encode()).hexdigest()


def read_json(path):
    data = Path(path).read_bytes()
    if len(data)>65536: raise ValueError('Diagnostic metadata too large')
    return json.loads(data)


def check_manifest(value):
    if not manifest_shape(value):
        raise ValueError('Unsupported diagnostic manifest')
    if value['schema']==STATUS_SCHEMA:
        if (tuple(value[k+'_sha256'] for k in ('rover','model_library')) not in
                ((STATUS_ROVER_SHA256,MODEL_LIBRARY_SHA256),TIMING_STATUS_BUILD) or
                tuple(value[k+'_sha256'] for k in ('wrapper','library'))!=STATUS_PAIR or
                tuple(value[k+'_sha256'] for k in ('bridge','bridge_library'))!=RPC_PREPARED_ARTIFACTS[2:] or
                any(not re.fullmatch('[0-9a-f]{64}',value[k]) for k in ('sitl_launch_sha256','wildthumper_launch_sha256'))):
            raise ValueError('Unreviewed Status diagnostic artifact/launch selection')
    if (value['schema'] in (IDENTITY_SCHEMA,MODEL_SCHEMA) and tuple(value[k+'_sha256'] for k in ('wrapper','library','bridge','bridge_library')) not in (IDENTITY_ARTIFACTS,RPC_IDENTITY_ARTIFACTS,RPC_PREPARED_ARTIFACTS) or
            value['schema']==MODEL_SCHEMA and value['model_library_sha256']!=MODEL_LIBRARY_SHA256 or
            value['schema']==SCHEMA and (value['wrapper_sha256'],value['library_sha256']) not in (PAIR,PEER_PAIR)):
        raise ValueError('Unreviewed/incompatible diagnostic wrapper/library pair')
    if not re.fullmatch('[0-9a-f]{64}',value['container_id']) or not re.fullmatch('sha256:[0-9a-f]{64}',value['image_id']):
        raise ValueError('Exact container/image identities required')
    if not isinstance(value['engine_id'],str) or not value['engine_id']:
        raise ValueError('Docker engine identity required')
    for name in (k+'_path' for k in artifact_names(value)):
        p=Path(value[name])
        if not p.is_absolute() or '..' in p.parts or not p.is_relative_to('/tmp'):
            raise ValueError('Explicit temporary diagnostic build paths required')
    return value


def load_manifest(path):
    p=Path(path)
    if p.is_symlink() or not p.is_file(): raise ValueError('Regular explicit manifest required')
    return check_manifest(read_json(p))


def descriptor(manifest, owner):
    if str(UUID(owner))!=owner: raise ValueError('Canonical lifecycle identity required')
    deployment()  # validate the entire helper set before persisting/start
    return {'manifest':check_manifest(manifest), 'lifecycle_id':owner,
            'prefix':str(ROOT/owner), 'selection_sha256':digest(manifest),
            'helpers':{name:hashlib.sha256(source.read_bytes()).hexdigest()
                       for name, source in helper_sources().items()}}


def check_frozen_descriptor(value):
    """Validate a recorded close target, without reinterpreting an old build pair."""
    if set(value)!={'manifest','lifecycle_id','prefix','selection_sha256','helpers'}:
        raise ValueError('Recorded diagnostic descriptor shape changed')
    owner=value['lifecycle_id']
    if str(UUID(owner))!=owner or value['prefix']!=str(ROOT/owner):
        raise ValueError('Recorded diagnostic owner/prefix mismatch')
    manifest=value['manifest']
    if (not manifest_shape(manifest) or value['selection_sha256']!=digest(manifest)
            or not re.fullmatch('[0-9a-f]{64}',manifest.get('container_id',''))
            or not re.fullmatch('sha256:[0-9a-f]{64}',manifest.get('image_id',''))
            or not manifest.get('engine_id')):
        raise ValueError('Recorded diagnostic environment/digest changed')
    return value


def check_descriptor(value):
    if value != descriptor(value['manifest'],value['lifecycle_id']):
        raise ValueError('Diagnostic descriptor/prefix mismatch')
    return value


def checked_bytes(path, expected):
    p=Path(path)
    if p.resolve()!=p or not stat.S_ISREG(p.stat().st_mode):
        raise ValueError('Diagnostic artifact symlink/nonregular path')
    data=p.read_bytes()
    if not data.startswith(b'\x7fELF') or hashlib.sha256(data).hexdigest()!=expected:
        raise ValueError('Diagnostic artifact absent/altered')
    return data


def elf(path):
    text=subprocess.run(['readelf','-d',str(path)],capture_output=True,text=True,
                        timeout=5,check=True).stdout
    return {'needed':re.findall(r'\(NEEDED\).*?\[([^]]+)\]',text),
            'soname':re.findall(r'\(SONAME\).*?\[([^]]+)\]',text)}


def validate_sources(value, *, elf_reader=elf):
    check_descriptor(value)
    if os.environ.get('LD_PRELOAD') or os.environ.get('LD_AUDIT'):
        raise ValueError('Diagnostic loader overrides are unsupported')
    m=value['manifest']
    data=[checked_bytes(m[k+'_path'],m[k+'_sha256']) for k in artifact_names(m)]
    wrapper, library=[elf_reader(m[k+'_path']) for k in ('wrapper','library')]
    if ('libmicroxrcedds_agent.so.2.4' not in wrapper['needed'] or
            library['soname']!=['libmicroxrcedds_agent.so.2.4'] or
            'librmw_fastrtps_shared_cpp.so' not in library['needed']):
        raise ValueError('Diagnostic ELF linkage contract differs')
    if m['schema'] in (IDENTITY_SCHEMA,MODEL_SCHEMA,STATUS_SCHEMA):
        bridge,bridge_library=[elf_reader(m[k+'_path']) for k in ('bridge','bridge_library')]
        if ('libros_gz_bridge.so' not in bridge['needed'] or bridge_library['soname']!=['libros_gz_bridge.so']):
            raise ValueError('Diagnostic bridge ELF linkage differs')
    if m['schema'] in (MODEL_SCHEMA,STATUS_SCHEMA):
        model=elf_reader(m['model_library_path'])
        if model['soname']!=['libTFGArduPilotIdentity.so'] or 'libgz-sim8.so.8' not in model['needed']:raise ValueError('Model plugin ELF contract differs')
    if m['schema']==STATUS_SCHEMA:
        for path,key in [(SITL_LAUNCH,'sitl_launch_sha256'),(WILDTHUMPER_LAUNCH,'wildthumper_launch_sha256')]:
            if path.is_symlink() or hashlib.sha256(path.read_bytes()).hexdigest()!=m[key]:
                raise ValueError('Status launch source differs from reviewed executable lookup')
        if 'f"exec {command} "' not in SITL_LAUNCH.read_text() or '"command": "ardurover"' not in WILDTHUMPER_LAUNCH.read_text():
            raise ValueError('Status rover PATH lookup contract differs')
    return data


def atomic_record(path, value):
    # Always BLOCKED: process/trace facts are never full rover identity.
    value={**value,'status':'BLOCKED','source_association_verified':False,'movement_authorized':False}
    p=Path(path);tmp=p.with_suffix('.tmp')
    fd=os.open(tmp,os.O_WRONLY|os.O_CREAT|os.O_TRUNC|os.O_NOFOLLOW,0o600)
    with os.fdopen(fd,'w') as f:
        json.dump(value,f,sort_keys=True);f.flush();os.fsync(f.fileno())
    os.replace(tmp,p)


def prepare_overlay(value, *, elf_reader=elf):
    """Container backend only, BEFORE lifecycle cleanup/start. Never executes ELF."""
    data=validate_sources(value,elf_reader=elf_reader)
    wrapper,library=data[:2]
    prefix=Path(value['prefix'])
    ROOT.mkdir(mode=0o700,exist_ok=True)
    if ROOT.resolve()!=ROOT or ROOT.stat().st_uid!=os.getuid() or ROOT.stat().st_mode & 0o077:
        raise ValueError('Private diagnostic root required')
    prefix.mkdir(mode=0o700,exist_ok=False)  # no reuse or overwriting a session
    for name in ('lib/micro_ros_agent','share/ament_index/resource_index/packages','capture'):
        (prefix/name).mkdir(parents=True,mode=0o700)
    for name,contents,mode in [('lib/micro_ros_agent/micro_ros_agent',wrapper,0o500),
                           ('lib/libmicroxrcedds_agent.so.2.4',library,0o400)]:
        with (prefix/name).open('xb') as f: f.write(contents);f.flush();os.fsync(f.fileno())
        (prefix/name).chmod(mode)
    if value['manifest']['schema'] in (IDENTITY_SCHEMA,MODEL_SCHEMA,STATUS_SCHEMA):
        (prefix/'lib/ros_gz_bridge').mkdir(mode=0o700)
        for name,contents,mode in [('lib/ros_gz_bridge/parameter_bridge',data[2],0o500),('lib/libros_gz_bridge.so',data[3],0o400)]:
            with (prefix/name).open('xb') as f:f.write(contents);f.flush();os.fsync(f.fileno())
            (prefix/name).chmod(mode)
        marker=prefix/'share/ament_index/resource_index/packages/ros_gz_bridge'
        marker.write_bytes(b'');marker.chmod(0o400)
    if value['manifest']['schema'] in (MODEL_SCHEMA,STATUS_SCHEMA):
        with (prefix/'lib/libArduPilotPlugin.so').open('xb') as f:f.write(data[4]);f.flush();os.fsync(f.fileno())
        (prefix/'lib/libArduPilotPlugin.so').chmod(0o400)
    if value['manifest']['schema']==STATUS_SCHEMA:
        (prefix/'bin').mkdir(mode=0o700)
        with (prefix/'bin/ardurover').open('xb') as f:f.write(data[5]);f.flush();os.fsync(f.fileno())
        (prefix/'bin/ardurover').chmod(0o500)
    marker=prefix/'share/ament_index/resource_index/packages/micro_ros_agent'
    marker.write_bytes(b'');marker.chmod(0o400)
    helper_hashes={}
    for name, source in helper_sources().items():
        shutil.copyfile(source,prefix/name);(prefix/name).chmod(0o400)
        helper_hashes[name]=hashlib.sha256(source.read_bytes()).hexdigest()
    atomic_record(prefix/'selection.json',{'descriptor':value,'helpers':helper_hashes})
    return verify_overlay(value)


def verify_overlay(value):
    check_descriptor(value);prefix=Path(value['prefix'])
    if prefix.resolve()!=prefix or prefix.stat().st_uid!=os.getuid() or prefix.stat().st_mode & 0o077:
        raise ValueError('Diagnostic overlay ownership/path/mode changed')
    record=read_json(prefix/'selection.json')
    if record['descriptor']!=value: raise ValueError('Overlay belongs to another selection/session')
    for name in HELPERS:
        p=prefix/name
        if p.resolve()!=p or hashlib.sha256(p.read_bytes()).hexdigest()!=record['helpers'][name]:
            raise ValueError('Diagnostic helper changed')
    for name,k in [('lib/micro_ros_agent/micro_ros_agent','wrapper'),('lib/libmicroxrcedds_agent.so.2.4','library')]:
        checked_bytes(prefix/name,value['manifest'][k+'_sha256'])
    if value['manifest']['schema'] in (IDENTITY_SCHEMA,MODEL_SCHEMA,STATUS_SCHEMA):
        for name,k in [('lib/ros_gz_bridge/parameter_bridge','bridge'),('lib/libros_gz_bridge.so','bridge_library')]:
            checked_bytes(prefix/name,value['manifest'][k+'_sha256'])
        marker=prefix/'share/ament_index/resource_index/packages/ros_gz_bridge'
        if marker.resolve()!=marker or marker.read_bytes()!=b'':raise ValueError('Bridge ament selection changed')
    if value['manifest']['schema'] in (MODEL_SCHEMA,STATUS_SCHEMA):checked_bytes(prefix/'lib/libArduPilotPlugin.so',value['manifest']['model_library_sha256'])
    if value['manifest']['schema']==STATUS_SCHEMA:
        checked_bytes(prefix/'bin/ardurover',value['manifest']['rover_sha256'])
    marker=prefix/'share/ament_index/resource_index/packages/micro_ros_agent'
    if marker.resolve()!=marker or marker.read_bytes()!=b'': raise ValueError('Ament selection changed')
    return record


def configure(environment):
    env=dict(environment)
    env.pop('TFG_XRCE_TRACE',None)
    for key in ('TFG_STATUS_DIAGNOSTIC','TFG_STATUS_DIAGNOSTIC_CONTEXT','TFG_STATUS_DIAGNOSTIC_FIXTURE_FD'):env.pop(key,None)
    for key in ('TFG_MODEL_TRACE','TFG_MODEL_SESSION','TFG_MODEL_REQUEST_PATH'):env.pop(key,None)
    if not env.get(ENV): return env,None
    value=json.loads(env[ENV]);verify_overlay(value)
    if env.get('LD_PRELOAD') or env.get('LD_AUDIT'): raise ValueError('Diagnostic loader override')
    prefix=value['prefix']
    env.update(AMENT_PREFIX_PATH=prefix+':'+env.get('AMENT_PREFIX_PATH',''),
               LD_LIBRARY_PATH=prefix+'/lib:'+env.get('LD_LIBRARY_PATH',''),TFG_XRCE_TRACE='1')
    if value['manifest']['schema'] in (MODEL_SCHEMA,STATUS_SCHEMA):
        env.update(GZ_SIM_SYSTEM_PLUGIN_PATH=prefix+'/lib:'+env.get('GZ_SIM_SYSTEM_PLUGIN_PATH',''),TFG_MODEL_TRACE='1',TFG_MODEL_SESSION=value['lifecycle_id'],TFG_MODEL_REQUEST_PATH=prefix+'/capture/model_request')
    if value['manifest']['schema']==STATUS_SCHEMA:
        env.update(PATH=prefix+'/bin:'+env.get('PATH',''),TFG_STATUS_DIAGNOSTIC=value['lifecycle_id'],
                   TFG_STATUS_DIAGNOSTIC_CONTEXT=value['selection_sha256'])
    return env,value


if __name__=='__main__':
    # No start/run-agent verb. Invoked only after the host backend lease check.
    import sys
    if sys.argv[1:]!=['prepare']: raise SystemExit('Only internal prepare is supported')
    value=json.loads(os.environ[ENV])
    # Refuse a second agent before any overlay/start/cleanup side effect. Metadata
    # lookup only; no ROS graph/services, no process signals.
    for directory in Path('/proc').iterdir():
        if directory.name.isdigit():
            try:
                if Path(os.readlink(directory/'exe')).name=='micro_ros_agent':
                    raise ValueError('An agent already exists; diagnostic start blocked')
            except (FileNotFoundError,ProcessLookupError):pass
    prepare_overlay(value)
    print(json.dumps({'prepared':value,'status':'BLOCKED','movement_authorized':False}))
