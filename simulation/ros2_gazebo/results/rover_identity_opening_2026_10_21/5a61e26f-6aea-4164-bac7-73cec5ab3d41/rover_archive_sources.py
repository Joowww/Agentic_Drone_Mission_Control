import sys,json,base64,hashlib
from pathlib import Path
sys.path.insert(0,'/tmp')
import rover_opening_ops as ops
meta=json.loads((ops.ROOT/'postcheck.json').read_text())['environment']
code=r'''
import json,base64,hashlib,importlib.util
from pathlib import Path
paths=[Path('/tmp/tfg_rover_identity_worker.py'),Path('/tmp/tfg_rover_environment_identity.py'),Path('/tmp/tfg_sim_processes.py')]
spec=importlib.util.find_spec('rclpy')
if spec and spec.origin:
    root=Path(spec.origin).parent
    paths.extend(root/name for name in ('subscription.py','executors.py','node.py'))
result=[]
for p in paths:
    try:
        with p.open('rb') as f: raw=f.read(524289)
        if len(raw)>524288: raise ValueError('Bounded source capture limit')
        result.append({'source':str(p),'sha256':hashlib.sha256(raw).hexdigest(),'size_bytes':len(raw),'mode':p.stat().st_mode,'raw_base64':base64.b64encode(raw).decode()})
    except Exception as exc: result.append({'source':str(p),'error':str(exc)})
print(json.dumps(result))
'''
raw=ops.command('deployed-sources-archive',['docker','exec','-i',meta['container_id'],'bash','-lc','source /opt/ros/humble/setup.bash && source /root/ardu_ws/install/setup.bash && exec python3 -'],input=code.encode(),timeout=10)
rows=json.loads(raw);root=ops.ROOT/'deployed-sources';root.mkdir()
index=[]
for i,row in enumerate(rows):
    if 'raw_base64' in row:
        data=base64.b64decode(row['raw_base64'],validate=True)
        assert hashlib.sha256(data).hexdigest()==row['sha256']
        name=f'{i:02d}-'+Path(row['source']).name
        (root/name).write_bytes(data)
        row={k:v for k,v in row.items() if k!='raw_base64'}|{'evidence_path':'deployed-sources/'+name}
    index.append(row)
ops.save('deployed-sources-index.json',index)
print(json.dumps(index,indent=2))
