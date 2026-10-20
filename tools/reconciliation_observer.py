"""Explicit read-only inspection collector. Never imported by a flight workflow.

New volatile subscriptions, bounded collection, raw headers and host receipts.
Advancing headers demonstrate progression, NOT absolute generation freshness.
"""
import json
import subprocess

from tools.ros2_flight_control import CONTAINER, ROS_SETUP

WINDOW_SECONDS = 20
COMMAND_TIMEOUT_SECONDS = 35

ROS_OBSERVER = r'''
import json,time
from datetime import datetime,timezone
import rclpy
from rclpy.qos import QoSProfile,ReliabilityPolicy,DurabilityPolicy
from rosidl_runtime_py.convert import message_to_ordereddict
from ardupilot_msgs.msg import Status
from geographic_msgs.msg import GeoPoseStamped
rclpy.init()
node=rclpy.create_node('tfg_explicit_reconciliation_observer')
qos=QoSProfile(depth=5,reliability=ReliabilityPolicy.BEST_EFFORT,durability=DurabilityPolicy.VOLATILE)
samples={v:{'status':[],'position':[]} for v in ('v1','v2')}
started=time.monotonic()
def receive(vehicle,kind,msg):
    values=samples[vehicle][kind]
    if len(values)>=8:
        values.pop(0)
    values.append({'received_at_utc':datetime.now(timezone.utc).isoformat(),
                   'receipt_elapsed_seconds':time.monotonic()-started,
                   'message':message_to_ordereddict(msg)})
subscriptions=[]
for v in samples:
    for kind,topic,cls in [('status','status',Status),('position','geopose/filtered',GeoPoseStamped)]:
        subscriptions.append(node.create_subscription(cls,'/ap/'+v+'/'+topic,
                             lambda msg,v=v,kind=kind:receive(v,kind,msg),qos))
while time.monotonic()-started<20:
    rclpy.spin_once(node,timeout_sec=0.25)
node.destroy_node()
rclpy.shutdown()
print(json.dumps({'samples':samples,'collection_wall_seconds':time.monotonic()-started,
                  'subscription':'NEW_VOLATILE','absolute_generation_age_known':False}))
'''


def collect_observations():
    # Code goes to stdin of a noninteractive docker exec, never a control endpoint.
    result = subprocess.run(["docker", "exec", "-i", CONTAINER, "bash", "-lc",
                             ROS_SETUP + "\nexec python3 -"], input=ROS_OBSERVER,
                            capture_output=True, text=True, timeout=COMMAND_TIMEOUT_SECONDS, check=False)
    if result.returncode:
        raise RuntimeError(f"Read-only collector returned {result.returncode}: {result.stderr[-2048:]}")
    value = json.loads(result.stdout)
    return {**value, "collector_timeout_seconds": COMMAND_TIMEOUT_SECONDS}
