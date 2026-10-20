
import os,json,glob,base64,hashlib
from pathlib import Path
from datetime import datetime,timezone
keys={'DISPLAY','WAYLAND_DISPLAY','XDG_RUNTIME_DIR','GZ_SIM_RESOURCE_PATH','GZ_RENDER_ENGINE','IGN_RENDER_ENGINE','LIBGL_ALWAYS_SOFTWARE','MESA_D3D12_DEFAULT_ADAPTER_NAME','QT_QPA_PLATFORM','QT_OPENGL','__GLX_VENDOR_LIBRARY_NAME','GALLIUM_DRIVER','GZ_PARTITION','ROS_DOMAIN_ID','RMW_IMPLEMENTATION'}
processes=[]
for p in Path('/proc').iterdir():
    if not p.name.isdigit():continue
    try:
        args=p.joinpath('cmdline').read_bytes().replace(b'\0',b' ').decode(errors='replace')
        if not any(s in args for s in ['gz sim','arducopter','tfg_demo_2drones.launch.py','parameter_bridge']):continue
        if 'python3 -' in args or 'bash -lc' in args:continue
        fields=p.joinpath('stat').read_text().rpartition(')')[2].split()
        env={}
        for item in p.joinpath('environ').read_bytes().split(b'\0'):
            k,_,v=item.partition(b'=')
            if k.decode(errors='replace') in keys:env[k.decode()]=v.decode(errors='replace')
        processes.append({'pid':int(p.name),'ppid':int(fields[1]),'state':fields[0],'start_ticks':int(fields[19]),'arguments':args,'selected_graphics_ros_environment':env,'stdout_target':os.readlink(p/'fd/1'),'stderr_target':os.readlink(p/'fd/2')})
    except (OSError,ValueError,IndexError):pass
candidates=set()
for pattern in ['/tmp/tfg*.log','/root/.gz/**/*.log','/root/.ignition/**/*.log','/root/.ros/log/**/*.log','/root/.gz/**/gui.config','/root/.gz/**/server.config']:
    candidates.update(p for p in glob.glob(pattern,recursive=True) if Path(p).is_file())
inventory=[]
for p in candidates:
    st=os.stat(p)
    inventory.append({'path':p,'bytes':st.st_size,'mtime_ns':st.st_mtime_ns,'mtime_utc':datetime.fromtimestamp(st.st_mtime,timezone.utc).isoformat()})
inventory.sort(key=lambda x:x['mtime_ns'],reverse=True)
# Capture current launch output and recent ROS/Gazebo logs/config. No devices read.
selected=[];total=0
for info in inventory:
    p=info['path']
    if len(selected)>=40 or total>=25_000_000:break
    if info['mtime_utc'][:10]!='2026-10-18' and p!='/tmp/tfg_demo.log' and not p.endswith('.config'):continue
    length=min(info['bytes'],6_000_000,25_000_000-total)
    offset=max(0,info['bytes']-length)
    try:
        with open(p,'rb') as f:f.seek(offset);data=f.read(length)
        after=os.stat(p)
        selected.append({**info,'offset':offset,'captured_bytes':len(data),'complete_file_at_initial_stat':offset==0 and len(data)==info['bytes'],'size_after_read':after.st_size,'mtime_ns_after_read':after.st_mtime_ns,'sha256':hashlib.sha256(data).hexdigest(),'base64':base64.b64encode(data).decode()});total+=len(data)
    except OSError as exc:selected.append({**info,'error':str(exc)})
assets=[]
for pattern in ['/dev/dxg','/dev/dri/*','/usr/lib/wsl/lib/libd3d12.so','/tmp/.X11-unix/*']:
    for p in glob.glob(pattern):
        st=os.stat(p);assets.append({'path':p,'mode':oct(st.st_mode),'bytes':st.st_size})
print(json.dumps({'captured_at_utc':datetime.now(timezone.utc).isoformat(),'processes':processes,'log_inventory':inventory,'files':selected,'graphics_assets_metadata_only':assets,'selected_shell_environment':{k:os.environ[k] for k in keys if k in os.environ}},indent=2))
