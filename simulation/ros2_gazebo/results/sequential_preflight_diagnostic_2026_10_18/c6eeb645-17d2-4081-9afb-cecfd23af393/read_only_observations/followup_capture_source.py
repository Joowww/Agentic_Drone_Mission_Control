
import os,json,base64,hashlib,glob
from pathlib import Path
from datetime import datetime,timezone
paths=['/root/.gz/rendering/ogre2.log','/root/.gz/auto_default.log','/root/.gz/sim/8/gui.config','/root/.gz/sim/8/server.config','/root/ardu_ws/install/ardupilot_gz_bringup/share/ardupilot_gz_bringup/launch/tfg_demo_2drones.launch.py','/opt/ros/humble/lib/python3.10/site-packages/ros2topic/verb/echo.py','/opt/ros/humble/lib/python3.10/site-packages/ros2topic/api/__init__.py']
paths+=glob.glob('/tmp/launch_params_*')
files=[]
for p in paths:
    try:
        stat=os.stat(p)
        if stat.st_size>1000000:
            files.append({'path':p,'error':'Size exceeds 1MB diagnostic bound'});continue
        data=Path(p).read_bytes()
        files.append({'path':p,'bytes':len(data),'mtime_utc':datetime.fromtimestamp(stat.st_mtime,timezone.utc).isoformat(),'sha256':hashlib.sha256(data).hexdigest(),'base64':base64.b64encode(data).decode()})
    except OSError as e:files.append({'path':p,'error':str(e)})
print(json.dumps({'captured_at_utc':datetime.now(timezone.utc).isoformat(),'files':files},indent=2))
