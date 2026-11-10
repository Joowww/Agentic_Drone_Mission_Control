"""Bounded read-only MAVLink parameter capture over an injected connection.

This module never opens a transport. The caller must supply an already-created
connection plus separately acquired process/socket/lifecycle provenance. A
heartbeat and matching PARAM_VALUE messages identify a MAVLink target; they do
not by themselves prove which process or firmware produced them.
"""
from datetime import datetime, timezone
import math
from typing import TypedDict
import time

DEFAULT_PARAMETERS = (
    'MAV_SYSID', 'DDS_USE_NS', 'GUID_TIMEOUT', 'ATC_ACCEL_MAX',
    'ATC_DECEL_MAX', 'FS_GCS_ENABLE', 'FS_ACTION', 'FS_TIMEOUT',
    'FS_THR_ENABLE', 'FS_THR_VALUE', 'FS_EKF_ACTION', 'FS_EKF_THRESH',
    'FS_OPTIONS', 'FS_GCS_TIMEOUT',
)
MAX_TIMEOUT_S = 5.0
MAX_PARAMETERS = 32
SOCKET_ASSOCIATION = 'SOCKET_OWNER_AND_MAVLINK_TARGET_CORRELATED'


class ParameterCapture(TypedDict, total=False):
    schema: str
    status: str
    reason: str | None
    values: dict[str, float]
    responses: list[dict]
    live_read: bool | None
    movement_authorized: bool
    capture_complete: bool
    source_association: str
    target_system: int | None
    target_component: int | None
    host_boot_id: str | None
    lifecycle_id: str | None
    target_process: dict | None
    firmware_sha256: str | None
    rejection_reasons: list[str]
    sequence_integrity: str
    late_message_check: str


def _sequence(msg):
    getter=getattr(msg,'get_seq',None)
    value=getter() if callable(getter) else None
    return value if type(value) is int and 0 <= value <= 255 else None


def _received_monotonic(msg):
    value=getattr(msg,'tfg_received_monotonic_s',None)
    return value if isinstance(value,(int,float)) and not isinstance(value,bool) and math.isfinite(value) else None


def _utc_now():
    return datetime.now(timezone.utc).isoformat()


def _valid_sha256(value):
    return (isinstance(value, str) and len(value) == 64
            and all(c in '0123456789abcdef' for c in value))


def _source(msg):
    return msg.get_srcSystem(), msg.get_srcComponent()


def _json_safe(value):
    if isinstance(value, (bytes, bytearray, memoryview)):
        return bytes(value).hex()
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    return value


def _param_id(msg):
    value = msg.param_id
    if isinstance(value, bytes):
        value = value.split(b'\0', 1)[0].decode('ascii', errors='strict')
    return str(value).split('\0', 1)[0].strip()


def _provenance_status(provenance, connection_identity, target_process,
                       lifecycle_id, host_boot_id, firmware_sha256):
    """Validate the supplied socket/process join; never infer it from MAVLink."""
    required_identity = ('pid', 'start_ticks', 'exe_sha256')
    process_ok = (isinstance(target_process, dict)
                  and type(target_process.get('pid')) is int and target_process['pid']>0
                  and type(target_process.get('start_ticks')) is int and target_process['start_ticks']>0
                  and _valid_sha256(target_process.get('exe_sha256')))
    endpoint_ok = (isinstance(connection_identity, dict)
                   and all(connection_identity.get(k) not in (None, '')
                           for k in ('local_endpoint', 'remote_endpoint', 'transport')))
    joined = (isinstance(provenance, dict)
              and provenance.get('socket_owner_verified') is True
              and provenance.get('connection_identity') == connection_identity
              and provenance.get('target_process') == target_process
              and provenance.get('lifecycle_id') == lifecycle_id
              and provenance.get('host_boot_id') == host_boot_id
              and provenance.get('firmware_sha256') == firmware_sha256)
    if (process_ok and endpoint_ok and joined and isinstance(lifecycle_id, str)
            and lifecycle_id and isinstance(host_boot_id, str) and host_boot_id
            and _valid_sha256(firmware_sha256)):
        return SOCKET_ASSOCIATION, []
    return 'UNVERIFIED', ['SOCKET_PROCESS_FIRMWARE_LIFECYCLE_JOIN_MISSING']


def collect(connection, *, lifecycle_id, host_boot_id, target_process,
            connection_identity, firmware_sha256, provenance=None,
            parameters=DEFAULT_PARAMETERS, timeout_s=2.0, utc=_utc_now,
            monotonic=time.monotonic) -> ParameterCapture:
    """Read one bounded set from an injected pymavlink-like link.

    Performs no connect/open/close calls and sends only PARAM_REQUEST_READ.
    There are no retries. Each response must match both the heartbeat-selected
    SYSID/COMPID and its requested parameter name. Missing data stays missing.
    """
    if (isinstance(timeout_s, bool) or not isinstance(timeout_s, (int, float))
            or not math.isfinite(timeout_s) or not 0 < timeout_s <= MAX_TIMEOUT_S):
        raise ValueError('MAVLink read timeout must be in (0, 5] seconds')
    try:
        raw_names=tuple(parameters)
        names=tuple(n.strip().upper() if isinstance(n,str) else n for n in raw_names)
        encoded=tuple(n.encode('ascii') if isinstance(n,str) else b'' for n in names)
    except (UnicodeEncodeError,TypeError,AttributeError) as exc:
        raise ValueError('Invalid MAVLink parameter name set') from exc
    if (not names or len(names) > MAX_PARAMETERS or len(set(names)) != len(names)
            or any(not isinstance(n,str) or not n or len(b)>16 for n,b in zip(names,encoded))):
        raise ValueError('Invalid MAVLink parameter name set')

    started_utc, started = utc(), monotonic()
    heartbeat_deadline = started + timeout_s
    deadline = started + (len(names) + 1) * timeout_s
    heartbeat = None
    transport_error=None
    while monotonic() < heartbeat_deadline:
        try:
            msg = connection.recv_match(type='HEARTBEAT', blocking=True,
                                        timeout=max(0.0, heartbeat_deadline-monotonic()))
        except Exception as exc:
            transport_error='TRANSPORT_ERROR:'+type(exc).__name__; break
        if msg is None:
            break
        if msg.get_type() == 'HEARTBEAT':
            heartbeat = msg
            break
    if heartbeat is None:
        return _result('INCOMPLETE', transport_error or 'HEARTBEAT_MISSING', started_utc, utc(), {},
                       None, None, None, None, None, target_process, connection_identity,
                       lifecycle_id, host_boot_id, firmware_sha256, provenance)

    heartbeat_at_utc, heartbeat_monotonic = utc(), monotonic()
    sysid, compid = _source(heartbeat)
    heartbeat_record = {'received_at_utc': heartbeat_at_utc,
                        'received_monotonic_s': heartbeat_monotonic,
                        'system_id': sysid, 'component_id': compid,
                        'vehicle_type': getattr(heartbeat, 'type', None),
                        'autopilot': getattr(heartbeat, 'autopilot', None),
                        'mavlink_version': getattr(heartbeat, 'mavlink_version', None)}
    firmware_report = None
    firmware_transport_error=None
    try:
        version = connection.recv_match(type='AUTOPILOT_VERSION', blocking=False)
    except TypeError:
        version = None
    except Exception as exc:
        version = None
        firmware_transport_error='TRANSPORT_ERROR:'+type(exc).__name__
    if version is not None and version.get_type() == 'AUTOPILOT_VERSION' and _source(version) == (sysid, compid):
        firmware_report = {name: _json_safe(getattr(version, name, None)) for name in
                           ('flight_sw_version', 'middleware_sw_version', 'os_sw_version',
                            'board_version', 'vendor_id', 'product_id', 'uid', 'uid2')}
        firmware_report['received_at_utc'] = utc()
        firmware_report['received_monotonic_s'] = monotonic()
    if (type(sysid) is not int or not 1 <= sysid <= 255
            or type(compid) is not int or not 1 <= compid <= 255):
        raise ValueError('Heartbeat has invalid source SYSID/COMPID')

    values, rows = {}, []
    rejected=[firmware_transport_error] if firmware_transport_error else []; seen_sequences=set(); last_sequence=None
    for name in names:
        request_started_utc = utc()
        request_started = monotonic()
        # PARAM_REQUEST_READ is a read request; no PARAM_SET/control messages.
        try:
            connection.mav.param_request_read_send(sysid, compid, name.encode('ascii'), -1)
        except Exception as exc:
            transport_error='TRANSPORT_ERROR:'+type(exc).__name__
            rejected.append(transport_error)
            rows.append({'name':name,'status':'MISSING','reason':transport_error,
                         'request_started_at_utc':request_started_utc,'request_started_monotonic_s':request_started})
            break
        request_deadline = min(deadline, request_started + timeout_s)
        found = None
        while monotonic() < request_deadline:
            try:
                msg = connection.recv_match(type='PARAM_VALUE', blocking=True,
                                            timeout=max(0.0, request_deadline-monotonic()))
            except Exception as exc:
                transport_error='TRANSPORT_ERROR:'+type(exc).__name__
                rejected.append(transport_error); break
            if msg is None:
                break
            if msg.get_type() != 'PARAM_VALUE':
                continue
            if _source(msg) != (sysid, compid):
                rejected.append('MAVLINK_SOURCE_MISMATCH')
                continue
            seq=_sequence(msg); received=_received_monotonic(msg); observed_now=monotonic()
            if seq is None:
                rejected.append('MAVLINK_SEQUENCE_MISSING_OR_INVALID'); continue
            if received is None:
                rejected.append('RECEIPT_MONOTONIC_MISSING'); continue
            if received < request_started or received > observed_now:
                rejected.append('LATE_OR_FUTURE_PARAM_VALUE'); continue
            if seq in seen_sequences or (last_sequence is not None and not 0 < ((seq-last_sequence) % 256) <= 127):
                rejected.append('MAVLINK_SEQUENCE_DUPLICATE_OR_NONMONOTONIC'); continue
            try:
                response_name = _param_id(msg)
            except (UnicodeDecodeError, AttributeError, TypeError):
                continue
            if response_name.strip().upper() != name:
                continue
            value = msg.param_value
            index=getattr(msg,'param_index',None); count=getattr(msg,'param_count',None); kind=getattr(msg,'param_type',None)
            if type(index) is not int or type(count) is not int or count<1 or not 0<=index<count:
                rejected.append('PARAMETER_INDEX_METADATA_INVALID'); continue
            if type(kind) is not int or not 1<=kind<=10:
                rejected.append('PARAMETER_TYPE_INVALID'); continue
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
                rejected.append('PARAMETER_VALUE_INVALID'); continue
            found = (float(value), msg, seq, received)
            seen_sequences.add(seq); last_sequence=seq
            break
        observed_utc, observed = utc(), monotonic()
        if found is None:
            rows.append({'name': name, 'status': 'MISSING',
                         'request_started_at_utc': request_started_utc,
                         'observed_at_utc': observed_utc,
                         'request_started_monotonic_s': request_started,
                         'observed_monotonic_s': observed,
                         'duration_s': observed-request_started})
            continue
        value, msg, seq, received = found
        values[name] = value
        rows.append({'name': name, 'status': 'OBSERVED', 'value': value,
                     'param_type': getattr(msg, 'param_type', None),
                     'param_count': getattr(msg, 'param_count', None),
                     'param_index': getattr(msg, 'param_index', None),
                     'packet_sequence':seq,'received_monotonic_s':received,
                     'request_started_at_utc': request_started_utc,
                     'observed_at_utc': observed_utc,
                     'request_started_monotonic_s': request_started,
                     'observed_monotonic_s': observed,
                     'duration_s': observed-request_started})
    status = 'COMPLETE' if len(values) == len(names) and not rejected and not transport_error else 'INCOMPLETE'
    reason = None if status == 'COMPLETE' else (transport_error or (';'.join(sorted(set(rejected))) if rejected else 'PARAMETER_RESPONSE_MISSING'))
    return _result(status, reason, started_utc, utc(), values, sysid, compid,
                   getattr(heartbeat, 'autopilot', None), heartbeat_record,
                   firmware_report, target_process, connection_identity,
                   lifecycle_id, host_boot_id, firmware_sha256, provenance, rows, rejected)


def _result(status, reason, started_utc, finished_utc, values, sysid, compid,
            autopilot, heartbeat, firmware_report, target_process,
            connection_identity, lifecycle_id, host_boot_id, firmware_sha256,
            provenance, rows=None, rejected=None) -> ParameterCapture:
    association, provenance_reasons = _provenance_status(
        provenance, connection_identity, target_process, lifecycle_id,
        host_boot_id, firmware_sha256)
    return {
        'schema': 'tfg.rover.mavlink-parameter-capture/2',
        'status': status,
        'reason': reason,
        'rejection_reasons': list(rejected or []),
        'sequence_integrity': 'VERIFIED_FOR_CAPTURED_RESPONSES' if rows and all('packet_sequence' in r for r in rows if r.get('status')=='OBSERVED') and not rejected else 'INCOMPLETE_OR_UNAVAILABLE',
        'late_message_check': 'RECEIPT_MONOTONIC_BOUND_TO_REQUEST' if rows and all('received_monotonic_s' in r for r in rows if r.get('status')=='OBSERVED') else 'UNAVAILABLE',
        'source_association': association,
        'provenance_reasons': provenance_reasons,
        'live_read': None,
        'live_read_status': 'NOT_INDEPENDENTLY_ATTESTED',
        'host_boot_id': host_boot_id,
        'lifecycle_id': lifecycle_id,
        'target_process': target_process,
        'connection_identity': connection_identity,
        'firmware_sha256': firmware_sha256,
        'target_system': sysid,
        'target_component': compid,
        'autopilot': autopilot,
        'heartbeat': heartbeat,
        'autopilot_version_report': firmware_report,
        'firmware_report_status': 'OBSERVED' if firmware_report is not None else 'NOT_OBSERVED',
        'started_at_utc': started_utc,
        'finished_at_utc': finished_utc,
        'values': values,
        'responses': rows or [],
        'atomic_snapshot': False,
        'parameter_writes': 0,
        'control_messages_sent': 0,
        'eligible_for_motion_admission': False,
        'movement_authorized': False,
        'capture_complete': status == 'COMPLETE',
    }
