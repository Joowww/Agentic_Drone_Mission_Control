
import os,json,base64,hashlib
from pathlib import Path
from datetime import datetime,timezone
names=['/tmp/tmp_rbh5s2k.yaml','/tmp/tmp_426fxnn.yaml']
files=[]
for p in names:
    try:
        data=Path(p).read_bytes();st=os.stat(p)
        files.append({'path':p,'bytes':len(data),'mtime_utc':datetime.fromtimestamp(st.st_mtime,timezone.utc).isoformat(),'sha256':hashlib.sha256(data).hexdigest(),'base64':base64.b64encode(data).decode()})
    except OSError as e:files.append({'path':p,'error':str(e)})
meshes=[]
for name in ['iris_with_standoffs/meshes/iris.dae','iris_with_standoffs/meshes/iris_prop_cw.dae','gimbal_small_3d/meshes/base_plate.dae']:
    p=Path('/root/ardu_ws/install/ardupilot_gazebo/share/ardupilot_gazebo/models')/name
    try:
        s=p.stat();meshes.append({'path':str(p),'exists':True,'bytes':s.st_size,'mtime_utc':datetime.fromtimestamp(s.st_mtime,timezone.utc).isoformat()})
    except OSError as e:meshes.append({'path':str(p),'exists':False,'error':str(e)})
print(json.dumps({'captured_at_utc':datetime.now(timezone.utc).isoformat(),'files':files,'mesh_files_metadata_only':meshes}))
