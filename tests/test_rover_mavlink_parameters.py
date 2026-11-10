from types import SimpleNamespace

import pytest

from tools.rover_mavlink_parameters import collect
from tools.rover_parameter_correlation import REQUIRED, verify


class Message:
    def __init__(self, kind, system=3, component=1, **fields):
        self.kind = kind
        self.system = system
        self.component = component
        self.__dict__.update(fields)

    def get_seq(self):
        return getattr(self,'sequence',None)

    def get_type(self):
        return self.kind

    def get_srcSystem(self):
        return self.system

    def get_srcComponent(self):
        return self.component


class FakeMav:
    def __init__(self, owner, values, wrong_source=False):
        self.owner = owner
        self.values = values
        self.wrong_source = wrong_source
        self.sent = []
        self.sequence=10

    def param_request_read_send(self, system, component, name, index):
        self.sent.append((system, component, name, index))
        key = name.decode('ascii')
        if key not in self.values:
            return
        source = self.wrong_source if isinstance(self.wrong_source,tuple) else ((9, 1) if self.wrong_source else (system, component))
        self.sequence=(self.sequence+1)%256
        self.owner.queue.append(Message(
            'PARAM_VALUE', *source, param_id=name, param_value=self.values[key],
            param_type=9, param_count=2, param_index=len(self.sent)-1, sequence=self.sequence,
            tfg_received_monotonic_s=5.0))


class FakeConnection:
    def __init__(self, values, *, heartbeat=True, wrong_source=False, firmware=True):
        self.queue = []
        if heartbeat:
            self.queue.append(Message('HEARTBEAT', 3, 1, autopilot=3, type=10, mavlink_version=3))
        if firmware:
            self.queue.append(Message('AUTOPILOT_VERSION', 3, 1, flight_sw_version=123,
                                      board_version=4, vendor_id=9, product_id=2, uid=55, uid2=b'id'))
        self.mav = FakeMav(self, values, wrong_source=wrong_source)
        self.recv_calls = []

    def recv_match(self, *, type, blocking, timeout=None):
        self.recv_calls.append((type, blocking, timeout))
        for index, msg in enumerate(self.queue):
            if msg.get_type() == type:
                return self.queue.pop(index)
        return None


def context():
    process = {'pid': 44, 'start_ticks': 88, 'exe_sha256': 'a' * 64}
    conn = {'local_endpoint': '127.0.0.1:14550',
            'remote_endpoint': '127.0.0.1:14551', 'transport': 'UDP'}
    firmware = 'b' * 64
    provenance = {'socket_owner_verified': True, 'connection_identity': conn,
                  'target_process': process, 'lifecycle_id': 'life-1',
                  'host_boot_id': 'boot-1', 'firmware_sha256': firmware}
    return dict(lifecycle_id='life-1', host_boot_id='boot-1',
                target_process=process, connection_identity=conn,
                firmware_sha256=firmware, provenance=provenance)


def test_collect_matches_heartbeat_sysid_compid_and_param_value_with_provenance():
    connection = FakeConnection({'MAV_SYSID': 3, 'GUID_TIMEOUT': 3.0})
    result = collect(connection, parameters=('MAV_SYSID', 'GUID_TIMEOUT'),
                     utc=lambda: '2026-11-06T12:00:00Z', monotonic=lambda: 5.0,
                     **context())
    assert result['status'] == 'COMPLETE'
    assert result['live_read'] is None
    assert result['target_system'] == 3 and result['target_component'] == 1
    assert result['schema']=='tfg.rover.mavlink-parameter-capture/2'
    assert result['sequence_integrity']=='VERIFIED_FOR_CAPTURED_RESPONSES'
    assert result['source_association'] == 'SOCKET_OWNER_AND_MAVLINK_TARGET_CORRELATED'
    assert result['heartbeat']['system_id'] == 3
    assert result['firmware_report_status'] == 'OBSERVED'
    assert result['autopilot_version_report']['flight_sw_version'] == 123
    assert result['autopilot_version_report']['uid2'] == '6964'
    assert result['values'] == {'MAV_SYSID': 3.0, 'GUID_TIMEOUT': 3.0}
    assert [m[2] for m in connection.mav.sent] == [b'MAV_SYSID', b'GUID_TIMEOUT']
    assert all(m[0:2] == (3, 1) and m[3] == -1 for m in connection.mav.sent)
    assert result['parameter_writes'] == result['control_messages_sent'] == 0
    assert result['movement_authorized'] is False
    assert len(result['responses']) == 2


def test_heartbeat_without_socket_join_stays_unverified():
    connection = FakeConnection({'GUID_TIMEOUT': 3.0})
    args = context()
    args.pop('provenance')
    result = collect(connection, parameters=('GUID_TIMEOUT',), monotonic=lambda:5.0, **args)
    assert result['status'] == 'COMPLETE'
    assert result['source_association'] == 'UNVERIFIED'
    assert result['target_system'] == 3 and result['target_component'] == 1
    assert result['schema']=='tfg.rover.mavlink-parameter-capture/2'
    assert result['sequence_integrity']=='VERIFIED_FOR_CAPTURED_RESPONSES'


def test_wrong_source_and_missing_parameter_are_not_attributed_or_filled():
    connection = FakeConnection({'GUID_TIMEOUT': 3.0}, wrong_source=True)
    result = collect(connection, parameters=('GUID_TIMEOUT',), monotonic=lambda:5.0,**context())
    assert result['status'] == 'INCOMPLETE'
    assert result['values'] == {}
    assert result['responses'][0]['status'] == 'MISSING'


def test_missing_heartbeat_sends_no_parameter_request():
    connection = FakeConnection({}, heartbeat=False)
    result = collect(connection, parameters=('GUID_TIMEOUT',), monotonic=lambda:5.0,**context())
    assert result['reason'] == 'HEARTBEAT_MISSING'
    assert result['values'] == {}
    assert connection.mav.sent == []


@pytest.mark.parametrize('timeout', [0, -1, 5.01, True, float('nan')])
def test_timeout_is_bounded(timeout):
    connection = FakeConnection({})
    with pytest.raises(ValueError, match='timeout'):
        collect(connection, parameters=('GUID_TIMEOUT',), timeout_s=timeout, monotonic=lambda:5.0,**context())


def test_synthetic_capture_never_passes_the_live_cross_source_verifier():
    values = {name: 1.0 for name in REQUIRED}
    values.update(MAV_SYSID=3, DDS_USE_NS=1)
    connection = FakeConnection(values)
    ctx = context()
    result = collect(connection, parameters=REQUIRED, monotonic=lambda:5.0,**ctx)
    ros = {'host_boot_id': ctx['host_boot_id'], 'lifecycle_id': ctx['lifecycle_id'],
           'target_process': ctx['target_process'], 'firmware_sha256': ctx['firmware_sha256'],
           'source_association': 'NATIVE_RESPONSE_SAMPLEINFO_TO_TARGET_PROCESS',
           'live_read': True, 'sysid': 3, 'component_id': 1, 'values': dict(values)}
    verdict = verify(ros, result)
    assert verdict['verdict'] == 'UNVERIFIED'
    assert 'NOT_BOTH_LIVE_READS' in verdict['reasons']
    assert result['live_read'] is None
    assert result['movement_authorized'] is False



def test_duplicate_normalized_parameter_names_are_rejected():
    with pytest.raises(ValueError,match='parameter name set'):
        collect(FakeConnection({'GUID_TIMEOUT':3}),parameters=('guid_timeout',' GUID_TIMEOUT '),monotonic=lambda:5.0,**context())


def test_late_parameter_value_is_rejected():
    connection=FakeConnection({'GUID_TIMEOUT':3.0})
    connection.mav.param_request_read_send=lambda *args: connection.queue.append(
        Message('PARAM_VALUE',3,1,param_id=b'GUID_TIMEOUT',param_value=3.0,sequence=11,
                tfg_received_monotonic_s=4.0))
    out=collect(connection,parameters=('GUID_TIMEOUT',),monotonic=lambda:5.0,**context())
    assert out['status']=='INCOMPLETE'
    assert 'LATE_OR_FUTURE_PARAM_VALUE' in out['rejection_reasons']
    assert out['values']=={}


def test_missing_sequence_and_wrong_component_are_rejected():
    c=FakeConnection({'GUID_TIMEOUT':3.0})
    c.mav.param_request_read_send=lambda *args: c.queue.append(
        Message('PARAM_VALUE',3,2,param_id=b'GUID_TIMEOUT',param_value=3.0,sequence=11,
                tfg_received_monotonic_s=5.0))
    out=collect(c,parameters=('GUID_TIMEOUT',),monotonic=lambda:5.0,**context())
    assert out['status']=='INCOMPLETE'
    assert 'MAVLINK_SOURCE_MISMATCH' in out['rejection_reasons']


def test_unknown_firmware_and_unjoined_identity_never_accredit():
    c=FakeConnection({'GUID_TIMEOUT':3.0},firmware=False)
    ctx=context(); out=collect(c,parameters=('GUID_TIMEOUT',),monotonic=lambda:5.0,**ctx)
    assert out['firmware_report_status']=='NOT_OBSERVED'
    assert out['source_association']=='SOCKET_OWNER_AND_MAVLINK_TARGET_CORRELATED'
    ctx.pop('provenance')
    out=collect(FakeConnection({'GUID_TIMEOUT':3.0}),parameters=('GUID_TIMEOUT',),monotonic=lambda:5.0,**ctx)
    assert out['source_association']=='UNVERIFIED'


def test_transport_failure_is_reported_as_incomplete_capture():
    class Broken(FakeConnection):
        def recv_match(self,**kwargs): raise TimeoutError('socket stalled')
    out=collect(Broken({}),parameters=('GUID_TIMEOUT',),monotonic=lambda:5.0,**context())
    assert out['status']=='INCOMPLETE' and out['reason']=='TRANSPORT_ERROR:TimeoutError'
    assert out['live_read'] is None and out['movement_authorized'] is False



def test_duplicate_mavlink_packet_sequence_invalidates_capture():
    c=FakeConnection({'GUID_TIMEOUT':3.0,'ATC_ACCEL_MAX':1.0})
    original=c.mav.param_request_read_send
    def duplicate(*args):
        original(*args)
        c.queue[-1].sequence=11
    c.mav.param_request_read_send=duplicate
    out=collect(c,parameters=('GUID_TIMEOUT','ATC_ACCEL_MAX'),monotonic=lambda:5.0,**context())
    assert out['status']=='INCOMPLETE'
    assert 'MAVLINK_SEQUENCE_DUPLICATE_OR_NONMONOTONIC' in out['rejection_reasons']



def test_missing_packet_sequence_and_invalid_param_metadata_are_rejected():
    c=FakeConnection({'GUID_TIMEOUT':3.0})
    def no_sequence(*args):
        c.queue.append(Message('PARAM_VALUE',3,1,param_id=b'GUID_TIMEOUT',param_value=3.0,
                               tfg_received_monotonic_s=5.0,param_type=9,param_count=2,param_index=0))
    c.mav.param_request_read_send=no_sequence
    out=collect(c,parameters=('GUID_TIMEOUT',),monotonic=lambda:5.0,**context())
    assert out['status']=='INCOMPLETE' and 'MAVLINK_SEQUENCE_MISSING_OR_INVALID' in out['rejection_reasons']
    c=FakeConnection({'GUID_TIMEOUT':3.0})
    def bad_index(*args):
        c.sequence=11
        c.queue.append(Message('PARAM_VALUE',3,1,param_id=b'GUID_TIMEOUT',param_value=3.0,sequence=11,
                               tfg_received_monotonic_s=5.0,param_type=9,param_count=1,param_index=3))
    c.mav.param_request_read_send=bad_index
    out=collect(c,parameters=('GUID_TIMEOUT',),monotonic=lambda:5.0,**context())
    assert 'PARAMETER_INDEX_METADATA_INVALID' in out['rejection_reasons']
