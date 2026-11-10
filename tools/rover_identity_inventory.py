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
            candidates[0], ('MAV_SYSID', 'DDS_USE_NS'), timeout_s=timeout_s))
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
                for name in ('MAV_SYSID', 'DDS_USE_NS')}
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
    def __init__(self, node, *, utc=lambda: datetime.now(timezone.utc).isoformat(), parameter_transport=None):
        self.node, self.utc = node, utc
        self.parameter_transport = parameter_transport

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
        # Opt-in: the default graph-only reader still creates no clients/spins.
        if self.parameter_transport is None:
            return self._unknown(f'public GetParameters response for {service}')
        candidates = [(n, list(t)) for n,t in self.node.get_service_names_and_types()
                      if n.startswith('/ap/v3/') and list(t)==['rcl_interfaces/srv/GetParameters']]
        if candidates != [(service,['rcl_interfaces/srv/GetParameters'])]:
            raise ValueError('Missing/ambiguous discovered v3 GetParameters service')
        if tuple(names) != ('MAV_SYSID','DDS_USE_NS'):
            raise ValueError('Only the explicit read-only identity parameter set is supported')
        value = self.parameter_transport(service, tuple(names), timeout_s=timeout_s)
        if candidates != [(n,list(t)) for n,t in self.node.get_service_names_and_types()
                          if n.startswith('/ap/v3/') and list(t)==['rcl_interfaces/srv/GetParameters']]:
            raise ValueError('Parameter service discovery changed during query')
        return Reading(value, 'public GetParameters response; server-instance association UNVERIFIED', self.utc())


def read_identity_parameters(node, service, names, *, timeout_s):
    """Prepared public ROS read, never invoked by graph inventory by default.

    Caller must authorize the future query and own node/context. A public rclpy
    future does not expose the server GID; a value is NOT an instance binding.
    AP_DDS_Client GET_PARAMETERS reads AP_Param::find, never calls set().
    """
    if tuple(names)!=('MAV_SYSID','DDS_USE_NS') or not service.startswith('/ap/v3/'):
        raise ValueError('Unsupported identity parameter read scope')
    def interpret(values):
        result={}
        for name,value in zip(names,values):
            # Public ParameterType INTEGER=2; NOT_SET=0 is explicit absence.
            if value.type==0:result[name]=None
            elif value.type==2 and type(value.integer_value) is int:result[name]=value.integer_value
            else:raise ValueError('Identity parameter is not an integer or NOT_SET')
        if result['MAV_SYSID'] is not None and not 1<=result['MAV_SYSID']<=255:raise ValueError('Invalid SYSID response')
        if result['DDS_USE_NS'] not in (None,0,1):raise ValueError('Invalid DDS_USE_NS response')
        return result
    return _read_parameters_once(node,service,names,timeout_s,interpret)


def _read_parameters_once(node,service,names,timeout_s,interpret):
    """Shared typed transport, private to the two strict read-only scopes."""
    from tools.rover_control import number, synchronous_deadline
    timeout_s=number(timeout_s,'parameter timeout',positive=True)
    from rcl_interfaces.srv import GetParameters
    import rclpy
    client=None;future=None
    try:
        with synchronous_deadline(timeout_s):
            client=node.create_client(GetParameters,service)
            if not client.service_is_ready():raise LookupError('GetParameters service unavailable')
            request=GetParameters.Request();request.names=list(names)
            future=client.call_async(request)  # one request, no retry
            rclpy.spin_until_future_complete(node,future,timeout_sec=timeout_s)
            if not future.done():raise TimeoutError('GetParameters response absent')
            response=future.result()
            if response is None or len(response.values)!=len(names):raise ValueError('Parameter response shape')
            return interpret(response.values)
    finally:
        if future is not None and not future.done():future.cancel()
        if client is not None and node.destroy_client(client) is False:
            raise RuntimeError('Parameter client destruction not confirmed')


def read_rover_model_description(node, *, timeout_s):
    """Prepared runtime robot_description read, NOT a model/endpoint binding.

    robot.launch.py spawns from this topic, not directly from the installed SDF.
    Public discovery must name this exact read-only service; no controls/CLI.
    Capturing the parameter later does not prove which bytes a past spawn used.
    """
    import xml.etree.ElementTree as ET
    from tools.rover_xrce_trace.budget import SOCKET
    from tools.rover_control import synchronous_deadline,number
    timeout_s=number(timeout_s,'description timeout',positive=True)
    service='/rover1/robot_state_publisher/get_parameters'
    def discovered():
        return [(n,list(t)) for n,t in node.get_service_names_and_types() if n==service]
    def interpret(values):
        value=values[0]
        if value.type!=4 or not isinstance(value.string_value,str):raise ValueError('robot_description is not a string')
        data=value.string_value.encode('utf-8')
        if not data or len(data)>SOCKET.row_bytes:raise ValueError('robot_description missing/over existing row budget')
        root=ET.fromstring(data)
        if root.tag!='sdf':raise ValueError('Expected SDF robot_description from this launch')
        return {'content':value.string_value,'sha256':hashlib.sha256(data).hexdigest(),
                'size_bytes':len(data),'runtime_instantiation_verified':False}
    with synchronous_deadline(timeout_s):
        if discovered()!=[(service,['rcl_interfaces/srv/GetParameters'])]:
            raise ValueError('Compatible rover robot_description parameter service not discovered')
        result=_read_parameters_once(node,service,('robot_description',),timeout_s,interpret)
        if discovered()!=[(service,['rcl_interfaces/srv/GetParameters'])]:raise ValueError('Description service changed during read')
    return Reading(result,'public robot_description GetParameters response; server/entity association UNVERIFIED',
                   datetime.now(timezone.utc).isoformat())


def collect_node_inventory(node, *, timeout_s=2.):
    """Explicit in-process connection; caller owns node/context/authorization.

    Does not initialize ROS, add a CLI/MCP route, spin, call services or persist.
    """
    return collect_inventory(RosGraphInventoryReader(node), timeout_s=timeout_s)


def verify_bridge_observations(evidence):
    """Offline configuration joins, not a graph->PID or model accreditation.

    Input readings carry the same explicit session/environment context, source
    and receipt. Effective YAML must be selected by the observed process argv;
    templates and files from another run are rejected, never auto-rendered.
    """
    import xml.etree.ElementTree as ET
    import yaml
    report={'status':'BLOCKED','source_association_verified':False,'movement_authorized':False,
            'sample_endpoint':'UNKNOWN','configuration_chain':'UNKNOWN',
            'publisher_process_link':'UNKNOWN_NO_PUBLIC_GRAPH_PID',
            'runtime_model_link':'UNKNOWN_CONFIG_IS_NOT_RUNTIME_MODEL_IDENTITY','reasons':[],'sources':{}}
    try:
        context=evidence['context']
        if not context.get('session_id') or not context.get('environment'):raise ValueError('Missing session context')
        def read(name):
            r=evidence[name]
            if r['context']!=context or not r['source'] or not r['observed_at_utc']:
                raise ValueError('Mixed session or missing provenance: '+name)
            # Require explicit timezone, not just an arbitrary nonempty string.
            if datetime.fromisoformat(r['observed_at_utc'].replace('Z','+00:00')).tzinfo is None:
                raise ValueError('Unknown observation timezone')
            report['sources'][name]={'source':r['source'],'observed_at_utc':r['observed_at_utc']}
            return r['value']
        sample=read('sample');candidates=read('publishers')
        if sample['topic']!='/rover1/odometry' or not sample.get('message_publisher_gid'):
            raise ValueError('Missing per-message odometry GID')
        gid=sample['message_publisher_gid']
        if len(gid)!=48 or not int(gid,16):raise ValueError('Invalid/zero per-message GID')
        matches=[c for c in candidates if c['endpoint_gid']==gid and c['topic_type']=='nav_msgs/msg/Odometry']
        if len(matches)!=1:raise ValueError('Sample endpoint absent or contradictory in discovery')
        report['sample_endpoint']='MESSAGE_GID_MATCHED_DISCOVERY_ENDPOINT_NOT_PROCESS_ID'
        before=read('process_before');after=read('process_after')
        if before!=after or any(k not in before for k in ('pid','start_ticks','boot_id','argv','executable')):
            raise ValueError('Bridge process changed or incomplete')
        if before['executable'].rsplit('/',1)[-1]!='parameter_bridge':raise ValueError('Wrong bridge executable')
        argv=before['argv']
        if argv.count('__ns:=/rover1')!=1:raise ValueError('Bridge namespace ambiguous')
        selected=read('parameters_file');config=read('bridge_configuration')
        # ros2 launch passes the YAML selector in an explicitly observed params file.
        if _ArchivedCapture._argument(argv,'--params-file')!=selected['path']:
            raise ValueError('Effective params file not selected uniquely by argv')
        # Reuse the existing evidence loader, which rejects duplicate keys.
        # Inspect parsed values: a comment mentioning {{ robot_name }} is inert.
        params=_ArchivedCapture._yaml(selected['content'])
        routes=_ArchivedCapture._yaml(config['content'])
        def pending(value):
            if isinstance(value,str):return '{{' in value or '}}' in value
            if isinstance(value,dict):return any(pending(k) or pending(v) for k,v in value.items())
            if isinstance(value,list):return any(pending(v) for v in value)
            return False
        if pending(params) or pending(routes):raise ValueError('Unrendered template is not effective configuration')
        selectors=[]
        for node,p in params.items():
            if isinstance(p,dict) and isinstance(p.get('ros__parameters'),dict):
                if 'config_file' in p['ros__parameters']:selectors.append(p['ros__parameters']['config_file'])
        if selectors!=[config['path']]:raise ValueError('Bridge config selector contradiction')
        route=[p for p in routes if p.get('ros_topic_name') in ('odometry','/rover1/odometry')]
        if len(route)!=1 or any(route[0].get(k)!=v for k,v in {
                'gz_topic_name':'/model/rover1/odometry','ros_type_name':'nav_msgs/msg/Odometry',
                'gz_type_name':'gz.msgs.Odometry','direction':'GZ_TO_ROS'}.items()):
            raise ValueError('Odometry bridge route/type/direction contradiction')
        model=read('model_sdf');tree=ET.fromstring(model['content'])
        plugins=[p for p in tree.iter('plugin') if p.get('name')=='gz::sim::systems::OdometryPublisher']
        if len(plugins)!=1:raise ValueError('Model odometry plugin absent or ambiguous')
        plugin=plugins[0]
        if plugin.findtext('odom_frame')!='odom' or plugin.findtext('robot_base_frame')!='base_link':
            raise ValueError('Model frame contract contradiction')
        if sample['frame_id']!='odom' or sample['child_frame_id']!='base_link':raise ValueError('Sample frame contradiction')
        report.update(configuration_chain='OBSERVED_FILE_SELECTION_AND_ROUTE_ONLY',
            bridge_config_sha256=hashlib.sha256(config['content'].encode()).hexdigest(),
            model_sdf_sha256=hashlib.sha256(model['content'].encode()).hexdigest(),
            configured_dimensions=plugin.findtext('dimensions'),
            reasons=['MessageInfo binds the sample to an endpoint; discovery does not bind it to a PID.',
                     'Selected file bytes and a plugin declaration do not identify the running Gazebo entity.',
                     'Pose origin, plugin twist coordinates and goal transformation still require source/runtime evidence.'])
    except (KeyError,TypeError,ValueError,AttributeError,ET.ParseError,yaml.YAMLError) as exc:
        report['reasons'].append(str(exc))
    return report


class CaptureEvidenceError(ValueError):
    """Offline evidence is inconsistent; never a request to repair runtime state."""


class _ArchivedCapture:
    """Verified historical files, not a live ROS reader or a trusted signature."""
    def __init__(self, root, expected_run_id=None):
        import json
        from pathlib import Path
        from uuid import UUID
        self.root = Path(root).resolve()
        self.run_id = expected_run_id or self.root.name
        if str(UUID(self.run_id)) != self.run_id:
            raise CaptureEvidenceError('Expected canonical capture UUID')
        manifest = self.root / 'manifest.json'
        self.entries, self.snapshot_bytes = {}, {}
        manifest_bytes = manifest.read_bytes()
        self.manifest_sha256 = hashlib.sha256(manifest_bytes).hexdigest()
        for entry in json.loads(manifest_bytes)['files']:
            name = entry['path']
            p = self.root / name
            if (Path(name).is_absolute() or '..' in Path(name).parts or name in self.entries
                    or p.is_symlink() or not p.resolve().is_relative_to(self.root)):
                raise CaptureEvidenceError('Unsafe or duplicate manifest path')
            data = p.read_bytes()
            if len(data) != entry['size_bytes'] or hashlib.sha256(data).hexdigest() != entry['sha256']:
                raise CaptureEvidenceError('Manifest integrity mismatch: ' + name)
            self.entries[name] = entry
            self.snapshot_bytes[name] = data
        self.execution = self.json('capture/execution.json')
        self.result = self.json('collector_result.json')
        self.context = self.execution['context']
        start = self.json('lifecycle_start_result.json')
        if (not start.get('success') or start['operation']['action'] != 'start'
                or start['operation']['owner_id'] != self.context['lifecycle_id']
                or self.result['execution'] != self.execution
                or not self.result['directory'].endswith('_' + self.run_id)
                or self.execution['command'][2] != self.result['directory'] + '/journal.jsonl'):
            raise CaptureEvidenceError('Capture/start/execution session mismatch')
        if self.json('lifecycle_start/operation.json') != start['operation']:
            raise CaptureEvidenceError('Archived start operation contradiction')
        self.effective = self.json('effective_readonly_report.json')
        if self.json('effective_readonly.stdout') != self.effective:
            raise CaptureEvidenceError('Effective observation differs from original output')
        if (self.context['profile'] != 'two_drones_rover' or self.context['interface'] != 'v3'
                or self.context['vehicle_id'] != 'rover_01' or self.context['namespace'] != '/rover1'):
            raise CaptureEvidenceError('Wrong rover/interface/profile context')
        for name in ('environment_before.json', 'environment_before_capture.json'):
            actual = self.json(name)
            if any(actual.get(k) != v for k, v in self.context['environment'].items()):
                raise CaptureEvidenceError('Environment/context identity mismatch')
        self.copies = self.json('effective_copies.json')
        worker_context = self.original_json('passive_worker_context.json')
        worker_record = self.original_json('passive_worker_worker.json')
        from tools.rover_environment_identity import digest
        if worker_context != self.context or worker_record['context_sha256'] != digest(self.context):
            raise CaptureEvidenceError('Passive worker belongs to another session')
        self.worker_record = worker_record
        snapshot = self.json('container_processes_before_close.stdout')
        self.snapshot = {p['pid']: p for p in snapshot['relevant']}
        for identity in (self.context['launch_process'], worker_record['worker']):
            p = self.snapshot.get(identity['pid'])
            if (p is None or p['start_ticks'] != identity['start_ticks']
                    or snapshot['boot_id'] != identity['boot_id']):
                raise CaptureEvidenceError('Launch/worker process identity mismatch or PID recycled')
        for p in self.effective['processes']:
            original = self.snapshot.get(p['pid'])
            if original is None or original['start_ticks'] != p['start_ticks'] or original['argv'] != p['argv']:
                raise CaptureEvidenceError('Process snapshot contradiction')
        for entry in self.result['files']:
            name = 'capture/' + entry['path']
            data = self.bytes(name)
            if len(data) != entry['size'] or hashlib.sha256(data).hexdigest() != entry['sha256']:
                raise CaptureEvidenceError('Original capture file hash mismatch')
        self.binary = self.json('binary.json')  # actual build, never the later cap-only build
        if self.execution['command'][0] != self.binary['binary']:
            raise CaptureEvidenceError('Executed binary differs from selected build')
        for name in ('binary_before.stdout', 'binary_after.stdout'):
            if self.json(name)['sha256'] != self.binary['sha256']:
                raise CaptureEvidenceError('Executed binary hash contradiction')
        installed = [v for v in self.effective['files'].values()
                     if v.get('path', '').endswith('/launch/tfg_demo.launch.py')]
        if len(installed) != 1 or installed[0]['sha256'] != self.context['launch_sha256']:
            raise CaptureEvidenceError('Installed/protected launch hash mismatch')
        self.launch = installed[0]
        self._original_bytes(self.launch)
        self.bridge = self._one_process(lambda p: '__ns:=/rover1' in p['argv']
                                        and p['argv'][0].endswith('/parameter_bridge'))
        self.rover = self._one_process(lambda p: p['argv'][0] == 'ardurover')
        self.agent = self._one_process(lambda p: p['argv'][0].endswith('/micro_ros_agent'))
        params = self._argument(self.bridge['argv'], '--params-file')
        parsed = self._yaml(self.original_path(params)['text'])
        try:
            config_path = parsed['/**']['ros__parameters']['config_file']
        except (KeyError, TypeError) as exc:
            raise CaptureEvidenceError('Missing unique bridge config_file') from exc
        self.bridge_config = self.original_path(config_path)
        self.bridge_config_source = config_path
        config = self._yaml(self.bridge_config['text'])
        matches = [v for v in config if isinstance(v, dict) and v.get('ros_topic_name') == 'odometry']
        if len(matches) != 1 or any(matches[0].get(k) != v for k, v in {
                'gz_topic_name': '/model/rover1/odometry', 'ros_type_name': 'nav_msgs/msg/Odometry',
                'gz_type_name': 'gz.msgs.Odometry', 'direction': 'GZ_TO_ROS'}.items()):
            raise CaptureEvidenceError('Bridge odometry type/model/direction contradiction')
        self.odometry_mapping = matches[0]
        if self._argument(self.rover['argv'], '--instance') != '2' or self._argument(self.rover['argv'], '--sysid') != '3':
            raise CaptureEvidenceError('SITL instance/SYSID contradict expected rover topology')

    def bytes(self, name):
        if name not in self.entries:
            raise CaptureEvidenceError('Required file absent from manifest: ' + name)
        return self.snapshot_bytes[name]

    def json(self, name):
        import json
        return json.loads(self.bytes(name))

    def ref(self, name, selector=None):
        if name not in self.entries:
            raise CaptureEvidenceError('Unmanifested reference')
        return {'path': str(self.root / name), 'sha256': self.entries[name]['sha256'],
                'selector': selector}

    def original_json(self, label):
        import json
        f = self.effective['files'][label]
        self._original_bytes(f)
        return json.loads(f['text'])

    def original_path(self, path):
        matches = [f for f in self.effective['files'].values() if f.get('path') == path and 'text' in f]
        if len(matches) != 1:
            raise CaptureEvidenceError('Missing/ambiguous observed file: ' + str(path))
        self._original_bytes(matches[0])
        return matches[0]

    def _original_bytes(self, f):
        if f.get('truncated') or hashlib.sha256(f['text'].encode()).hexdigest() != f['sha256']:
            raise CaptureEvidenceError('Observed original file incomplete or changed')
        copies = [c for c in self.copies if c['source'] == f['path'] and c['sha256'] == f['sha256']]
        if len(copies) != 1 or self.bytes(copies[0]['copy']) != f['text'].encode():
            raise CaptureEvidenceError('Observed file copy contradiction')

    def file_ref(self, f):
        copy = next(c for c in self.copies if c['source'] == f['path'] and c['sha256'] == f['sha256'])
        return {**self.ref(copy['copy']), 'observed_source_path': f['path'], 'observed_source_sha256': f['sha256']}

    def _one_process(self, predicate):
        values = [p for p in self.effective['processes'] if predicate(p)]
        if len(values) != 1:
            raise CaptureEvidenceError('Missing or ambiguous process role')
        return values[0]

    @staticmethod
    def _argument(argv, option):
        positions = [i for i, a in enumerate(argv) if a == option]
        if len(positions) != 1 or positions[0] + 1 >= len(argv):
            raise CaptureEvidenceError('Missing/ambiguous process argument: ' + option)
        return argv[positions[0] + 1]

    @staticmethod
    def _yaml(text):
        # Optional existing parser only, no installation or new ROS dependency.
        try:
            import yaml
        except ImportError as exc:
            raise CaptureEvidenceError('Existing safe YAML parser unavailable; no association inferred') from exc
        class UniqueLoader(yaml.SafeLoader):
            pass
        def mapping(loader, node):
            result = {}
            for k, v in node.value:
                key = loader.construct_object(k)
                if key in result:
                    raise CaptureEvidenceError('Duplicate YAML key')
                result[key] = loader.construct_object(v)
            return result
        UniqueLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, mapping)
        return yaml.load(text, Loader=UniqueLoader)


class ArchivedInventoryReader:
    """Replay validated historical evidence through the existing inventory protocol.

    No shell, Docker, ROS, service clients or current-state claims. Replay receipt
    timestamps belong to this analysis; observed_at is the original observation.
    """
    def __init__(self, archive):
        self.archive = archive
        self.observed = archive.effective['observed_at_utc']

    def environment(self, *, timeout_s):
        return Reading(self.archive.context['environment'], 'protected archived lifecycle context',
                       self.archive.execution['started_at_utc'])

    def versions(self, *, timeout_s):
        return Reading(None, 'Exact running ROS/RMW versions not recorded by this snapshot', self.observed)

    def processes(self, *, timeout_s):
        return Reading(self.archive.effective['processes'], 'archived /proc argv/start ticks/exe hashes', self.observed)

    def dds_candidates(self, *, timeout_s):
        return Reading(self.archive.analysis['discoveries_separate'], 'archived public TopicEndpointInfo',
                       self.archive.execution['finished_at_utc'])

    def bridge_configuration(self, *, timeout_s):
        f = self.archive.bridge_config
        return Reading({'path': f['path'], 'content': f['text'].encode()},
                       'archived bridge argv -> params file -> config_file exact copy', self.observed)

    def services(self, *, timeout_s):
        return Reading(None, 'No public parameter-service discovery retained; no replay call', self.observed)

    def get_parameters(self, service, names, *, timeout_s):
        return Reading(None, 'No parameter response recorded; no service call', self.observed)


def correlate_capture(evidence_root, *, expected_run_id=None):
    """Offline partial source-chain matrix, reusing inventory and journal analysis.

    Hashes establish internal file consistency, not authenticated authorship.
    Failure blocks all positive chain assertions; nothing repairs originals or
    authorizes movement, and missing XRCE links are never inferred from numbers.
    """
    import re
    result = {'schema': 'tfg.rover.archived-correlation/1', 'status': 'BLOCKED',
              'source_association_verified': False, 'movement_authorized': False,
              'cryptographic_authentication': 'NOT_ESTABLISHED_NOT_AN_ADDED_GATE_REQUIREMENT',
              'evidence_valid': False, 'errors': [], 'matrix': [], 'historical_only': True}
    try:
        from tools.rover_passive_journal import analyze_bytes
        archive = _ArchivedCapture(evidence_root, expected_run_id)
        result.update(run_id=archive.run_id, lifecycle_id=archive.context['lifecycle_id'],
                      manifest_sha256=archive.manifest_sha256, verified_manifest_entries=len(archive.entries),
                      executed_binary={'path': archive.binary['binary'], 'sha256': archive.binary['sha256'],
                                       'executed_in_capture': True},
                      later_unexecuted_binary=archive.json('post_trial_cap_build/binary.json'))
        archive.analysis = analyze_bytes(archive.bytes('capture/journal.jsonl'),
                                        receipt=archive.json('capture/receipt.json'),
                                        returncode=archive.execution['return_code'])
        if archive.analysis['completion'] != 'DATA_RECORDED' or archive.analysis['issues']:
            raise CaptureEvidenceError('Journal/receipt is not a coherent two-stream capture')
        import json
        raw_samples = [json.loads(line) for line in archive.bytes('capture/journal.jsonl').splitlines()
                       if json.loads(line).get('event') == 'sample']
        if any(v['child_frame_id'] != 'base_link' for v in raw_samples if v['topic'] == '/rover1/odometry'):
            raise CaptureEvidenceError('Odometry frame contradicts existing identity contract')
        result['inventory_replay'] = collect_inventory(ArchivedInventoryReader(archive))
        matrix = result['matrix']
        samples = archive.analysis['topics']
        endpoint_facts = []
        for topic, stream in samples.items():
            gids = {(s['message_publisher_gid'], s['rmw_implementation_identifier']) for s in stream['samples']}
            if len(gids) != 1:
                raise CaptureEvidenceError('Publisher changed/ambiguous within capture: ' + topic)
            gid, rmw = next(iter(gids))
            for s in stream['samples']:
                candidates = s['graph_candidates_separate']['candidates']
                if (len(candidates) != 1 or candidates[0]['endpoint_gid'] != gid
                        or candidates[0].get('topic_type') != {'/ap/v3/status': 'ardupilot_msgs/msg/Status',
                                                              '/rover1/odometry': 'nav_msgs/msg/Odometry'}[topic]):
                    raise CaptureEvidenceError('Unique publisher contract/MessageInfo graph contradiction')
            endpoint_facts.append({'topic': topic, 'gid': gid, 'rmw_identifier': rmw,
                                   'candidate': stream['samples'][0]['graph_candidates_separate']['candidates'][0]})
        matrix.append({'link': 'MessageInfo/GID -> DDS publisher endpoint', 'state': 'HISTORICALLY_CORRELATED',
                       'supports': endpoint_facts,
                       'unknown': ['Advertised node name is not an OS process identity or cryptographic authentication.'],
                       'evidence': [archive.ref('capture/journal.jsonl', 'sample.MessageInfo and separate graph candidates')]})
        log = archive.effective['files']['tfg_demo.log']
        archive._original_bytes(log)
        clean = re.sub(r'\x1b\[[0-9;]*m', '', log['text'])
        startup = re.findall(r'^\[INFO\] \[(.+)\]: process started with pid \[(\d+)\]', clean, re.M)
        def role_for(pid):
            matches = [role for role, observed_pid in startup if int(observed_pid) == pid]
            if len(matches) != 1:
                raise CaptureEvidenceError('Launch-log/process PID relationship ambiguous')
            return matches[0]
        agent_role, rover_role = role_for(archive.agent['pid']), role_for(archive.rover['pid'])
        settings = [line for line in clean.splitlines() if line.startswith('[' + rover_role + ']')
                    and 'Setting MAV_SYSID=' in line]
        if {re.search(r'MAV_SYSID=(\d+)', line).group(1) for line in settings} != {'3'}:
            raise CaptureEvidenceError('SITL SYSID setting contradicts process argument')
        client_events = []
        for number, line in enumerate(clean.splitlines(), 1):
            if not line.startswith('[' + agent_role + ']'):
                continue
            if 'create_client' in line or 'establish_session' in line or 'create_datawriter' in line:
                client_events.append({'line': number, 'text': line})
        matrix.append({'link': 'DDS publisher endpoint -> XRCE client/session', 'state': 'MISSING',
                       'supports': {'agent_pid': archive.agent['pid'], 'agent_exe_sha256': archive.agent['exe_sha256'],
                                    'xrce_records': client_events},
                       'unknown': ['No retained record joins native DDS GUID/GID to client_key and XRCE writer object.',
                                   'Session 0x81 and object IDs are scoped per client and recur across clients.',
                                   'The GID byte suffix is not decoded as an XRCE object number.'],
                       'evidence': [archive.ref('effective_readonly_report.json', 'processes: exact micro_ros_agent argv/exe hash'),
                                    archive.file_ref(log)]})
        matrix.append({'link': 'XRCE client/session -> SYSID and SITL instance', 'state': 'CONFIGURATION_ONLY',
                       'supports': {'rover_process': archive.rover,
                                    'sysid_setting_log': settings,
                                    'client_sessions': [e for e in client_events if 'create_client' in e['text'] or 'establish_session' in e['text']]},
                       'unknown': ['No retained socket/process/client-key mapping or exact runtime parameter readback.',
                                   'Reference key-base/name construction needs executable provenance; numeric similarity alone is not binding.'],
                       'evidence': [archive.ref('effective_readonly_report.json', 'ardurover argv --instance 2 --sysid 3, start_ticks/exe hash'), archive.file_ref(log)]})
        params_path = archive._argument(archive.bridge['argv'], '--params-file')
        matrix.append({'link': 'SITL instance -> bridge/configuration', 'state': 'SAME_START_CONFIGURATION',
                       'supports': {'bridge_process': archive.bridge, 'context': archive.context,
                                    'effective_bridge_configuration_sha256': archive.bridge_config['sha256']},
                       'unknown': ['Same protected launch is not proof that a DDS Status endpoint originates in this SITL process.'],
                       'evidence': [archive.ref('capture/execution.json', 'context and protected start'),
                                    archive.ref('container_processes_before_close.stdout', 'process identities in one container boot'),
                                    archive.file_ref(archive.original_path(params_path)), archive.file_ref(archive.bridge_config)]})
        matrix.append({'link': 'bridge/configuration -> Gazebo model', 'state': 'CONFIGURATION_MAPPING_OBSERVED',
                       'supports': archive.odometry_mapping,
                       'unknown': ['Configuration maps the Gazebo topic name; no model-instance/plugin/UDP association was captured.',
                                   'Human visual confirmation does not bind GID or SYSID to the rendered rover.'],
                       'evidence': [archive.file_ref(archive.bridge_config), archive.file_ref(archive.launch),
                                    archive.ref('operator_visual_confirmation.json', 'operator observation only')]})
        result.update(evidence_valid=True, first_missing_link='DDS publisher endpoint -> XRCE client/session',
                      existing_contract={'source': 'tools.rover_environment_identity.assess_identity / RoverEnvironmentGuard',
                        'not_evaluated_as_current': True,
                        'unchanged_requirements': ['protected environment/launch/worker process identities',
                          'unique correctly typed source per stream and required frames',
                          'recent observations and progressing source in justified clocks',
                          'XRCE/SYSID/DDS namespace and effective bridge/model association'],
                        'remaining': ['This archive is historical, not fresh evidence.',
                          'Only one Status cannot establish progression.',
                          'Python worker still supplies publisher_gid=None; no passive C++ data is transplanted into it.',
                          'Existing guard continues to raise even for consistent snapshots; no gate change here.']})
    except Exception as exc:
        result.update(evidence_valid=False, matrix=[], first_missing_link=None,
                      errors=[f'{type(exc).__name__}: {exc}'])
    return result
