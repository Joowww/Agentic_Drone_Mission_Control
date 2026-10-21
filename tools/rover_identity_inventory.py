"""Read-only inventory orchestration; no CLI, ROS import, shell or control API.

Readers supply explicitly sourced observations, not identity accreditation. No
production reader is selected automatically. Receipt time is not generation time.
"""
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import math
import time
from typing import Protocol


@dataclass(frozen=True)
class Reading:
    value: object
    source: str
    observed_at_utc: str


class InventoryReader(Protocol):
    """Future bounded public/file readers; no controls or service-name guessing.

    bridge_configuration returns {path, content: bytes} read from the effective
    configuration, not the repository template. DDS candidates remain candidates.
    get_parameters returns a mapping of requested names to interpreted values;
    absent/unset values must be None. It must enforce the discovered public type.
    """
    def environment(self, *, timeout_s): ...
    def versions(self, *, timeout_s): ...
    def processes(self, *, timeout_s): ...
    def dds_candidates(self, *, timeout_s): ...
    def bridge_configuration(self, *, timeout_s): ...
    def services(self, *, timeout_s): ...
    def get_parameters(self, service, names, *, timeout_s): ...


def collect_inventory(reader: InventoryReader, *, timeout_s=2., monotonic=time.monotonic,
                      utc=lambda: datetime.now(timezone.utc).isoformat()):
    """Return partial evidence even on reader failure. Never changes safety state.

    Each call has a finite budget which the reader must enforce. This synchronous
    orchestrator cannot interrupt a reader that violates its timeout contract.
    No sample-to-publisher/session/model correlation is inferred from this report.
    """
    if type(timeout_s) not in (int, float) or not math.isfinite(timeout_s) or timeout_s <= 0:
        raise ValueError('Finite positive per-read timeout required')
    fields = {}

    def read(name, fn):
        start, received_start = monotonic(), utc()
        field = {'state': 'UNKNOWN', 'value': None, 'source': None,
                 'observed_at_utc': None, 'collection_started_at_utc': received_start,
                 'timeout_s': timeout_s}
        try:
            reading = fn()
            if not isinstance(reading, Reading) or not reading.source or not reading.observed_at_utc:
                raise ValueError('Missing observation provenance/time')
            field.update(source=reading.source, observed_at_utc=reading.observed_at_utc)
            if monotonic() - start > timeout_s:
                raise TimeoutError('Reader exceeded wall budget; observation not accepted')
            if reading.value is None:
                field['reason'] = 'Data unavailable or not attributable'
            else:
                field.update(state='OBSERVED', value=reading.value)
        except Exception as exc:
            field['reason'] = f'{type(exc).__name__}: {exc}'
        field.update(received_at_utc=utc(), received_monotonic_s=monotonic(),
                     duration_wall_s=monotonic()-start)
        fields[name] = field
        return field

    for name in ('environment', 'versions', 'processes', 'dds_candidates', 'bridge_configuration', 'services'):
        field = read(name, lambda name=name: getattr(reader, name)(timeout_s=timeout_s))
        if name == 'bridge_configuration' and field['state'] == 'OBSERVED':
            try:
                value = field['value']
                if not isinstance(value['path'], str) or not value['path'].startswith('/') or not isinstance(value['content'], bytes):
                    raise ValueError('Effective absolute path and exact bytes required')
                field['value'] = {'path': value['path'], 'sha256': hashlib.sha256(value['content']).hexdigest(),
                                  'size_bytes': len(value['content'])}
            except (KeyError, TypeError, ValueError) as exc:
                field.update(state='UNKNOWN', value=None, reason=str(exc))

    # Select only a unique publicly discovered GetParameters service in v3.
    discovery = fields['services']
    candidates = []
    if discovery['state'] == 'OBSERVED' and isinstance(discovery['value'], list):
        candidates = [entry['name'] for entry in discovery['value']
                      if isinstance(entry, dict) and isinstance(entry.get('name'), str)
                      and entry['name'].startswith('/ap/v3/')
                      and entry.get('types') == ['rcl_interfaces/srv/GetParameters']]
    if len(candidates) == 1:
        read('parameters', lambda: reader.get_parameters(
            candidates[0], ('SYSID_THISMAV', 'DDS_USE_NS'), timeout_s=timeout_s))
    else:
        read('parameters', lambda: Reading(None, 'public service discovery', utc()))
        fields['parameters']['reason'] = 'Unique compatible v3 GetParameters service not discovered'
    parameters = fields['parameters']
    if parameters['state'] == 'OBSERVED':
        if not isinstance(parameters['value'], dict):
            parameters.update(state='UNKNOWN', value=None, reason='Uninterpretable public parameter response')
        else:
            parameters['value'] = {
                name: {'state': 'OBSERVED' if parameters['value'].get(name) is not None else 'UNKNOWN',
                       'value': parameters['value'].get(name), 'source': parameters['source'],
                       'observed_at_utc': parameters['observed_at_utc']}
                for name in ('SYSID_THISMAV', 'DDS_USE_NS')}
    return {'schema_version': 1, 'status': 'BLOCKED', 'vehicle_id': 'rover_01',
            'expected_interface': 'v3', 'movement_authorized': False,
            'sample_publisher_gid': None, 'source_association_verified': False,
            'fields': fields, 'limitations': [
                'Reader provenance is reported, not authenticated; observations may be historical.',
                'DDS graph candidates do not attribute any individual sample.',
                'Receipt time does not establish generation time or clock comparability.',
                'XRCE/SYSID/SITL v3 and effective bridge/model correlation remain unverified.']}


class RosGraphInventoryReader:
    """Read through an already-owned public rclpy Node; never creates/spins one.

    Reuses the same public discovery APIs as PassiveObserver/NativeRos2Session.
    No reference to their control clients/publishers, handles or private APIs.
    This graph view cannot establish the node's container/process environment.
    """
    def __init__(self, node, *, utc=lambda: datetime.now(timezone.utc).isoformat()):
        self.node, self.utc = node, utc

    def _unknown(self, field):
        return Reading(None, f'{field}: unavailable through public ROS graph reader', self.utc())

    def environment(self, *, timeout_s):
        return self._unknown('environment')

    def versions(self, *, timeout_s):
        return self._unknown('ROS/RMW versions')

    def processes(self, *, timeout_s):
        return self._unknown('process identities and arguments')

    def bridge_configuration(self, *, timeout_s):
        return self._unknown('effective bridge file/path/content')

    def dds_candidates(self, *, timeout_s):
        # Endpoint discovery is evidence about the graph, NOT message metadata.
        result = []
        for topic in ('/ap/v3/status', '/rover1/odometry'):
            observed = self.node.get_publishers_info_by_topic(topic)
            result.append({'topic': topic, 'source': f'Node.get_publishers_info_by_topic({topic})',
                           'observed_at_utc': self.utc(),
                           'candidates': [{'gid': bytes(info.endpoint_gid).hex(),
                                           'node_name': info.node_name,
                                           'node_namespace': info.node_namespace,
                                           'topic_type': info.topic_type}
                                          for info in observed]})
        return Reading(result, 'public rclpy Node publisher discovery', self.utc())

    def services(self, *, timeout_s):
        observed = self.node.get_service_names_and_types()
        return Reading([{'name': name, 'types': list(types)} for name, types in observed],
                       'Node.get_service_names_and_types()', self.utc())

    def get_parameters(self, service, names, *, timeout_s):
        # No existing read-only parameter client in this route. Discovery alone
        # does not justify using NativeRos2Session's control client or guessing.
        return self._unknown(f'public GetParameters response for {service}')


def collect_node_inventory(node, *, timeout_s=2.):
    """Explicit in-process connection; caller owns node/context/authorization.

    Does not initialize ROS, add a CLI/MCP route, spin, call services or persist.
    """
    return collect_inventory(RosGraphInventoryReader(node), timeout_s=timeout_s)
