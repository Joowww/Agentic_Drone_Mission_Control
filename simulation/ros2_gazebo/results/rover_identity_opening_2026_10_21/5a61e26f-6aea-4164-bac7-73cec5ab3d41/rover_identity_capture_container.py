# Read-only capture: no service clients, publishers, controls, process signals or writes.
import os,sys,json,time,base64,hashlib
from pathlib import Path
from datetime import datetime,timezone
identifier=sys.argv[1]
if len(identifier)!=36 or any(c not in '0123456789abcdef-' for c in identifier): raise ValueError('Invalid lifecycle id')
root=Path('/tmp/tfg_rover_identity')/identifier
result={'started_at_utc':datetime.now(timezone.utc).isoformat(),'files':[],'errors':[], 'processes':[], 'ros':None}
def read(path,*,tail=False,maximum=262144):
    try:
        p=Path(path)
        if not str(p).startswith(('/tmp/','/root/ardu_ws/install/','/root/ardu_ws/src/')): raise ValueError('Path outside project capture roots')
        with p.open('rb') as f:
            size=os.fstat(f.fileno()).st_size
            if tail and size>maximum: f.seek(size-maximum)
            raw=f.read(maximum+1)
        if len(raw)>maximum: raise ValueError('Source too large for bounded exact read')
        result['files'].append({'source':str(p),'source_size_bytes':size,'tail_only':tail and size>maximum,
                                'captured_size_bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest(),
                                'raw_base64':base64.b64encode(raw).decode(),'received_monotonic_s':time.monotonic()})
        return raw
    except Exception as exc:
        result['errors'].append({'source':str(path),'error':str(exc)})
        return None
context_bytes=read(root/'context.json')
worker_bytes=read(root/'worker.json')
read(root/'worker.log',tail=True)
read('/tmp/tfg_demo.log',tail=True)
context=json.loads(context_bytes) if context_bytes else None
worker=json.loads(worker_bytes) if worker_bytes else None
boot=Path('/proc/sys/kernel/random/boot_id').read_text().strip()
for p in Path('/proc').iterdir():
    if not p.name.isdigit(): continue
    try:
        args=[x.decode(errors='replace') for x in (p/'cmdline').read_bytes().split(b'\0') if x]
        fields=(p/'stat').read_text().rpartition(')')[2].split()
        if not args: continue
        if (any(Path(x).name in {'arducopter','ardurover','parameter_bridge','micro_ros_agent','tfg_rover_identity_worker.py'} for x in args[:2])
                or ('launch' in args and 'ardupilot_gz_bringup' in args)):
            result['processes'].append({'pid':int(p.name),'start_ticks':int(fields[19]),'ppid':int(fields[1]),'state':fields[0], 'boot_id':boot,'argv':args})
    except (FileNotFoundError,ProcessLookupError): pass
    except Exception as exc: result['errors'].append({'source':str(p),'error':str(exc)})
result['context']=context;result['worker']=worker
identities={p['pid']:{k:p[k] for k in ('pid','start_ticks','boot_id')} for p in result['processes'] if p['state']!='Z'}
result['worker_alive_matching_identity']=bool(worker and identities.get(worker['worker']['pid'])==worker['worker'])
result['launch_alive_matching_identity']=bool(context and identities.get(context['launch_process']['pid'])==context['launch_process'])
if not result['worker_alive_matching_identity'] or not result['launch_alive_matching_identity']:
    result['blocked_reason']='Passive worker/context absent or process identity not live; no ROS collector started'
else:
    for path in ['/root/ardu_ws/install/ardupilot_gz_bringup/share/ardupilot_gz_bringup/launch/tfg_demo.launch.py',
                 '/root/ardu_ws/install/ardupilot_gz_bringup/share/ardupilot_gz_bringup/launch/robots/wildthumper.launch.py',
                 '/root/ardu_ws/install/ardupilot_gz_bringup/share/ardupilot_gz_bringup/launch/robots/robot.launch.py']:
        read(path)
    bridge_processes=[p for p in result['processes'] if any(Path(x).name=='parameter_bridge' for x in p['argv'][:2]) and '__ns:=/rover1' in p['argv']]
    result['rover_bridge_process_candidates']=bridge_processes
    try:
        import yaml
        for bridge in bridge_processes:
            args=bridge['argv']
            for i,item in enumerate(args[:-1]):
                if item!='--params-file': continue
                raw=read(args[i+1])
                if raw:
                    params=yaml.safe_load(raw)
                    def find(node):
                        if isinstance(node,dict):
                            if isinstance(node.get('ros__parameters'),dict) and isinstance(node['ros__parameters'].get('config_file'),str):
                                cfg=node['ros__parameters']['config_file'];data=read(cfg)
                                if data: result.setdefault('active_bridge_configs',[]).append({'process_pid':bridge['pid'],'source':cfg,'parsed':yaml.safe_load(data)})
                            for value in node.values(): find(value)
                        elif isinstance(node,list):
                            for value in node: find(value)
                    find(params)
    except Exception as exc: result['errors'].append({'stage':'bridge_config','error':str(exc)})
    for p in result['processes']:
        if not any(Path(x).name=='ardurover' for x in p['argv'][:2]): continue
        args=p['argv']
        for i,arg in enumerate(args[:-1]):
            if arg in ('--defaults','-P'):
                for name in args[i+1].split(','):
                    if name.startswith('/root/ardu_ws/'): read(name)
    try:
        import rclpy
        from rclpy.qos import QoSProfile,ReliabilityPolicy,DurabilityPolicy
        from rosidl_runtime_py.convert import message_to_ordereddict
        from ardupilot_msgs.msg import Status
        from nav_msgs.msg import Odometry
        rclpy.init()
        node=rclpy.create_node('tfg_readonly_rover_identity_capture',enable_rosout=False,start_parameter_services=False)
        q=QoSProfile(depth=5,reliability=ReliabilityPolicy.BEST_EFFORT,durability=DurabilityPolicy.VOLATILE)
        samples={'status':[],'odometry':[]}
        def receive(kind,msg,info):
            if len(samples[kind])<8:
                samples[kind].append({'message':message_to_ordereddict(msg),'publisher_gid':bytes(info.publisher_gid).hex(),
                    'received_monotonic_s':time.monotonic(),'received_at_utc':datetime.now(timezone.utc).isoformat()})
        def cb(kind):
            return lambda msg,info:receive(kind,msg,info)
        subscriptions=[node.create_subscription(cls,topic,cb(kind),q) for kind,topic,cls in
                       [('status','/ap/v3/status',Status),('odometry','/rover1/odometry',Odometry)]]
        began=time.monotonic()
        while time.monotonic()-began<4:
            rclpy.spin_once(node,timeout_sec=.1)
        target={'/ap/v3/status','/rover1/odometry','/ap/v3/cmd_vel'}
        topics={name:types for name,types in node.get_topic_names_and_types() if name in target}
        publishers={}
        for topic in ('/ap/v3/status','/rover1/odometry'):
            publishers[topic]=[{'node_name':p.node_name,'node_namespace':p.node_namespace,'topic_type':p.topic_type,
                                'endpoint_gid':bytes(p.endpoint_gid).hex()} for p in node.get_publishers_info_by_topic(topic)]
        result['ros']={'samples':samples,'topics':topics,'publishers':publishers,
                       'services_discovered_no_calls':[(n,t) for n,t in node.get_service_names_and_types() if n.startswith('/ap/v3/')],
                       'collection_duration_wall_s':time.monotonic()-began,'clock_scope':'CONTAINER_HOST_MONOTONIC_NOT_SIM_TIME',
                       'odometry_units_contract':{'linear':'m/s','angular':'rad/s','basis':'nav_msgs/msg/Odometry contract; no explicit unit fields observed'}}
        node.destroy_node();rclpy.shutdown()
    except Exception as exc: result['errors'].append({'stage':'ROS_readonly_subscriptions_and_discovery','error':str(exc)})
    raw=read(root/'worker.json')
    result['worker_after']=json.loads(raw) if raw else None
result['rechecked_process_identities']={}
for identity in ([context.get('launch_process'), worker.get('worker')] if context and worker else []):
    try:
        p=Path('/proc')/str(identity['pid']);f=(p/'stat').read_text().rpartition(')')[2].split()
        result['rechecked_process_identities'][str(identity['pid'])]={'pid':identity['pid'],'start_ticks':int(f[19]),'boot_id':boot,'state':f[0]}
    except Exception as exc:
        result['rechecked_process_identities'][str(identity['pid'])]={'error':str(exc)}
result['finished_at_utc']=datetime.now(timezone.utc).isoformat()
print(json.dumps(result,allow_nan=False))
