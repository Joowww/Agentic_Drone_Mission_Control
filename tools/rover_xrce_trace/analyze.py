"""Offline validation of opt-in native diagnostics; never an identity gate."""
import json
import re
import ipaddress


def analyze(lines):
    result = {'schema': 'tfg.xrce-writer-analysis/1', 'status': 'BLOCKED',
              'source_association_verified': False, 'movement_authorized': False,
              'correlations': [], 'errors': [], 'trace_valid': False}
    try:
        attempts, processes, sequences, clients = {}, set(), set(), {}
        for line in lines:
            if 'TFG_XRCE_TRACE ' not in line:
                continue
            row = json.loads(line.split('TFG_XRCE_TRACE ', 1)[1])
            if row.get('schema') != 'tfg.xrce-writer/1':
                raise ValueError('Unsupported schema')
            process = (row.get('boot_id'), row.get('pid'), row.get('process_start_ticks'))
            if (not isinstance(process[0], str) or not process[0] or type(process[1]) is not int
                    or process[1] <= 0 or not isinstance(process[2], str) or not process[2].isdigit()):
                raise ValueError('Process identity missing')
            processes.add(process)
            if len(processes) != 1:
                raise ValueError('Mixed process/session evidence')
            for field in ('sequence', 'wall_unix_ns', 'steady_ns'):
                if type(row.get(field)) is not int or row[field] <= 0:
                    raise ValueError('Missing diagnostic timestamp/sequence')
            if row['sequence'] > 512:
                raise ValueError('Sequence exceeds native trace bound')
            if row['sequence'] in sequences:
                raise ValueError('Duplicate event sequence')
            sequences.add(row['sequence'])
            if row.get('incomplete') or row.get('event') not in ('dds_writer', 'xrce_result'):
                raise ValueError('Incomplete/error/capped trace')
            for field in ('client_instance', 'attempt', 'client_key', 'session_id', 'writer_id'):
                if type(row.get(field)) is not int or row[field] < 0:
                    raise ValueError('Missing explicit XRCE context')
            client = row['client_instance']
            signature = (row['client_key'], row['session_id'])
            if client in clients and clients[client] != signature:
                raise ValueError('Client generation has contradictory key/session')
            clients[client] = signature
            key = row['attempt']
            group = attempts.setdefault(key, {})
            if row['event'] in group:
                raise ValueError('Duplicate/contradictory attempt record')
            group[row['event']] = row
        if sequences and sequences != set(range(1, max(sequences)+1)):
            raise ValueError('Missing diagnostic sequence: truncated or mixed excerpt')
        if not attempts:
            raise ValueError('No diagnostic records')
        owners, candidates = {}, []
        for events in attempts.values():
            commit, writer = events.get('xrce_result'), events.get('dds_writer')
            if commit is None or type(commit.get('committed')) is not bool:
                raise ValueError('Missing explicit XRCE completion')
            if not commit['committed']:
                if writer:
                    raise ValueError('Native writer was not committed to XRCE object table')
                continue  # failed creation cannot yield an association
            if writer is None:
                raise ValueError('Committed XRCE object has no native writer record')
            if any(commit[k] != writer[k] for k in ('client_instance', 'client_key', 'session_id', 'writer_id')):
                raise ValueError('Contradictory explicit context')
            if writer['steady_ns'] > commit['steady_ns']:
                raise ValueError('Result precedes synchronous writer creation')
            for field, length in [('native_guid', 32), ('rmw_gid', 48)]:
                if not isinstance(writer.get(field), str) or not re.fullmatch('[0-9a-f]{'+str(length)+'}', writer[field]) or set(writer[field]) == {'0'}:
                    raise ValueError('Missing/noninterpretable GUID/GID')
            if writer.get('rmw_identifier') != 'rmw_fastrtps_cpp':
                raise ValueError('Unexpected conversion contract')
            if any(not isinstance(writer.get(k), str) or not writer[k] for k in ('topic', 'type')) or type(writer.get('domain')) is not int:
                raise ValueError('Topic/type/domain absent')
            if writer.get('transport_peer') != commit.get('transport_peer'):
                raise ValueError('Writer/commit peer context contradiction')
            peer = writer.get('transport_peer')
            if peer is not None:
                if (not isinstance(peer, dict) or peer.get('family') != 'IPv4'
                        or peer.get('generation_binding') != 'SAME_PROXYCLIENT_REFERENCE'
                        or peer.get('source') != 'Processor InputMessage metadata before session queue'
                        or type(peer.get('port')) is not int or not 0 < peer['port'] <= 65535):
                    raise ValueError('Missing/unbound native peer contract')
                address = ipaddress.ip_address(peer['address'])
                if address.version != 4 or address.is_unspecified or str(address) != peer['address']:
                    raise ValueError('Non-normalized/unavailable UDPv4 peer')
            # Never join by object/session numbers, node names, timestamps or order.
            # Reused native identity is ambiguous, even across writer recreation.
            for field in ('native_guid', 'rmw_gid'):
                identity = (field, writer[field])
                if identity in owners:
                    raise ValueError('Native writer identity reused/contradictory')
                owners[identity] = writer['attempt']
            candidates.append(writer)
        result.update(trace_valid=True, correlations=candidates,
                      note='Explicit synchronous creation context only; not cryptographic authentication or full SITL/model identity.')
    except (ValueError, TypeError, KeyError) as exc:
        result.update(errors=[str(exc)], correlations=[])
    return result


UDP_PORT_SOURCE_SHA256 = '0d3d11252c58b65c85762390b5c79f72a2b9f4efdae6547b09da43a611a96217'


def normalized_udp_peer(writer, *, native_byte_order, transport_source_sha256):
    """Explicit interpretation only; never rewrites raw trace or historical reports.

    Pinned UDPv4Agent::recv_message in UDPv4AgentLinux.cpp stores sin_port directly
    in IPv4EndPoint. Native trace/get_port/formatter expose that network-order
    object as a native uint16_t. ELF EI_DATA establishes that integer's byte order.
    """
    if transport_source_sha256 != UDP_PORT_SOURCE_SHA256 or native_byte_order not in {'little','big'}:
        raise ValueError('UDP port contract/ELF byte order not established')
    peer=writer.get('transport_peer')
    if (not isinstance(peer,dict) or peer.get('family')!='IPv4' or
        peer.get('generation_binding')!='SAME_PROXYCLIENT_REFERENCE' or
        peer.get('source')!='Processor InputMessage metadata before session queue' or
        type(peer.get('port')) is not int or not 0<peer['port']<=65535):
        raise ValueError('Unavailable native UDP peer')
    return {'family':peer['family'],'address':peer['address'],
            'port':int.from_bytes(peer['port'].to_bytes(2,native_byte_order),'big')}
