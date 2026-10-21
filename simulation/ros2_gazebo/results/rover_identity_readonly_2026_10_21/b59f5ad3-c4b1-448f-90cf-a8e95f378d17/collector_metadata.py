import json, subprocess, time
from pathlib import Path
from datetime import datetime, timezone
import sys
root=Path('/tmp/rover_readonly_current_path.txt').read_text().strip()
root=Path(root)
label=sys.argv[1]
records=[]
def read(name,args):
    began=time.monotonic()
    event={'operation':name,'command':['docker',*args],'started_at_utc':datetime.now(timezone.utc).isoformat(),'started_monotonic_s':began,'timeout_s':5,'return_code':None}
    try:
        result=subprocess.run(event['command'],capture_output=True,timeout=5,check=False)
        stdout,stderr=result.stdout,result.stderr; event['return_code']=result.returncode
    except (OSError,subprocess.TimeoutExpired) as exc:
        stdout=getattr(exc,'stdout',None) or b''; stderr=getattr(exc,'stderr',None) or b''
        event['error']=f'{type(exc).__name__}: {exc}'
    event.update(finished_at_utc=datetime.now(timezone.utc).isoformat(),duration_wall_s=time.monotonic()-began)
    for kind,data in [('stdout',stdout),('stderr',stderr)]:
        filename=f'{label}-{name}.{kind}.bin'; (root/filename).write_bytes(data)
        event[kind+'_path']=filename
    records.append(event)
    (root/(label+'-commands.json')).write_text(json.dumps(records,indent=2)+'\n')
    if event['return_code']!=0: raise RuntimeError(name+': '+stderr.decode(errors='replace')[:1800]+event.get('error',''))
    return stdout.decode().strip()
summary={'status':'BLOCKED','stage':'DOCKER_METADATA','observed':{},'uncollected':['worker','ROS_GIDs_and_samples','active_bridge_YAML','effective_DDS_parameters_and_XRCE_session']}
try:
    o=summary['observed']
    o['docker_context']=read('context',['context','show'])
    o['endpoint']=read('endpoint',['context','inspect','--format','{{.Name}} {{json .Endpoints.docker.Host}}'])
    o['engine']=json.loads(read('engine',['info','--format','{"engine_id":{{json .ID}},"name":{{json .Name}},"operating_system":{{json .OperatingSystem}}}']))
    ids=read('container_ids',['ps','--all','--no-trunc','--filter','name=^/tfg-ardupilot-gazebo$','--format','{{.ID}}']).splitlines()
    if len(ids)!=1 or len(ids[0])!=64: raise RuntimeError('Exact named container absent or ambiguous; not termination evidence')
    fmt='{"container_id":{{json .Id}},"name":{{json .Name}},"created_at":{{json .Created}},"image_id":{{json .Image}},"state":{{json .State}}}'
    o['container']=json.loads(read('container',['inspect','--type','container','--format',fmt,ids[0]]))
    recheck=json.loads(read('engine_recheck',['info','--format','{"engine_id":{{json .ID}}}']))
    ids2=read('container_ids_recheck',['ps','--all','--no-trunc','--filter','name=^/tfg-ardupilot-gazebo$','--format','{{.ID}}']).splitlines()
    if recheck['engine_id']!=o['engine']['engine_id'] or ids2!=ids or o['container']['container_id']!=ids[0]: raise RuntimeError('Docker engine/container identity changed during collection')
    state=o['container']['state']
    if state['Running'] is not True or state['Status']!='running' or state['Pid']<=0 or state['Paused'] or state['Restarting'] or state['Dead']:
        summary['reason']='Container is not an active stable runtime; STOP without docker exec or ROS collection'
        summary['stage']='CONTAINER_NOT_ACTIVE'
    else:
        summary.update(status='METADATA_ACTIVE_REQUIRES_WORKER_CHECK',stage='WORKER_CHECK_PENDING')
except Exception as exc:
    summary['reason']=f'{type(exc).__name__}: {exc}'
summary['finished_at_utc']=datetime.now(timezone.utc).isoformat()
(root/(label+'-summary.json')).write_text(json.dumps(summary,indent=2)+'\n')
print(json.dumps(summary,indent=2))
