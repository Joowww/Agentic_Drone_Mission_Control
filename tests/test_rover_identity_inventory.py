"""Inventory doubles only: no ROS, Docker, files or operational entry point."""
import hashlib
from unittest.mock import Mock

import pytest

from tools.rover_identity_inventory import Reading, collect_inventory


def reader():
    r = Mock()
    for name in ('environment', 'versions', 'processes', 'dds_candidates', 'services'):
        getattr(r, name).return_value = Reading([], 'synthetic/' + name, '2026-10-21T10:00:00Z')
    r.bridge_configuration.return_value = Reading(
        {'path': '/tmp/effective.yaml', 'content': b'bridge: rover1\n'}, 'synthetic active bridge', '2026-10-21T10:00:00Z')
    r.services.return_value = Reading([{'name': '/ap/v3/get_parameters',
        'types': ['rcl_interfaces/srv/GetParameters']}], 'synthetic discovery', '2026-10-21T10:00:00Z')
    r.get_parameters.return_value = Reading({'SYSID_THISMAV': 3, 'DDS_USE_NS': None},
        'synthetic public GetParameters response', '2026-10-21T10:00:00Z')
    return r


def test_partial_inventory_never_accredits_graph_or_enables_motion():
    r = reader()
    result = collect_inventory(r)
    assert result['status'] == 'BLOCKED'
    assert not result['movement_authorized'] and not result['source_association_verified']
    assert result['sample_publisher_gid'] is None
    assert result['fields']['bridge_configuration']['value'] == {
        'path': '/tmp/effective.yaml', 'sha256': hashlib.sha256(b'bridge: rover1\n').hexdigest(), 'size_bytes': 15}
    assert result['fields']['parameters']['value']['DDS_USE_NS']['state'] == 'UNKNOWN'
    for field in result['fields'].values():
        assert field['source'] and field['observed_at_utc'] and field['received_at_utc']
    r.get_parameters.assert_called_once_with('/ap/v3/get_parameters', ('SYSID_THISMAV', 'DDS_USE_NS'), timeout_s=2.)


@pytest.mark.parametrize('services', [[], [dict(name='/ap/v2/get_parameters', types=['rcl_interfaces/srv/GetParameters'])],
    [dict(name='/ap/v3/set_parameters', types=['rcl_interfaces/srv/SetParameters'])],
    [dict(name='/ap/v3/a', types=['rcl_interfaces/srv/GetParameters']),
     dict(name='/ap/v3/b', types=['rcl_interfaces/srv/GetParameters'])]])
def test_no_parameter_call_without_unique_public_discovery(services):
    r = reader()
    r.services.return_value = Reading(services, 'graph double', 'time double')
    assert collect_inventory(r)['fields']['parameters']['state'] == 'UNKNOWN'
    r.get_parameters.assert_not_called()


def test_failures_preserve_other_fields_and_do_not_retry():
    r = reader()
    r.processes.side_effect = TimeoutError('synthetic timeout')
    r.versions.return_value = Reading({'rclpy': 'unknown'}, '', '')
    r.bridge_configuration.return_value = Reading({'path': 'template', 'content': b'x'}, 'double', 'time')
    fields = collect_inventory(r)['fields']
    assert fields['processes']['state'] == fields['versions']['state'] == fields['bridge_configuration']['state'] == 'UNKNOWN'
    assert fields['environment']['state'] == 'OBSERVED'
    r.processes.assert_called_once_with(timeout_s=2.)


def test_late_reader_not_accepted():
    r = reader()
    ticks = iter(range(100))
    fields = collect_inventory(r, timeout_s=.1, monotonic=lambda: next(ticks))['fields']
    assert all(field['state'] == 'UNKNOWN' for field in fields.values())
    r.get_parameters.assert_not_called()


@pytest.mark.parametrize('budget', [0, -1, float('inf'), float('nan'), True])
def test_invalid_budget_never_calls_reader(budget):
    r = reader()
    with pytest.raises(ValueError):
        collect_inventory(r, timeout_s=budget)
    assert not r.mock_calls


def test_public_node_reader_connects_discovery_only():
    from types import SimpleNamespace
    from tools.rover_identity_inventory import collect_node_inventory
    calls = []

    def publishers(topic):
        calls.append(('publishers', topic))
        return [SimpleNamespace(endpoint_gid=b'offline-gid', node_name='bridge',
                                node_namespace='/rover1', topic_type='synthetic/Type')]

    def services():
        calls.append(('services',))
        return [('/ap/v3/get_parameters', ['rcl_interfaces/srv/GetParameters'])]

    # No clients, publishers, handle, spin or process/file APIs on this double.
    node = SimpleNamespace(get_publishers_info_by_topic=publishers,
                           get_service_names_and_types=services)
    report = collect_node_inventory(node)
    assert calls == [('publishers', '/ap/v3/status'), ('publishers', '/rover1/odometry'), ('services',)]
    assert report['status'] == 'BLOCKED' and report['sample_publisher_gid'] is None
    assert not report['movement_authorized'] and not report['source_association_verified']
    fields = report['fields']
    for name in ('environment', 'versions', 'processes', 'bridge_configuration', 'parameters'):
        assert fields[name]['state'] == 'UNKNOWN' and fields[name]['value'] is None
        assert fields[name]['source'] and fields[name]['observed_at_utc']
    for stream in fields['dds_candidates']['value']:
        assert stream['source'] and stream['observed_at_utc']
        assert stream['candidates'][0]['gid'] == b'offline-gid'.hex()
    assert fields['services']['state'] == 'OBSERVED'


def test_graph_reader_failure_is_unknown_without_losing_service_discovery():
    from types import SimpleNamespace
    from tools.rover_identity_inventory import collect_node_inventory
    node = SimpleNamespace(get_publishers_info_by_topic=Mock(side_effect=RuntimeError('graph unavailable')),
                           get_service_names_and_types=lambda: [])
    report = collect_node_inventory(node)
    assert report['fields']['dds_candidates']['state'] == 'UNKNOWN'
    assert 'graph unavailable' in report['fields']['dds_candidates']['reason']
    assert report['fields']['services']['state'] == 'OBSERVED'
    assert report['status'] == 'BLOCKED'
    node.get_publishers_info_by_topic.assert_called_once_with('/ap/v3/status')
