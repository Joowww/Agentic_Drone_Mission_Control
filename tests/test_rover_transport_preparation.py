"""Isolated public API doubles; never initialize ROS or create an operational client."""
import sys
import time
from types import ModuleType, SimpleNamespace as NS
from unittest.mock import Mock

import pytest

from tools import rover_ros2_adapter as ros
from tools import rover_identity_inventory as inv
from tools.rover_control import RoverControlCore, RoverControlError


@pytest.fixture
def fake_ros(monkeypatch):
    callbacks={}
    node=NS(create_subscription=lambda cls,topic,callback,qos:callbacks.setdefault(topic,callback),
        create_client=Mock(),create_publisher=Mock(),destroy_node=Mock())
    context=NS(shutdown=Mock())
    rclpy=ModuleType('rclpy');rclpy.init=Mock();rclpy.create_node=Mock(return_value=node)
    rclpy.spin_until_future_complete=Mock()
    monkeypatch.setitem(sys.modules,'rclpy',rclpy)
    packages={'rclpy.context':{'Context':lambda:context},
        'rclpy.qos':{'QoSProfile':lambda **kw:kw,'ReliabilityPolicy':NS(BEST_EFFORT=1),'DurabilityPolicy':NS(VOLATILE=1)},
        'ardupilot_msgs.msg':{'Status':object},'ardupilot_msgs.srv':{'ModeSwitch':object,'ArmMotors':object},
        'geometry_msgs.msg':{'TwistStamped':object},'nav_msgs.msg':{'Odometry':object},
        'rosidl_runtime_py.convert':{'message_to_ordereddict':lambda msg:msg},
        'rcl_interfaces.srv':{'GetParameters':NS(Request=lambda:NS(names=[]))}}
    for name,values in packages.items():
        module=ModuleType(name)
        for key,value in values.items():setattr(module,key,value)
        monkeypatch.setitem(sys.modules,name,module)
    return rclpy,node,context,callbacks


def test_physical_factory_is_lazy_and_real_guard_blocks_before_ros(monkeypatch):
    native=Mock();monkeypatch.setattr(ros,'NativeRos2Session',native)
    binding=ros.MotionBinding('1'*64,'2'*64,'3'*48)
    factory=ros.physical_adapter_factory({},lambda:{},binding,call_timeout_s=.1)
    native.assert_not_called()
    with pytest.raises(RuntimeError,match='BLOCKED'):factory(lambda event:None)
    native.assert_not_called()


def test_factory_wires_current_guard_without_new_public_worker_api(fake_ros,monkeypatch):
    # TEST-ONLY substitute of an unsatisfied source guard; never accreditation.
    monkeypatch.setattr(ros.RoverEnvironmentGuard,'require_motion_source',lambda self:None)
    expected={'lifecycle_id':'fixture-session'}
    adapter=ros.physical_adapter_factory(expected,lambda:{},ros.MotionBinding('1'*64,'2'*64,'3'*48),call_timeout_s=.2)(Mock())
    assert adapter.session.identity_guard.expected==expected
    adapter.session.close();adapter.session.close()
    fake_ros[1].destroy_node.assert_called_once();fake_ros[2].shutdown.assert_called_once()


def test_constructor_partial_failure_releases_both_resources(fake_ros):
    fake_ros[1].create_client.side_effect=RuntimeError('synthetic creation failure')
    with pytest.raises(RuntimeError):ros.NativeRos2Session()
    fake_ros[1].destroy_node.assert_called_once();fake_ros[2].shutdown.assert_called_once()


def test_close_failure_is_uncertain_even_if_other_resource_closes(fake_ros):
    session=ros.NativeRos2Session()
    fake_ros[1].destroy_node.side_effect=RuntimeError('synthetic')
    with pytest.raises(RoverControlError,match='uncertain'):session.close()
    fake_ros[2].shutdown.assert_called_once()
    assert session.closed is False
    with pytest.raises(RoverControlError,match='uncertain'):session.close()
    fake_ros[1].destroy_node.assert_called_once()


def test_resource_deadline_cannot_claim_closed_on_blocked_cleanup(fake_ros):
    session=ros.NativeRos2Session(resource_timeout_s=.02)
    late=[]
    def blocked():time.sleep(.3);late.append(True)
    fake_ros[1].destroy_node=blocked
    start=time.monotonic()
    with pytest.raises(RoverControlError,match='uncertain'):session.close()
    assert time.monotonic()-start<.2 and not late and not session.closed


def test_factory_cancellation_precedes_identity_and_node_creation(monkeypatch):
    native=Mock();monkeypatch.setattr(ros,'NativeRos2Session',native)
    factory=ros.physical_adapter_factory({},Mock(),ros.MotionBinding('1'*64,'2'*64,'3'*48),
        call_timeout_s=.1,cancelled=lambda:True)
    with pytest.raises(RoverControlError,match='CANCELLED'):factory(Mock())
    native.assert_not_called()


def test_callback_sample_identity_remains_unavailable(fake_ros,monkeypatch):
    session=ros.NativeRos2Session()
    for callback in fake_ros[3].values():callback({'header':{'stamp':{'sec':1,'nanosec':0}}})
    assert all(row[2] is None for row in session.latest.values())
    with pytest.raises(RoverControlError,match='identity worker'):session.probe(timeout_s=.1)
    fake_ros[1].create_client.return_value.call_async.assert_not_called()
    fake_ros[1].create_publisher.return_value.publish.assert_not_called()


def test_cancelled_native_exchange_never_calls_transport(fake_ros,monkeypatch):
    session=ros.NativeRos2Session(cancelled=lambda:True)
    monkeypatch.setattr(ros,'assert_execution_authority',lambda interface:None)
    session._require_identity=lambda **kw:None
    with pytest.raises(RoverControlError,match='CANCELLED'):
        session.exchange(RoverControlCore.velocity_message(.1,0.),timeout_s=.1)
    fake_ros[1].create_publisher.return_value.publish.assert_not_called()


def test_blocked_native_call_is_interrupted_without_late_continuation(fake_ros,monkeypatch):
    session=ros.NativeRos2Session();session._require_identity=lambda **kw:None
    monkeypatch.setattr(ros,'assert_execution_authority',lambda interface:None)
    session.mode_type=NS(Request=lambda:NS(mode=None));late=[]
    def blocked(request):time.sleep(.3);late.append(True)
    session.client.call_async=blocked
    command={'kind':'service','endpoint':ros.MODE,'type':'ardupilot_msgs/srv/ModeSwitch','payload':{'mode':4}}
    start=time.monotonic()
    with pytest.raises(TimeoutError) as caught:session.exchange(command,timeout_s=.02)
    assert time.monotonic()-start<.2 and caught.value.diagnostic['effects']=='UNCONFIRMED'
    time.sleep(.03);assert not late


@pytest.mark.parametrize('values,expected',[
    ([NS(type=2,integer_value=3),NS(type=2,integer_value=1)],{'MAV_SYSID':3,'DDS_USE_NS':1}),
    ([NS(type=0),NS(type=0)],{'MAV_SYSID':None,'DDS_USE_NS':None}),
    ([NS(type=3,double_value=3.),NS(type=2,integer_value=1)],None),
    ([NS(type=2,integer_value=300),NS(type=2,integer_value=1)],None),
    ([NS(type=2,integer_value=3)],None)])
def test_public_parameter_read_typed_cardinality_and_cleanup(fake_ros,values,expected):
    _,node,_,_=fake_ros
    future=NS(done=lambda:True,result=lambda:NS(values=values))
    client=NS(service_is_ready=lambda:True,call_async=Mock(return_value=future))
    node.create_client.return_value=client;node.destroy_client=Mock()
    if expected is None:
        with pytest.raises(ValueError):inv.read_identity_parameters(node,'/ap/v3/get_parameters',('MAV_SYSID','DDS_USE_NS'),timeout_s=.1)
    else:
        assert inv.read_identity_parameters(node,'/ap/v3/get_parameters',('MAV_SYSID','DDS_USE_NS'),timeout_s=.1)==expected
    node.destroy_client.assert_called_once_with(client);client.call_async.assert_called_once()
    assert client.call_async.call_args.args[0].names==['MAV_SYSID','DDS_USE_NS']


def test_parameter_timeout_no_retry_and_local_future_cancel(fake_ros):
    rclpy,node,_,_=fake_ros
    future=NS(done=lambda:False,cancel=Mock())
    client=NS(service_is_ready=lambda:True,call_async=Mock(return_value=future))
    node.create_client.return_value=client;node.destroy_client=Mock()
    rclpy.spin_until_future_complete.side_effect=lambda *a,**kw:time.sleep(.3)
    with pytest.raises(TimeoutError):inv.read_identity_parameters(node,'/ap/v3/get_parameters',('MAV_SYSID','DDS_USE_NS'),timeout_s=.02)
    future.cancel.assert_called_once();client.call_async.assert_called_once();node.destroy_client.assert_called_once()


def test_parameter_client_cleanup_negative_does_not_return_accepted_value(fake_ros):
    _,node,_,_=fake_ros
    future=NS(done=lambda:True,result=lambda:NS(values=[NS(type=2,integer_value=3),NS(type=2,integer_value=1)]))
    node.create_client.return_value=NS(service_is_ready=lambda:True,call_async=Mock(return_value=future))
    node.destroy_client=Mock(return_value=False)
    with pytest.raises(RuntimeError,match='destruction not confirmed'):
        inv.read_identity_parameters(node,'/ap/v3/get_parameters',('MAV_SYSID','DDS_USE_NS'),timeout_s=.1)


def test_graph_reader_parameter_transport_is_opt_in_and_detects_change():
    service=[('/ap/v3/get_parameters',['rcl_interfaces/srv/GetParameters'])]
    node=NS(get_service_names_and_types=Mock(return_value=service))
    transport=Mock(return_value={'MAV_SYSID':3,'DDS_USE_NS':1})
    reader=inv.RosGraphInventoryReader(node,parameter_transport=transport)
    result=reader.get_parameters(service[0][0],('MAV_SYSID','DDS_USE_NS'),timeout_s=.1)
    assert result.value['MAV_SYSID']==3 and 'UNVERIFIED' in result.source
    node.get_service_names_and_types.side_effect=[service,[]]
    with pytest.raises(ValueError,match='changed'):reader.get_parameters(service[0][0],('MAV_SYSID','DDS_USE_NS'),timeout_s=.1)


@pytest.mark.parametrize('content,kind,valid',[
    ('<sdf version="1.9"><model name="fixture"/></sdf>',4,True),
    ('<robot name="urdf-is-not-this-launch"/>',4,False),('broken',4,False),('',4,False),
    ('x'*262145,4,False),('<sdf/>',0,False)])
def test_runtime_description_read_is_typed_bounded_and_not_entity_identity(fake_ros,content,kind,valid):
    import hashlib
    import xml.etree.ElementTree as ET
    _,node,_,_=fake_ros
    node.get_service_names_and_types=lambda:[('/rover1/robot_state_publisher/get_parameters',['rcl_interfaces/srv/GetParameters'])]
    future=NS(done=lambda:True,result=lambda:NS(values=[NS(type=kind,string_value=content)]))
    client=NS(service_is_ready=lambda:True,call_async=Mock(return_value=future))
    node.create_client.return_value=client;node.destroy_client=Mock(return_value=True)
    if valid:
        reading=inv.read_rover_model_description(node,timeout_s=.1)
        assert reading.value['sha256']==hashlib.sha256(content.encode()).hexdigest()
        assert reading.value['runtime_instantiation_verified'] is False and 'UNVERIFIED' in reading.source
    else:
        with pytest.raises((ValueError,ET.ParseError)):
            inv.read_rover_model_description(node,timeout_s=.1)
    assert client.call_async.call_args.args[0].names==['robot_description']
    client.call_async.assert_called_once();node.destroy_client.assert_called_once()


def test_description_absent_or_blocked_discovery_precedes_client(fake_ros):
    _,node,_,_=fake_ros;node.get_service_names_and_types=lambda:[]
    with pytest.raises(ValueError,match='not discovered'):inv.read_rover_model_description(node,timeout_s=.1)
    node.create_client.assert_not_called()
    def blocked():time.sleep(.3);return []
    node.get_service_names_and_types=blocked
    with pytest.raises(TimeoutError):inv.read_rover_model_description(node,timeout_s=.02)
    node.create_client.assert_not_called()
