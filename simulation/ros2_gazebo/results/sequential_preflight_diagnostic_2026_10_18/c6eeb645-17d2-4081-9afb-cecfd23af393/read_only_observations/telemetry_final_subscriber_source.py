
import json,time
from datetime import datetime,timezone
import rclpy
from rclpy.qos import QoSProfile,ReliabilityPolicy,DurabilityPolicy,HistoryPolicy
from rosidl_runtime_py.utilities import get_message
from rosidl_runtime_py.convert import message_to_ordereddict
TOPICS=['/ap/v1/status','/ap/v2/status','/ap/v1/geopose/filtered','/ap/v2/geopose/filtered','/ap/v1/gps_global_origin/filtered','/ap/v2/gps_global_origin/filtered','/ap/v1/clock','/ap/v2/clock','/drone1/clock','/drone2/clock']
start=time.monotonic()
rclpy.init()
node=rclpy.create_node('tfg_readonly_diagnostic_telemetry',start_parameter_services=False,enable_rosout=False)
qos=QoSProfile(depth=10,reliability=ReliabilityPolicy.BEST_EFFORT,durability=DurabilityPolicy.VOLATILE,history=HistoryPolicy.KEEP_LAST)
subscriptions={}; observations={t:[] for t in TOPICS}; last={}; errors={}
while time.monotonic()-start<13:
    available=dict(node.get_topic_names_and_types())
    for topic in TOPICS:
        if topic in subscriptions or not available.get(topic): continue
        try:
            cls=get_message(available[topic][0])
            def receive(msg,topic=topic):
                now=time.monotonic()
                if len(observations[topic])<3 and now-last.get(topic,-100)>1:
                    observations[topic].append({'received_at_utc':datetime.now(timezone.utc).isoformat(),'elapsed_seconds':now-start,'message':message_to_ordereddict(msg)})
                    last[topic]=now
            subscriptions[topic]=node.create_subscription(cls,topic,receive,qos)
        except Exception as exc: errors[topic]=repr(exc)
    rclpy.spin_once(node,timeout_sec=0.15)
    if all(len(observations[t])>=3 for t in TOPICS): break
publishers={}
for topic in TOPICS:
    publishers[topic]=[{'node_name':p.node_name,'node_namespace':p.node_namespace,'topic_type':p.topic_type,'reliability':str(p.qos_profile.reliability),'durability':str(p.qos_profile.durability)} for p in node.get_publishers_info_by_topic(topic)]
print(json.dumps({'captured_at_utc':datetime.now(timezone.utc).isoformat(),'elapsed_seconds':time.monotonic()-start,'subscriber_only':True,'requested_reader_qos':'best_effort/volatile; no publisher or configuration changes','observations':observations,'publishers':publishers,'errors':errors},indent=2),flush=True)
node.destroy_node();rclpy.shutdown()
