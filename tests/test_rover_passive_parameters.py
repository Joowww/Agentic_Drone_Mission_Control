"""Fixed read-only parameter route, including the real typed transport over doubles."""
import json
import sys
from types import SimpleNamespace as NS, ModuleType
from unittest.mock import Mock

import pytest

from tools import rover_passive_parameters as p
from tools.rover_control import RoverControlError
from tests.test_rover_first_navigation import BOOT, EXECUTION, LIFECYCLE, evidence


def value(name, **changes):
    v = NS(type=p.TYPES[name], integer_value=3 if name == 'MAV_SYSID' else 1, double_value=1.0)
    vars(v).update(changes)
    return v


def node():
    return NS(get_service_names_and_types=Mock(return_value=[(p.SERVICE, [p.SERVICE_TYPE])]))


def test_all_names_read_with_identity_in_each_batch_and_no_defaults():
    calls = []
    def transport(n, names, timeout):
        calls.append(names)
        return [value(name) for name in names]
    report = p.read_from_node(node(), transport=transport)
    assert calls == list(p.BATCHES) and all(len(names) <= 8 for names in calls)
    assert all(names[:2] == p.IDENTITY for names in calls)
    assert set(report['parameters']) == set(p.TYPES)
    assert report['parameter_writes'] == 0 and report['movement_authorized'] is False
    assert report['server_instance_association'].startswith('UNVERIFIED')
    assert report['atomic_snapshot'] is False
    assert all(row['observed_at_utc'] and row['ros_parameter_type'] in (2, 3) for row in report['parameters'].values())
    json.dumps(report, allow_nan=False)


@pytest.mark.parametrize('changes', [{'type': 0}, {'type': 2}, {'double_value': float('nan')}, {'double_value': True}])
def test_missing_wrong_type_or_nonfinite_value_is_never_defaulted(changes):
    def transport(n, names, timeout):
        return [value(name, **changes) if name == 'GUID_TIMEOUT' else value(name) for name in names]
    with pytest.raises(ValueError):
        p.read_from_node(node(), transport=transport)


@pytest.mark.parametrize('kind', ['absent', 'ambiguous', 'changed', 'truncated', 'wrong_sysid', 'identity_drift'])
def test_discovery_shape_and_repeated_identity_fail_closed(kind):
    n = node()
    calls = 0
    if kind == 'absent': n.get_service_names_and_types.return_value = []
    if kind == 'ambiguous': n.get_service_names_and_types.return_value *= 2
    if kind == 'changed': n.get_service_names_and_types.side_effect = [[(p.SERVICE, [p.SERVICE_TYPE])], []]
    def transport(n, names, timeout):
        nonlocal calls
        calls += 1
        values = [value(name) for name in names]
        if kind == 'truncated': return values[:-1]
        if kind == 'wrong_sysid' or kind == 'identity_drift' and calls > 1: values[0].integer_value = 2
        return values
    with pytest.raises(ValueError): p.read_from_node(n, transport=transport)
    assert calls <= (2 if kind == 'identity_drift' else 1)


def test_transport_timeout_is_not_retried():
    transport = Mock(side_effect=TimeoutError('synthetic timeout'))
    with pytest.raises(TimeoutError): p.read_from_node(node(), transport=transport)
    assert transport.call_count == 1


def test_host_collect_retains_full_session_and_does_not_promote_public_response():
    observed = p.read_from_node(node(), transport=lambda n, names, t: [value(name) for name in names])
    observed['host_boot_id'] = BOOT
    run = Mock(return_value=NS(returncode=0, stdout=json.dumps(observed), stderr=''))
    fence = Mock()
    report = p.collect(EXECUTION['persistent_identity']['container_id'], lifecycle_id=LIFECYCLE,
                       environment_execution=EXECUTION, host_boot_id=BOOT, binding_evidence=evidence(), run=run, fence=fence)
    assert report['scope']['environment_execution'] == EXECUTION
    assert report['scope']['lifecycle_id'] == LIFECYCLE
    assert report['eligible_for_motion_admission'] is False
    assert fence.call_count == 2 and run.call_count == 1
    assert run.call_args.args[0][:2] == ['docker', 'exec']


def test_invalid_binding_stops_before_any_read_process():
    run, fence = Mock(), Mock()
    with pytest.raises(RoverControlError):
        p.collect(EXECUTION['persistent_identity']['container_id'], lifecycle_id=LIFECYCLE,
                  environment_execution=EXECUTION, host_boot_id=BOOT, binding_evidence={}, run=run, fence=fence)
    run.assert_not_called(); fence.assert_not_called()


@pytest.mark.parametrize('timeout', [True, 0, -1, 6, float('nan')])
def test_invalid_deadlines_are_refused(timeout):
    transport = Mock()
    with pytest.raises(ValueError): p.read_from_node(node(), timeout_s=timeout, transport=transport)
    transport.assert_not_called()


@pytest.mark.parametrize('outcome', ['ok', 'timeout', 'spin_error'])
def test_typed_transport_creates_only_get_parameters_and_cancels_in_finally(monkeypatch, outcome):
    future = Mock()
    future.done.return_value = outcome != 'timeout'
    future.result.return_value = NS(values=[value('GUID_TIMEOUT')])
    client = NS(service_is_ready=lambda: True, call_async=Mock(return_value=future))
    n = NS(create_client=Mock(return_value=client), destroy_client=Mock(return_value=True))
    service = type('GetParameters', (), {'Request': type('Request', (), {})})
    srv = ModuleType('rcl_interfaces.srv'); srv.GetParameters = service
    ros = ModuleType('rclpy'); ros.spin_until_future_complete = Mock()
    if outcome == 'spin_error': ros.spin_until_future_complete.side_effect = KeyboardInterrupt()
    monkeypatch.setitem(sys.modules, 'rcl_interfaces.srv', srv)
    monkeypatch.setitem(sys.modules, 'rclpy', ros)
    if outcome == 'ok': assert len(p._read_once(n, ('GUID_TIMEOUT',), 0.1)) == 1
    else:
        with pytest.raises(TimeoutError if outcome == 'timeout' else KeyboardInterrupt):
            p._read_once(n, ('GUID_TIMEOUT',), 0.1)
    assert n.create_client.call_args.args == (service, p.SERVICE)
    assert client.call_async.call_args.args[0].names == ['GUID_TIMEOUT']
    future.cancel.assert_called_once(); n.destroy_client.assert_called_once_with(client)
