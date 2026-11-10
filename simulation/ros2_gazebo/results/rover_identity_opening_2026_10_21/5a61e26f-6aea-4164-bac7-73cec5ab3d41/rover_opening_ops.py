import sys, os, json, time, hashlib, subprocess
from pathlib import Path
from datetime import datetime, timezone
sys.path.insert(0,str(Path.cwd()))
from tools import vehicle_execution_lock as locks
from tools import simulation_lifecycle as lifecycle
from tools.reconciliation_environment import stopped_reasons
ROOT=Path(Path('/tmp/rover_opening_current_path.txt').read_text().strip())
SCAN_CODE=r'''
import os,json
from pathlib import Path
items=[];errors=[]
modules={'tools.virtual_preflight_worker','tools.preflight_sequence_worker','tools.simulation_lifecycle','tools.rover_ground_executor'}
scripts={'virtual_preflight_worker.py','preflight_sequence_worker.py','rover_identity_worker.py','tfg_rover_identity_worker.py'}
for p in Path('/proc').iterdir():
    if not p.name.isdigit() or int(p.name)==os.getpid(): continue
    try:
        args=[x.decode(errors='replace') for x in (p/'cmdline').read_bytes().split(b'\0') if x]
        fields=(p/'stat').read_text().rpartition(')')[2].split()
        if not args or fields[0]=='Z': continue
        names={Path(x).name for x in args[:2]}
        candidate=bool(names & {'arducopter','ardurover','gz','ign','micro_ros_agent'})
        candidate=candidate or any(x in modules for x in args)
        candidate=candidate or bool(names & scripts)
        candidate=candidate or ('launch' in args and 'ardupilot_gz_bringup' in args)
        candidate=candidate or (bool(names & {'parameter_bridge','robot_state_publisher','relay','rviz2','create'}) and any(x in {'__ns:=/drone1','__ns:=/drone2','__ns:=/rover1'} for x in args))
        if candidate: items.append({'pid':int(p.name),'start_ticks':int(fields[19]),'ppid':int(fields[1]),'argv':args})
    except (FileNotFoundError,ProcessLookupError): pass
    except Exception as exc: errors.append({'pid':int(p.name),'error':str(exc)})
print(json.dumps({'candidates':items,'errors':errors}))
'''
def now(): return datetime.now(timezone.utc).isoformat()
def save(name,value):
    p=ROOT/name
    if p.exists(): raise RuntimeError('Refuse overwrite '+name)
    p.write_text(json.dumps(value,indent=2)+'\n')
def command(name,args,*,input=None,timeout=8):
    began=time.monotonic();event={'command':args,'timeout_s':timeout,'started_at_utc':now(),'started_monotonic_s':began,'return_code':None}
    try:
        r=subprocess.run(args,input=input,capture_output=True,timeout=timeout,check=False)
        out,err=r.stdout,r.stderr;event['return_code']=r.returncode
    except (OSError,subprocess.TimeoutExpired) as exc:
        out=getattr(exc,'stdout',None) or b'';err=getattr(exc,'stderr',None) or b'';event['error']=str(exc)
    for stream,raw in [('stdout',out),('stderr',err)]:
        path=ROOT/(name+'.'+stream+'.bin')
        if path.exists(): raise RuntimeError('Refuse command repeat '+name)
        path.write_bytes(raw)
    event.update(duration_wall_s=time.monotonic()-began,finished_at_utc=now())
    save(name+'-command.json',event)
    if event['return_code']!=0: raise RuntimeError(name+': '+err.decode(errors='replace')[:1800]+event.get('error',''))
    return out

def metadata(label):
    context=command(label+'-context',['docker','context','show'],timeout=5).decode().strip()
    endpoint=command(label+'-endpoint',['docker','context','inspect','--format','{{.Name}} {{json .Endpoints.docker.Host}}'],timeout=5).decode().strip()
    engine=json.loads(command(label+'-engine',['docker','info','--format','{{json .ID}}'],timeout=5))
    ids=command(label+'-ids',['docker','ps','--all','--no-trunc','--filter','name=^/tfg-ardupilot-gazebo$','--format','{{.ID}}'],timeout=5).decode().strip().splitlines()
    if len(ids)!=1 or len(ids[0])!=64: raise RuntimeError('Missing or ambiguous exact container identity')
    fmt='{"container_id":{{json .Id}},"name":{{json .Name}},"created_at":{{json .Created}},"image_id":{{json .Image}},"state":{{json .State}}}'
    value=json.loads(command(label+'-inspect',['docker','inspect','--type','container','--format',fmt,ids[0]],timeout=5))
    recheck=json.loads(command(label+'-engine-recheck',['docker','info','--format','{{json .ID}}'],timeout=5))
    if recheck!=engine or value['container_id']!=ids[0] or value['name']!='/tfg-ardupilot-gazebo': raise RuntimeError('Environment changed during metadata capture')
    value.update(engine_id=engine,context=context,endpoint=endpoint)
    s=value['state']
    if s['Running'] is True and s['Status']=='running' and s['Pid']>0 and not any(s[k] for k in ('Paused','Restarting','Dead')): value['status']='ACTIVE'
    else:
        value['status']='STOPPED'
        reasons=stopped_reasons(value)
        if reasons: raise RuntimeError('Uncertain container state: '+str(reasons))
    return value

def guards(label, own_lifecycle=None):
    current=locks.restriction()
    records={}
    for p in sorted(locks.LOCK_ROOT.glob('*.json')):
        raw=p.read_bytes();records[p.name]={'sha256':hashlib.sha256(raw).hexdigest(),'record':json.loads(raw)}
        target=ROOT/(label+'-guard-'+p.name)
        if target.exists(): raise RuntimeError('Repeated guard capture')
        target.write_bytes(raw)
    save(label+'-guards.json',records)
    if own_lifecycle is None:
        if current is not None or records: raise RuntimeError('Reservation or infrastructure restriction present')
    elif (set(records)!={'lifecycle.json'} or current is None or current.get('owner_id')!=own_lifecycle or current.get('state')!='EXECUTING' or current.get('process')!=locks.process_identity()):
        raise RuntimeError('Own lifecycle is not the sole coherent restriction')
    return records

def processes(label,meta):
    host=json.loads(command(label+'-host-processes',[sys.executable,'-c',SCAN_CODE]))
    container={'candidates':[],'errors':[],'basis':'Docker exited/Running=false/Pid=0; no container exec'}
    if meta['status']=='ACTIVE':
        container=json.loads(command(label+'-container-processes',['docker','exec','-i',meta['container_id'],'python3','-'],input=SCAN_CODE.encode()))
    save(label+'-processes.json',{'host':host,'container':container})
    if host['candidates'] or host['errors'] or container['candidates'] or container['errors']:
        raise RuntimeError('Project/ambiguous processes or unreadable process identity present')
    return {'host':host,'container':container}

def check_sources():
    for name,entry in json.loads((ROOT/'session.json').read_text())['sources'].items():
        if hashlib.sha256(Path(name).read_bytes()).hexdigest()!=entry['sha256']: raise RuntimeError('Source changed: '+name)

def precheck():
    report={'status':'BLOCKED','started_at_utc':now()}
    try:
        if json.loads((ROOT/'offline-tests-result.json').read_text())['return_code']!=0: raise RuntimeError('Offline regression tests failed')
        check_sources()
        with locks.file_mutex(locks.LOCK_ROOT/'v1.execution.lock',blocking=False), locks.file_mutex(locks.LOCK_ROOT/'registry.lock',blocking=False):
            report['guards']=guards('precheck')
            report['environment']=metadata('precheck')
            report['processes']=processes('precheck',report['environment'])
        report['status']='CLEAR'
    except Exception as exc: report['reason']=f'{type(exc).__name__}: {exc}'
    report['finished_at_utc']=now();save('precheck.json',report);print(json.dumps(report,indent=2))

def start():
    initial=json.loads((ROOT/'precheck.json').read_text())
    if initial['status']!='CLEAR' or (ROOT/'start-result.json').exists(): raise RuntimeError('No CLEAR precheck or opening already attempted')
    original=lifecycle._backend
    def checked_backend(action,gui,fd,process,log):
        own=json.loads((locks.LOCK_ROOT/'lifecycle.json').read_text())['owner_id']
        guards('atomic-recheck',own_lifecycle=own)
        actual=metadata('atomic-recheck')
        if actual!=initial['environment']: raise RuntimeError('Environment changed since CLEAR precheck')
        processes('atomic-recheck',actual);check_sources()
        save('atomic-recheck.json',{'status':'CLEAR','lifecycle_id':own,'checked_at_utc':now()})
        return original(action,gui,fd,process,log)
    lifecycle._backend=checked_backend
    result=lifecycle.run_lifecycle('start',gui=True,profile='two_drones_rover')
    save('start-result.json',result)
    print(json.dumps(result,indent=2))

def stop():
    if (ROOT/'stop-result.json').exists(): raise RuntimeError('Stop already attempted')
    baseline=json.loads((ROOT/'capture-environment.json').read_text()) if (ROOT/'capture-environment.json').exists() else json.loads((ROOT/'precheck.json').read_text())['environment']
    original=lifecycle._backend
    def checked_stop(action,gui,fd,process,log):
        own=json.loads((locks.LOCK_ROOT/'lifecycle.json').read_text())['owner_id']
        guards('stop-atomic',own_lifecycle=own)
        actual=metadata('stop-atomic')
        for key in ('engine_id','container_id','created_at','image_id','context','endpoint'):
            if actual[key]!=baseline[key]: raise RuntimeError('Environment changed before protected closure')
        if baseline['status']=='ACTIVE' and actual['state']['StartedAt']!=baseline['state']['StartedAt']:
            raise RuntimeError('Container incarnation changed before closure')
        return original(action,gui,fd,process,log)
    lifecycle._backend=checked_stop
    result=lifecycle.run_lifecycle('stop',gui=True,profile='two_drones_rover')
    save('stop-result.json',result);print(json.dumps(result,indent=2))


def capture():
    start_result=json.loads((ROOT/'start-result.json').read_text())
    if start_result['status']!='SUCCESS': raise RuntimeError('No confirmed opening: do not collect inside unknown runtime')
    actual=metadata('capture')
    baseline=json.loads((ROOT/'precheck.json').read_text())['environment']
    for key in ('engine_id','container_id','name','created_at','image_id','context','endpoint'):
        if actual[key]!=baseline[key]: raise RuntimeError('Environment identity changed before capture')
    if actual['status']!='ACTIVE': raise RuntimeError('Environment not active for capture')
    save('capture-environment.json',actual)
    identifier=start_result['operation']['owner_id']
    setup='source /opt/ros/humble/setup.bash && source /root/ardu_ws/install/setup.bash && exec python3 - '+identifier
    raw=command('container-identity-capture',['docker','exec','-i',actual['container_id'],'bash','-lc',setup],
                input=Path('/tmp/rover_identity_capture_container.py').read_bytes(),timeout=25)
    received=time.monotonic()
    data=json.loads(raw)
    folder=ROOT/'container-originals';folder.mkdir()
    import base64
    entries=[]
    for index,entry in enumerate(data.get('files',[])):
        value=base64.b64decode(entry['raw_base64'],validate=True)
        if hashlib.sha256(value).hexdigest()!=entry['sha256']: raise RuntimeError('Capture bytes hash mismatch')
        name=f'{index:03d}-'+Path(entry['source']).name
        (folder/name).write_bytes(value)
        entries.append({k:v for k,v in entry.items() if k!='raw_base64'} | {'evidence_path':'container-originals/'+name})
    save('container-originals-index.json',entries)
    assessment={'status':'BLOCKED','source_association_verified':False,'movement_authorized':False,
                'reason':'Effective DDS/XRCE session association not demonstrated; no parameter services called'}
    if data.get('context') and data.get('worker_after'):
        from tools.rover_environment_identity import assess_identity,digest
        expected=data['context'];worker=data['worker_after']
        identities={k:{a:v[a] for a in ('pid','start_ticks','boot_id')} for k,v in data.get('rechecked_process_identities',{}).items() if all(a in v for a in ('pid','start_ticks','boot_id')) and v.get('state')!='Z'}
        worker_read=[e for e in data['files'] if e['source'].endswith('/worker.json')][-1]
        installed=[e for e in data['files'] if e['source'].endswith('/launch/tfg_demo.launch.py')]
        bundle={'record':worker,'context_sha256':digest(expected),
                'environment':{k:actual[k] for k in ('engine_id','container_id','name','created_at','image_id')},
                'installed_launch_sha256':installed[0]['sha256'] if installed else None,
                'process_clock_scope':'CONTAINER_PROC_BOOT_AND_MONOTONIC','processes':identities,
                'receipt_age_s':time.monotonic()-received,
                'worker_age_s':worker_read['received_monotonic_s']-worker['heartbeat_monotonic_s']}
        assessment=assess_identity(expected,bundle)
    save('identity-assessment.json',assessment)
    print(json.dumps({'worker_alive_matching_identity':data.get('worker_alive_matching_identity'),
                      'launch_alive_matching_identity':data.get('launch_alive_matching_identity'),
                      'worker_state':(data.get('worker_after') or data.get('worker') or {}).get('state'),
                      'ros_topics':(data.get('ros') or {}).get('topics'),
                      'sample_counts':{k:len(v) for k,v in (data.get('ros') or {}).get('samples',{}).items()},
                      'bridge_configs':len(data.get('active_bridge_configs',[])),
                      'errors':data.get('errors'),'assessment':assessment},indent=2))


def postcheck():
    report={'status':'BLOCKED','started_at_utc':now()}
    try:
        with locks.file_mutex(locks.LOCK_ROOT/'v1.execution.lock',blocking=False), locks.file_mutex(locks.LOCK_ROOT/'registry.lock',blocking=False):
            report['guards']=guards('postcheck')
            report['environment']=metadata('postcheck')
            report['processes']=processes('postcheck',report['environment'])
        report['status']='CLEAR_NO_RECOGNIZED_RUNTIME_PROCESSES'
        report['readiness_service_checks']='NOT_CALLED_NO_SERVICES_CONSTRAINT'
    except Exception as exc: report['reason']=f'{type(exc).__name__}: {exc}'
    report['finished_at_utc']=now();save('postcheck.json',report);print(json.dumps(report,indent=2))

if __name__=='__main__':
    {'precheck':precheck,'start':start,'stop':stop,'capture':capture,'postcheck':postcheck}[sys.argv[1]]()
